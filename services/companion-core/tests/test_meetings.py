"""Phase 27.1 foundation (docs/phase-27.md): upload, track and recover a
meeting job across restart, plus the worker's real PREPROCESSING stage.
"""

import asyncio
import io
import wave

import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.store import (
    InMemoryMeetingStore,
    MeetingNotCancellableError,
)
from companion_core.meetings.worker import MeetingWorker, probe_wav_duration
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient


def _wav_bytes(*, seconds: float = 1.0, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def core_app(**kwargs):
    return create_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        meeting_store=kwargs.pop("meeting_store", InMemoryMeetingStore()),
        run_meeting_worker_task=kwargs.pop("run_meeting_worker_task", False),
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
        **kwargs,
    )


# --- store unit tests -------------------------------------------------


def test_in_memory_store_create_get_list():
    async def run():
        store = InMemoryMeetingStore()
        meeting = await store.create_meeting(
            title="Weekly sync", audio=b"raw", source_filename="rec.wav", content_type="audio/wav"
        )
        assert meeting.status == MeetingJobStatus.UPLOADED
        assert await store.get_meeting(meeting.id) == meeting
        assert await store.list_meetings() == [meeting]
        assert await store.load_audio(meeting.id) == b"raw"

    asyncio.run(run())


def test_claim_next_upload_is_oldest_and_transitions_status():
    async def run():
        store = InMemoryMeetingStore()
        first = await store.create_meeting(title="A", audio=b"1", source_filename="a.wav", content_type="audio/wav")
        second = await store.create_meeting(title="B", audio=b"2", source_filename="b.wav", content_type="audio/wav")

        claimed = await store.claim_next_upload()
        assert claimed.id == first.id
        assert claimed.status == MeetingJobStatus.PREPROCESSING
        # "A" is already claimed (PREPROCESSING, not UPLOADED), so the next
        # claim finds "B" instead of re-claiming it.
        claimed_again = await store.claim_next_upload()
        assert claimed_again.id == second.id
        # Nothing UPLOADED remains.
        assert await store.claim_next_upload() is None

    asyncio.run(run())


def test_requeue_orphaned_resets_stuck_preprocessing_job():
    async def run():
        store = InMemoryMeetingStore()
        meeting = await store.create_meeting(title="A", audio=b"1", source_filename="a.wav", content_type="audio/wav")
        await store.claim_next_upload()  # simulate a worker that claimed it and then crashed

        resumed = await store.requeue_orphaned()
        assert resumed == 1
        refreshed = await store.get_meeting(meeting.id)
        assert refreshed.status == MeetingJobStatus.UPLOADED

    asyncio.run(run())


def test_cancel_meeting_rejects_past_cancellable_stage():
    async def run():
        store = InMemoryMeetingStore()
        meeting = await store.create_meeting(title="A", audio=b"1", source_filename="a.wav", content_type="audio/wav")
        await store.mark_preprocessed(meeting.id, normalized_audio_path=None, duration_seconds=1.0)

        with pytest.raises(MeetingNotCancellableError):
            await store.cancel_meeting(meeting.id)

    asyncio.run(run())


# --- worker -------------------------------------------------------------


def test_probe_wav_duration_real_and_malformed():
    assert probe_wav_duration(_wav_bytes(seconds=2.0, rate=8000)) == pytest.approx(2.0)
    assert probe_wav_duration(b"not a wav file") is None


def test_worker_preprocesses_wav_and_leaves_job_at_transcribing():
    async def run():
        store = InMemoryMeetingStore()
        meeting = await store.create_meeting(
            title="A", audio=_wav_bytes(seconds=1.5), source_filename="a.wav", content_type="audio/wav"
        )

        worker = MeetingWorker(store)
        found = await worker.process_one()

        assert found is True
        refreshed = await store.get_meeting(meeting.id)
        assert refreshed.status == MeetingJobStatus.TRANSCRIBING
        assert refreshed.duration_seconds == pytest.approx(1.5)
        # No handler exists yet for TRANSCRIBING (27.2), so a second pass finds nothing workable.
        assert await worker.process_one() is False

    asyncio.run(run())


