"""Phase 49: enqueue, process, review and commit. Everything here is deterministic code around two narrow model calls (extract only); the model never writes.

Enqueue snapshots the note and returns at once; a bounded runner processes jobs later. Accept is the only path from a proposal to a task or reminder: it claims the proposal
(pending -> accepting), creates the record under an id derived from the proposal (so a retry, a double click or a crash cannot create a second one), links provenance, writes the
existing receipt, then closes the proposal. Every step is safe to run again."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from companion_core.meetings.outputs import transcript_lines
from companion_core.notepad_processing import extraction, links
from companion_core.notepad_processing.models import (
    MAX_LINKED_MEETINGS,
    MAX_SNAPSHOT_CHARS,
    MAX_TEXT,
    MAX_TRANSCRIPT_CHARS,
    Job,
    JobSource,
    JobStatus,
    Kind,
    Proposal,
    ProposalStatus,
    Provenance,
    content_hash,
    record_id_for,
    utcnow,
)
from companion_core.notepad_processing.store import OPEN_PROPOSALS, NotepadStore
from companion_core.privacy_classifier import classify_privacy
from shared.models.receipt import ActionReceipt
from shared.models.response import Privacy

log = logging.getLogger("companion_core.notepad_processing")

ENABLED_FLAG = "NOTEPAD_PROCESSING_ENABLED"
CONCURRENCY_ENV = "NOTEPAD_PROCESSING_CONCURRENCY"
JOB_TIMEOUT_SECONDS = 180.0
POLL_SECONDS = 5.0
_RECEIPT_NAMESPACE = uuid.UUID("49a0c0de-4949-4949-8949-49a0c0de4950")
_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}
UNSET = object()

# What the runner needs from the model layer: a local-only completion and the model's name, or None when no local model is configured.
Provider = Callable[[], Awaitable[tuple[extraction.Ask, str] | None]]


def enabled() -> bool:
    import os

    return os.environ.get(ENABLED_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


class NotepadError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def state_of(job: Job | None, proposals: list[Proposal]) -> str:
    """The owner-facing processing state of a note."""
    if job is None:
        return "not_processed"
    if job.status is JobStatus.QUEUED:
        return "queued"
    if job.status is JobStatus.PROCESSING:
        return "processing"
    if job.status is JobStatus.FAILED:
        return "failed"
    return "review_required" if any(p.status in OPEN_PROPOSALS for p in proposals) else "completed"


@dataclass
class NotepadService:
    store: NotepadStore
    planner: object  # notes, reminders, receipts
    tasks: object
    timezone: Callable[[], Awaitable[str]]
    provider: Provider | None = None
    meetings: object | None = None  # the meeting store; None leaves meeting links unavailable
    clock: Callable[[], datetime] = utcnow
    counters: dict[str, int] = None  # type: ignore[assignment]
    wake: asyncio.Event = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.counters = {}
        self.wake = asyncio.Event()

    def _count(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    # -- 49A: enqueue and status -----------------------------------------------------------------------------------------------

    async def enqueue(self, note_id: str, *, force: bool = False, expected_hash: str | None = None, include_meetings: bool = False) -> dict:
        note = await self.planner.get_note(note_id)
        if note is None:
            raise NotepadError(404, "No such note")
        body = note.body
        if not body.strip():
            raise NotepadError(422, "The note is empty")
        if len(body) > MAX_SNAPSHOT_CHARS:
            raise NotepadError(422, "The note is too long to process")
        digest = content_hash(body)
        if expected_hash is not None and expected_hash != digest:
            raise NotepadError(409, "The note changed since it was saved; save it again")
        sources = await self._sources(note_id) if include_meetings else []
        included = sorted((x.meeting_id, x.hash) for x in sources if x.included)
        job = Job(note_id=note.id, note_title=note.title, snapshot_text=body, snapshot_hash=digest, note_updated_at=note.updated_at, timezone=await self.timezone(),
                  sensitivity=note.sensitivity, project_scope=note.project_scope, reprocess=force, created_at=self.clock(), sources=sources,
                  inputs_hash=content_hash(digest + "|" + "|".join(f"{m}:{h}" for m, h in included)))
        _, created = await self.store.enqueue(job, force=force)
        if created:
            self._count("enqueued")
            self.wake.set()
        return {"created": created, **await self.status(note_id)}

    async def _sources(self, note_id: str) -> list[JobSource]:
        """The CONFIRMED linked meetings, snapshotted for one job. A meeting whose transcript is not ready yet is listed but not included: the note is still processed, and the
        owner can reprocess once the transcript exists. Nothing waits for transcription."""
        if self.meetings is None:
            return []
        out: list[JobSource] = []
        total = 0
        for link in (await self.store.list_links(note_id=note_id, states=("confirmed",)))[:MAX_LINKED_MEETINGS]:
            meeting = await self.meetings.get_meeting(link.meeting_id)
            if meeting is None:
                out.append(JobSource(meeting_id=link.meeting_id, title="(deleted meeting)", reason="the meeting no longer exists"))
            elif not links.transcript_ready(meeting):
                out.append(JobSource(meeting_id=meeting.id, title=meeting.title, started_at=meeting.started_at, reason="the transcript is not ready yet"))
            else:
                text = "\n".join(transcript_lines(meeting))
                total += len(text)
                if total > MAX_TRANSCRIPT_CHARS:
                    raise NotepadError(422, "The linked meeting transcripts are too long to process together")
                out.append(JobSource(meeting_id=meeting.id, title=meeting.title, started_at=meeting.started_at, included=True, text=text, hash=content_hash(text),
                                     sensitivity=meeting.sensitivity))
        return out

    # -- 49G: note <-> meeting links -----------------------------------------------------------------------------------------------

    async def links_for(self, note_id: str, *, refresh: bool = True) -> dict:
        """The note's suggested and confirmed meeting links. With `refresh`, new time-overlap suggestions are stored first (only suggestions; nothing is confirmed)."""
        note = await self.planner.get_note(note_id)
        if note is None:
            raise NotepadError(404, "No such note")
        if self.meetings is None:
            return {"note_id": note_id, "links": []}
        known = {m.id: m for m in await self.meetings.list_meetings()}
        if refresh:
            candidates = [(link, known[link.meeting_id]) for m in known.values() if (link := links.suggestion(note, m)) is not None]
            for link, meeting in sorted(candidates, key=lambda c: links.rank(note, *c))[:links.MAX_SUGGESTIONS]:
                await self.store.suggest_link(link)
        rows = await self.store.list_links(note_id=note_id, states=("suggested", "confirmed"))
        return {"note_id": note_id, "links": [{**row.model_dump(mode="json"), "meeting": links.meeting_view(known.get(row.meeting_id)), "meeting_missing": row.meeting_id not in known}
                                              for row in rows]}

    async def set_link(self, note_id: str, meeting_id: str, state: str) -> dict:
        """The owner's decision: confirm (also the explicit link from inside a meeting) or reject/unlink. Neither changes the note or the meeting."""
        if state not in ("confirmed", "rejected"):
            raise NotepadError(422, "State must be confirmed or rejected")
        if await self.planner.get_note(note_id) is None:
            raise NotepadError(404, "No such note")
        if self.meetings is None:
            raise NotepadError(503, "Meetings are unavailable")
        existing = (await self.store.list_links(note_id=note_id, meeting_id=meeting_id))
        if await self.meetings.get_meeting(meeting_id) is None and not existing:
            raise NotepadError(404, "No such meeting")
        await self.store.set_link(note_id, meeting_id, state=state, now=self.clock())
        return await self.links_for(note_id, refresh=False)

    async def meeting_deleted(self, meeting_id: str) -> None:
        with contextlib.suppress(Exception):
            await self.store.drop_links(meeting_id=meeting_id)

    async def status(self, note_id: str) -> dict:
        note = await self.planner.get_note(note_id)
        job = await self.store.latest_job(note_id)
        proposals = await self.store.list_proposals(note_id=note_id)
        current = content_hash(note.body) if note is not None else None
        return {
            "note_id": note_id,
            "state": state_of(job, proposals),
            "job": job.view() if job else None,
            "note_changed_since_job": bool(job and current is not None and current != job.snapshot_hash),
            "proposals": [p.view(current_hash=current) for p in proposals],
        }

    async def retry(self, job_id: str) -> dict:
        job, outcome = await self.store.retry_job(job_id, now=self.clock())
        if outcome == "missing":
            raise NotepadError(404, "No such job")
        if outcome == "not_failed":
            raise NotepadError(409, "Only a failed job can be retried")
        if outcome == "active":
            raise NotepadError(409, "This note is already being processed")
        self.wake.set()
        return await self.status(job.note_id)

    async def pending(self) -> dict:
        rows = await self.store.list_proposals(statuses=(*OPEN_PROPOSALS,))
        titles: dict[str, str | None] = {}
        out = []
        for p in rows:
            if p.note_id not in titles:
                note = await self.planner.get_note(p.note_id)
                titles[p.note_id] = note.title if note else None
            out.append({**p.view(), "note_title": titles[p.note_id]})
        return {"proposals": out}

    # -- 49B: the runner -----------------------------------------------------------------------------------------------------

    async def process_next(self) -> bool:
        """Claim and process one job. Returns whether there was one. Never raises."""
        job = await self.store.claim_next(self.clock())
        if job is None:
            return False
        try:
            offered = await self.provider() if self.provider is not None else None
            if offered is None:
                raise extraction.ExtractionFailed("model_unavailable")
            ask, model = offered
            async with asyncio.timeout(JOB_TIMEOUT_SECONDS):
                proposals, rejected = await extraction.extract(job, ask, model=model)
            added = await self.store.complete_job(job.id, proposals, model=model, now=self.clock())
            self._count("succeeded")
            self._count("proposals", added)
            for reason, n in rejected.counts.items():
                self._count(f"rejected_{reason}", n)
        except extraction.ExtractionFailed as exc:
            await self._fail(job, exc.code)
        except TimeoutError:
            await self._fail(job, "timeout")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors can carry URLs or text: log the type only
            log.warning("notepad job failed: %s", type(exc).__name__)
            await self._fail(job, "model_unavailable" if type(exc).__name__ == "ProviderUnavailable" else "internal_error")
        return True

    async def _fail(self, job: Job, code: str) -> None:
        self._count(f"failed_{code}")
        await self.store.fail_job(job.id, code, now=self.clock())

    # -- 49C / 49D: review and commit ------------------------------------------------------------------------------------------

    async def accept(self, proposal_id: str, *, text: str | None = None, kind: Kind | None = None, due_at=UNSET) -> dict:
        now = self.clock()
        p = await self.store.get_proposal(proposal_id)
        if p is None:
            raise NotepadError(404, "No such proposal")
        if p.status is ProposalStatus.ACCEPTED:
            return await self._result(p)  # a retry or a double click: the same record, nothing new
        if p.status in (ProposalStatus.DISMISSED, ProposalStatus.NOTED):
            raise NotepadError(409, "This item is not waiting for a decision")
        if p.status is ProposalStatus.PENDING:
            final_kind = kind or p.kind
            if final_kind is Kind.REFERENCE:
                raise NotepadError(409, "Reference information stays in the note")
            final_text = " ".join((text if text is not None else p.text).split())
            if not final_text or len(final_text) > MAX_TEXT:
                raise NotepadError(422, f"The text must be between 1 and {MAX_TEXT} characters")
            final_due = p.due_at if due_at is UNSET else due_at
            if final_kind is Kind.REMINDER:
                if final_due is None:
                    raise NotepadError(422, "A reminder needs a time")
                if final_due.tzinfo is None:
                    raise NotepadError(422, "The time must include a time zone")
                if final_due <= now:
                    raise NotepadError(422, "That time has already passed")
            elif final_kind is Kind.TASK:
                final_due = None
            level = p.sensitivity if _RANK[p.sensitivity] >= _RANK[classify_privacy(final_text)] else classify_privacy(final_text)
            edited = final_text != p.text or final_kind is not p.kind or (final_kind is Kind.REMINDER and final_due != p.due_at)
        else:  # accepting: a retry; the values stored at the first claim are the ones used
            final_kind, final_text, final_due, level, edited = p.final_kind, p.final_text, p.final_due_at, p.sensitivity, p.edited
        claim = await self.store.claim_accept(proposal_id, kind=final_kind, text=final_text, due_at=final_due, sensitivity=level, edited=edited, now=now)
        if claim.outcome == "done":
            return await self._result(claim.proposal)
        if claim.outcome == "in_progress":
            raise NotepadError(409, "This item is being saved; try again in a moment")
        if claim.outcome == "missing":
            raise NotepadError(404, "No such proposal")
        if claim.outcome != "claimed":
            raise NotepadError(409, "This item can no longer be accepted")
        return await self._finish(claim.proposal)

    async def _finish(self, p: Proposal) -> dict:
        """Create the record once, link it, write the receipt once, then close the proposal. Safe to run again after any interruption."""
        kind, text, due = p.final_kind, p.final_text, p.final_due_at
        record_kind: str | None = None
        record_id: str | None = None
        if kind is Kind.TASK:
            record_kind, record_id = "task", record_id_for(p.id)
            if await self.tasks.get_task(record_id) is None:
                try:
                    await self.tasks.add_task(text, sensitivity=p.sensitivity, project_scope=p.project_scope, record_id=record_id)
                except (psycopg.errors.UniqueViolation, ValueError):
                    pass  # a concurrent finisher created it first: same id, same record
        elif kind is Kind.REMINDER:
            record_kind, record_id = "reminder", record_id_for(p.id)
            if await self.planner.get_reminder(record_id) is None:
                try:
                    await self.planner.add_reminder(text, due, sensitivity=p.sensitivity, record_id=record_id)
                except (psycopg.errors.UniqueViolation, ValueError):
                    pass
        if record_id is not None:
            await self.store.add_provenance(Provenance(record_kind=record_kind, record_id=record_id, note_id=p.note_id, proposal_id=p.id, snapshot_hash=p.snapshot_hash, created_at=self.clock()))
            await self._receipt(p, record_kind, record_id, text, due)
        done = await self.store.finish_accept(p.id, record_kind, record_id, now=self.clock())
        if done is None:
            raise NotepadError(409, "This item can no longer be accepted")
        self._count("accepted")
        return await self._result(done)

    async def _receipt(self, p: Proposal, record_kind: str, record_id: str, text: str, due: datetime | None) -> None:
        """The existing task.created / reminder.created receipt, with an id derived from the proposal so a retry cannot write a second one. A failure never undoes the accept (ADR 0028)."""
        if record_kind == "task":
            fields = {"Task": text, "From": "reviewed note proposal"}
        else:
            zone_name = await self.timezone()
            from zoneinfo import ZoneInfo

            fields = {"Reminder": text, "When": f"{due.astimezone(ZoneInfo(zone_name)):%a %d %b at %I:%M %p}", "From": "reviewed note proposal"}
        receipt = ActionReceipt(id=str(uuid.uuid5(_RECEIPT_NAMESPACE, p.id)), action_type=f"{record_kind}.created", source_channel="web", object_type=record_kind, object_id=record_id,
                                fields=fields, notify=False)
        try:
            await self.planner.add_receipt(receipt)
        except psycopg.errors.UniqueViolation:
            return
        except Exception:
            log.exception("could not record the receipt for an accepted notepad proposal")

    async def _result(self, p: Proposal) -> dict:
        current = None
        note = await self.planner.get_note(p.note_id)
        if note is not None:
            current = content_hash(note.body)
        return {"proposal": p.view(current_hash=current), "record": {"kind": p.record_kind, "id": p.record_id} if p.record_id else None}

    async def dismiss(self, proposal_id: str) -> dict:
        decision = await self.store.dismiss(proposal_id, now=self.clock())
        if decision.outcome == "missing":
            raise NotepadError(404, "No such proposal")
        if decision.outcome == "closed":
            raise NotepadError(409, "This item was already decided")
        return await self._result(decision.proposal)

    async def note_deleted(self, note_id: str) -> None:
        with contextlib.suppress(Exception):
            await self.store.close_for_note(note_id, now=self.clock())
            await self.store.drop_links(note_id=note_id)

    async def reconcile(self) -> int:
        """Finish accepts a crash interrupted: take over each stale `accepting` proposal and run the same idempotent finish."""
        n = 0
        for proposal_id in await self.store.stale_accepting(self.clock()):
            with contextlib.suppress(NotepadError):
                await self.accept(proposal_id)
                n += 1
        return n

    def summary(self) -> dict[str, int]:
        return dict(self.counters)


async def run_loop(service: NotepadService, *, concurrency: int = 1, poll: float = POLL_SECONDS) -> None:
    """Bounded background runner: `concurrency` workers, each taking one job at a time, woken by an enqueue and otherwise polling. Worker 0 also finishes interrupted
    accepts. Never raises."""

    async def worker(index: int) -> None:
        while True:
            try:
                if index == 0:
                    await service.reconcile()
                if await service.process_next():
                    continue
                service.wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(service.wake.wait(), timeout=poll)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("notepad runner step failed")
                await asyncio.sleep(poll)

    async with asyncio.TaskGroup() as group:
        for index in range(max(1, concurrency)):
            group.create_task(worker(index))


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
