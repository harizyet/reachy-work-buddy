"""Postgres-backed MeetingStore. See store.py for the interface.

Audio bytes are written under MEETING_AUDIO_DIR on the local filesystem,
not into a database column — same "large binaries don't belong in
Postgres rows" reasoning as reachy-hub's owner-recognition capture store
(docs/deployment.md#owner-recognition-benchmark-storage), except this
directory is always required (not optional/in-memory-fallback) because a
meeting recording surviving restart is 27.1's literal exit criterion.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from companion_core.meetings.models import (
    CANCELLABLE_STATUSES,
    ORPHAN_RESUME,
    Meeting,
    MeetingJobStatus,
    MeetingOutput,
)
from companion_core.meetings.store import MeetingNotCancellableError
from shared.database import check_schema

_COLUMNS = (
    "id, title, project_scope, context, participants, started_at, source_filename, content_type, "
    "audio_path, normalized_audio_path, duration_seconds, transcript_segments, diarization_segments, "
    "status, error_detail, created_at, updated_at, speaker_names, transcript_corrections, key_terms, summary, minutes, "
    "aligned_segments, audio_gaps"
)


def _from_row(row: tuple) -> Meeting:
    return Meeting(
        id=row[0],
        title=row[1],
        project_scope=row[2],
        context=row[3],
        participants=list(row[4] or []),
        started_at=row[5],
        source_filename=row[6],
        content_type=row[7],
        audio_path=row[8],
        normalized_audio_path=row[9],
        duration_seconds=row[10],
        transcript_segments=row[11],
        diarization_segments=row[12],
        status=MeetingJobStatus(row[13]),
        error_detail=row[14],
        created_at=row[15],
        updated_at=row[16],
        speaker_names=dict(row[17] or {}),
        transcript_corrections=dict(row[18] or {}),
        key_terms=list(row[19] or []),
        summary=MeetingOutput(**row[20]) if row[20] else None,
        minutes=MeetingOutput(**row[21]) if row[21] else None,
        aligned_segments=row[22],
        audio_gaps=row[23],
    )


class PostgresMeetingStore:
    def __init__(self, pool: AsyncConnectionPool, audio_dir: Path) -> None:
        self._pool = pool
        self._audio_dir = audio_dir
        self._audio_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    async def connect(cls, dsn: str, *, audio_dir: str | Path | None = None) -> PostgresMeetingStore:
        resolved_dir = Path(audio_dir or os.environ.get("MEETING_AUDIO_DIR") or "./data/meeting-audio")
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool, resolved_dir)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await self._pool.close()

    def _audio_file(self, meeting_id: str, audio_path: str) -> Path:
        # audio_path is always "<meeting_id>/<basename>" (set in
        # create_meeting), so this never escapes audio_dir even though the
        # id and extension both come from caller-controlled input.
        return self._audio_dir / meeting_id / Path(audio_path).name

    async def create_meeting(
        self,
        *,
        title: str,
        audio: bytes | BinaryIO,
        source_filename: str,
        content_type: str,
        project_scope: str | None = None,
        context: str | None = None,
        participants: list[str] | None = None,
        started_at: datetime | None = None,
    ) -> Meeting:
        meeting = Meeting(
            title=title,
            source_filename=source_filename,
            content_type=content_type,
            audio_path=f"{uuid.uuid4()}{Path(source_filename).suffix.lower()}",
            project_scope=project_scope,
            context=context,
            participants=list(participants or []),
            started_at=started_at,
        )
        target = self._audio_file(meeting.id, meeting.audio_path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        def write_audio():
            with target.open("wb") as destination:
                if isinstance(audio, bytes):
                    destination.write(audio)
                else:
                    shutil.copyfileobj(audio, destination, length=1024 * 1024)

        await asyncio.to_thread(write_audio)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO meetings ({_COLUMNS}) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    meeting.id, meeting.title, meeting.project_scope, meeting.context, meeting.participants,
                    meeting.started_at, meeting.source_filename, meeting.content_type, meeting.audio_path,
                    meeting.normalized_audio_path, meeting.duration_seconds, None, None,
                    meeting.status.value, meeting.error_detail, meeting.created_at, meeting.updated_at,
                    Json({}), Json({}), Json([]), None, None, None, None,
                ),
            )
        return meeting

    async def get_meeting(self, meeting_id: str) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM meetings WHERE id = %s", (meeting_id,))
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def list_meetings(self) -> list[Meeting]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM meetings ORDER BY created_at DESC")
            rows = await cur.fetchall()
            return [_from_row(row) for row in rows]

    async def load_audio(self, meeting_id: str) -> bytes:
        meeting = await self.get_meeting(meeting_id)
        if meeting is None:
            raise KeyError(meeting_id)
        path = meeting.normalized_audio_path or meeting.audio_path
        return await asyncio.to_thread(self._audio_file(meeting_id, path).read_bytes)

    async def open_audio(self, meeting_id: str) -> BinaryIO:
        meeting = await self.get_meeting(meeting_id)
        if meeting is None:
            raise KeyError(meeting_id)
        path = meeting.normalized_audio_path or meeting.audio_path
        return await asyncio.to_thread(self._audio_file(meeting_id, path).open, "rb")

    async def claim_next_upload(self) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                UPDATE meetings SET status = %s, updated_at = now()
                WHERE id = (
                    SELECT id FROM meetings WHERE status = %s ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                RETURNING {_COLUMNS}
                """,
                (MeetingJobStatus.PREPROCESSING.value, MeetingJobStatus.UPLOADED.value),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def requeue_orphaned(self) -> int:
        total = 0
        async with self._pool.connection() as conn:
            for stuck_status, resume_to in ORPHAN_RESUME.items():
                cur = await conn.execute(
                    "UPDATE meetings SET status = %s, updated_at = now() WHERE status = %s RETURNING id",
                    (resume_to.value, stuck_status.value),
                )
                total += len(await cur.fetchall())
        return total

    async def mark_preprocessed(
        self, meeting_id: str, *, normalized_audio_path: str | None, duration_seconds: float | None
    ) -> Meeting | None:
        # A cancel can race a stage already in flight (single bounded
        # worker, but an owner-initiated cancel is a separate HTTP
        # request) — the WHERE status guard means a late stage completion
        # after a cancel/fail is a no-op, not a resurrection.
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                UPDATE meetings SET status = %s, normalized_audio_path = %s, duration_seconds = %s, updated_at = now()
                WHERE id = %s AND status = %s RETURNING {_COLUMNS}
                """,
                (
                    MeetingJobStatus.TRANSCRIBING.value, normalized_audio_path, duration_seconds,
                    meeting_id, MeetingJobStatus.PREPROCESSING.value,
                ),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else await self.get_meeting(meeting_id)

    async def claim_next_transcription(self) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM meetings WHERE status = %s ORDER BY created_at LIMIT 1",
                (MeetingJobStatus.TRANSCRIBING.value,),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def claim_next_diarization(self) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM meetings WHERE status = %s ORDER BY created_at LIMIT 1",
                (MeetingJobStatus.DIARIZING.value,),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def mark_transcribed(
        self, meeting_id: str, *, transcript_segments: list[dict[str, Any]]
    ) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                UPDATE meetings SET status = %s, transcript_segments = %s, updated_at = now()
                WHERE id = %s AND status = %s RETURNING {_COLUMNS}
                """,
                (MeetingJobStatus.DIARIZING.value, Json(transcript_segments), meeting_id, MeetingJobStatus.TRANSCRIBING.value),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else await self.get_meeting(meeting_id)

    async def mark_diarized(
        self, meeting_id: str, *, diarization_segments: list[dict[str, Any]]
    ) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                UPDATE meetings SET status = %s, diarization_segments = %s, updated_at = now()
                WHERE id = %s AND status = %s RETURNING {_COLUMNS}
                """,
                (MeetingJobStatus.ALIGNING.value, Json(diarization_segments), meeting_id, MeetingJobStatus.DIARIZING.value),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else await self.get_meeting(meeting_id)

    async def claim_next_alignment(self) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM meetings WHERE status = %s ORDER BY created_at LIMIT 1",
                (MeetingJobStatus.ALIGNING.value,),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def mark_aligned(self, meeting_id: str, *, aligned_segments: list[dict[str, Any]]) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                UPDATE meetings SET status = %s, aligned_segments = %s, updated_at = now()
                WHERE id = %s AND status = %s RETURNING {_COLUMNS}
                """,
                (MeetingJobStatus.COMPLETE.value, Json(aligned_segments), meeting_id, MeetingJobStatus.ALIGNING.value),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else await self.get_meeting(meeting_id)

    async def claim_next_audio_check(self) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM meetings WHERE status = %s AND audio_gaps IS NULL ORDER BY created_at LIMIT 1",
                (MeetingJobStatus.COMPLETE.value,),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def set_audio_gaps(self, meeting_id: str, gaps: dict[str, Any]) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE meetings SET audio_gaps = %s, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
                (Json(gaps), meeting_id),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def mark_failed(self, meeting_id: str, *, error_detail: str) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE meetings SET status = %s, error_detail = %s, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
                (MeetingJobStatus.FAILED.value, error_detail, meeting_id),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def cancel_meeting(self, meeting_id: str) -> Meeting | None:
        cancellable = [s.value for s in CANCELLABLE_STATUSES]
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                UPDATE meetings SET status = %s, updated_at = now()
                WHERE id = %s AND status = ANY(%s) RETURNING {_COLUMNS}
                """,
                (MeetingJobStatus.CANCELLED.value, meeting_id, cancellable),
            )
            row = await cur.fetchone()
            if row:
                return _from_row(row)
            existing = await self.get_meeting(meeting_id)
            if existing is None:
                return None
            raise MeetingNotCancellableError(f"meeting '{meeting_id}' is past the cancellable stage")

    async def set_speaker_names(self, meeting_id: str, names: dict[str, str]) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE meetings SET speaker_names = %s, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
                (Json(names), meeting_id),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def set_correction(self, meeting_id: str, segment: int, text: str | None) -> Meeting | None:
        async with self._pool.connection() as conn:
            if text is None:
                cur = await conn.execute(
                    f"UPDATE meetings SET transcript_corrections = transcript_corrections - %s, updated_at = now() "
                    f"WHERE id = %s RETURNING {_COLUMNS}",
                    (str(segment), meeting_id),
                )
            else:
                cur = await conn.execute(
                    f"UPDATE meetings SET transcript_corrections = transcript_corrections || %s::jsonb, updated_at = now() "
                    f"WHERE id = %s RETURNING {_COLUMNS}",
                    (Json({str(segment): text}), meeting_id),
                )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def set_corrections(self, meeting_id: str, updates: dict[int, str]) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE meetings SET transcript_corrections = transcript_corrections || %s::jsonb, updated_at = now() "
                f"WHERE id = %s RETURNING {_COLUMNS}",
                (Json({str(i): t for i, t in updates.items()}), meeting_id),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def set_key_terms(self, meeting_id: str, terms: list[str]) -> Meeting | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE meetings SET key_terms = %s, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
                (Json(terms), meeting_id),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def list_terms(self) -> list[str]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT term FROM meeting_terms ORDER BY lower(term)")
            return [row[0] for row in await cur.fetchall()]

    async def add_term(self, term: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("INSERT INTO meeting_terms (term) VALUES (%s) ON CONFLICT DO NOTHING", (term,))

    async def delete_term(self, term: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM meeting_terms WHERE lower(term) = lower(%s)", (term,))
            return cur.rowcount > 0

    async def set_output(self, meeting_id: str, kind: str, output: MeetingOutput | None) -> Meeting | None:
        if kind not in ("summary", "minutes"):
            raise ValueError(kind)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE meetings SET {kind} = %s, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
                (Json(output.model_dump(mode="json")) if output else None, meeting_id),
            )
            row = await cur.fetchone()
            return _from_row(row) if row else None

    async def delete_meeting(self, meeting_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))
            deleted = cur.rowcount > 0
        if deleted:
            await asyncio.to_thread(shutil.rmtree, self._audio_dir / meeting_id, True)
        return deleted