def test_worker_fails_job_on_empty_audio():
    async def run():
        store = InMemoryMeetingStore()
        meeting = await store.create_meeting(title="A", audio=b"", source_filename="a.wav", content_type="audio/wav")

        worker = MeetingWorker(store)
        await worker.process_one()

        refreshed = await store.get_meeting(meeting.id)
        assert refreshed.status == MeetingJobStatus.FAILED
        assert refreshed.error_detail

    asyncio.run(run())


def test_worker_run_forever_requeues_orphans_on_startup():
    async def run():
        store = InMemoryMeetingStore()
        meeting = await store.create_meeting(title="A", audio=b"1", source_filename="a.wav", content_type="audio/wav")
        await store.claim_next_upload()

        worker = MeetingWorker(store, poll_interval=0.01)
        task = asyncio.create_task(worker.run_forever())
        try:
            for _ in range(200):
                refreshed = await store.get_meeting(meeting.id)
                if refreshed.status == MeetingJobStatus.TRANSCRIBING:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("worker never processed the orphaned job")
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())


# --- routes ---------------------------------------------------------------


def test_upload_list_get_meeting_over_http():
    store = InMemoryMeetingStore()
    with TestClient(core_app(meeting_store=store)) as client:
        response = client.post(
            "/meetings",
            data={"title": "Weekly sync", "project_scope": "Reachy", "participants": "Hariz, Alice"},
            files={"audio": ("meeting.wav", _wav_bytes(), "audio/wav")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "Weekly sync"
        assert body["participants"] == ["Hariz", "Alice"]
        assert body["status"] == "uploaded"
        meeting_id = body["id"]

        listed = client.get("/meetings").json()
        assert [m["id"] for m in listed] == [meeting_id]

        fetched = client.get(f"/meetings/{meeting_id}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == meeting_id


def test_upload_rejects_unsupported_extension():
    with TestClient(core_app()) as client:
        response = client.post(
            "/meetings",
            data={"title": "Weekly sync"},
            files={"audio": ("meeting.exe", b"whatever", "application/octet-stream")},
        )
        assert response.status_code == 422


def test_upload_rejects_empty_file():
    with TestClient(core_app()) as client:
        response = client.post(
            "/meetings",
            data={"title": "Weekly sync"},
            files={"audio": ("meeting.wav", b"", "audio/wav")},
        )
        assert response.status_code == 422


def test_get_missing_meeting_is_404():
    with TestClient(core_app()) as client:
        assert client.get("/meetings/does-not-exist").status_code == 404


def test_cancel_meeting_then_reject_second_cancel():
    with TestClient(core_app()) as client:
        upload = client.post(
            "/meetings",
            data={"title": "Weekly sync"},
            files={"audio": ("meeting.wav", _wav_bytes(), "audio/wav")},
        )
        meeting_id = upload.json()["id"]

        cancelled = client.post(f"/meetings/{meeting_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        second = client.post(f"/meetings/{meeting_id}/cancel")
        assert second.status_code == 409


def test_meeting_survives_service_restart_with_same_backing_store():
    """The 27.1 exit criterion: upload, track, recover across restart. A
    fresh create_app against the same store stands in for a service
    restart against the same durable backend (see PostgresMeetingStore,
    where that backend is real Postgres + disk rather than memory)."""
    store = InMemoryMeetingStore()
    with TestClient(core_app(meeting_store=store)) as client:
        meeting_id = client.post(
            "/meetings",
            data={"title": "Weekly sync"},
            files={"audio": ("meeting.wav", _wav_bytes(), "audio/wav")},
        ).json()["id"]

    with TestClient(core_app(meeting_store=store)) as client:
        recovered = client.get(f"/meetings/{meeting_id}")
        assert recovered.status_code == 200
        assert recovered.json()["title"] == "Weekly sync"
