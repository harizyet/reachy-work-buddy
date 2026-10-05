"""End-to-end meeting pipeline check with a real recorded meeting.

Opt-in: set MEETING_REAL_AUDIO to a recording (any supported extension) and
point TRANSCRIPTION_URL / DIARIZATION_URL at running sidecars. Real here: the
audio, the hub multipart upload chain, core's routes and MeetingWorker, the
HTTP speech clients and both inference sidecars. In-memory: the meeting store.
The pipeline currently ends at ALIGNING (docs/phase-27.md), so that is the
terminal state asserted. Only counts and timings are printed, never transcript
text, because the recording is private.
"""

import asyncio
import mimetypes
import os
import time
from pathlib import Path

import httpx
import pytest
from companion_core.app import create_app as create_core_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.speech_clients import (
    HTTPDiarizationClient,
    HTTPTranscriptionClient,
)
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.meetings.worker import MeetingWorker
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from fastapi.testclient import TestClient
from reachy_embodiment.app import create_app as create_embodiment_app
from reachy_embodiment.robot import SimulatedRobotBackend
from reachy_hub.app import create_app
from reachy_hub.audit_log import InMemoryAuditLog
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.embodiment_client import EmbodimentClient
from reachy_hub.notification_queue import InMemoryNotificationQueue
from reachy_hub.robot_registry import InMemoryRobotRegistry
from reachy_hub.session_store import InMemorySessionStore
from reachy_hub.user_store import InMemoryUserStore

CSRF = {"X-Reachy-CSRF": "1"}

AUDIO = os.environ.get("MEETING_REAL_AUDIO")
TIMEOUT_SECONDS = float(os.environ.get("MEETING_REAL_TIMEOUT_SECONDS", "3600"))

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not AUDIO or not Path(AUDIO).is_file(),
        reason="set MEETING_REAL_AUDIO to a real meeting recording (plus TRANSCRIPTION_URL and DIARIZATION_URL)",
    ),
]


def _hub_client(store: InMemoryMeetingStore) -> TestClient:
    core = create_core_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        planner_store=InMemoryPlannerStore(),
        meeting_store=store,
        run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
    )
    embodiment = create_embodiment_app(SimulatedRobotBackend(), run_presence_loop=False)
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "correct-password"))
    return TestClient(
        create_app(
            user_store=users,
            registry=InMemoryRobotRegistry(),
            session_store=InMemorySessionStore(),
            audit_log=InMemoryAuditLog(),
            notification_queue=InMemoryNotificationQueue(),
            run_heartbeat_task=False,
            run_telegram_poll_task=False,
            session_secret_key="test-session-secret",
            remote_ui_token="test-token",
            companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)),
            client_factory=lambda url: EmbodimentClient(url, transport=httpx.ASGITransport(app=embodiment)),
        )
    )


def test_real_meeting_recording_reaches_aligning(capsys):
    path = Path(AUDIO)
    store = InMemoryMeetingStore()
    client = _hub_client(store)
    client.post("/auth/login", json={"username": "owner", "password": "correct-password"}, headers=CSRF)

    content_type = mimetypes.guess_type(path.name)[0] or "audio/mp4"
    with path.open("rb") as audio:
        uploaded = client.post(
            "/meetings",
            data={"title": "Real meeting end-to-end"},
            files={"audio": (path.name, audio, content_type)},
            headers=CSRF,
        )
    assert uploaded.status_code == 200, uploaded.text
    meeting_id = uploaded.json()["id"]

    async def drive() -> float:
        transcription = HTTPTranscriptionClient()
        diarization = HTTPDiarizationClient()
        worker = MeetingWorker(store, transcription_client=transcription, diarization_client=diarization)
        started = time.monotonic()
        try:
            while time.monotonic() - started < TIMEOUT_SECONDS:
                meeting = await store.get_meeting(meeting_id)
                if meeting.status in (MeetingJobStatus.ALIGNING, MeetingJobStatus.FAILED):
                    break
                if not await worker.process_one():
                    await asyncio.sleep(2)
        finally:
            await transcription.aclose()
            await diarization.aclose()
        return time.monotonic() - started

    elapsed = asyncio.run(drive())
    shown = client.get(f"/meetings/{meeting_id}").json()
    assert shown["status"] == "aligning", shown.get("error_detail") or shown["status"]

    meeting = asyncio.run(store.get_meeting(meeting_id))
    transcript, turns = meeting.transcript_segments, meeting.diarization_segments
    assert transcript and turns

    for segment in transcript:
        assert segment["text"].strip()
        assert 0 <= segment["start"] <= segment["end"]
    starts = [s["start"] for s in transcript]
    assert starts == sorted(starts)

    for turn in turns:
        assert turn["speaker"]
        assert 0 <= turn["start"] <= turn["end"]

    speech_end = max(s["end"] for s in transcript)
    turn_end = max(t["end"] for t in turns)
    # Both models heard the same recording, so their timelines must agree.
    assert abs(speech_end - turn_end) <= max(30.0, 0.1 * speech_end)

    speakers = sorted({t["speaker"] for t in turns})
    words = sum(len(s["text"].split()) for s in transcript)
    with capsys.disabled():
        print(
            f"\nreal meeting: audio_end={turn_end:.0f}s wall={elapsed:.0f}s "
            f"rtf={elapsed / max(turn_end, 1):.2f} transcript_segments={len(transcript)} "
            f"words={words} diarization_turns={len(turns)} speakers={len(speakers)}"
        )
