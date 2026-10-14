"""Real in-process hub in front of a REAL companion-core for the Phase 54 browser test. The meeting's recording is a real WAV in which each detected speaker is a distinct tone, so a browser
playing a sample really hears that speaker, and the diarization matches it. Nothing is mocked except the speech services (the meeting is seeded already transcribed and diarized).
Test fixture only; never a deployment.

    python e2e/speakers_hub_server.py PORT
"""

import asyncio
import importlib.util
import io
import math
import struct
import sys
import wave
from pathlib import Path

import httpx
import uvicorn

tests = Path(__file__).resolve().parents[3] / "services" / "reachy-hub" / "tests" / "test_web_client.py"
spec = importlib.util.spec_from_file_location("test_web_client", tests)
module = importlib.util.module_from_spec(spec)
sys.modules["test_web_client"] = module
spec.loader.exec_module(module)

from reachy_hub.companion_core_client import CompanionCoreClient  # noqa: E402
from reachy_hub.enrollment_store import InMemoryEnrollmentStore  # noqa: E402

RATE = 8000
# (start, end, tone Hz, speaker): A 440 Hz, B 880 Hz, C 1320 Hz. Speaker C barely speaks and gets no clean sample.
PLAN = [(0, 14, 440, "SPEAKER_00"), (14, 26, 880, "SPEAKER_01"), (26, 27.5, 1320, "SPEAKER_02"), (27.5, 45.5, 440, "SPEAKER_00"), (45.5, 59.5, 880, "SPEAKER_01")]
TEXT = "we should plan the release for the autumn quarter together with the vendor"


def wav() -> bytes:
    frames = bytearray()
    for start, end, hz, _ in PLAN:
        for n in range(int((end - start) * RATE)):
            frames += struct.pack("<h", int(9000 * math.sin(2 * math.pi * hz * n / RATE)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(bytes(frames))
    return buf.getvalue()


def build():
    core = module.create_core_app(
        calendar_store=module.InMemoryCalendarStore(), task_store=module.InMemoryTaskStore(), planner_store=module.InMemoryPlannerStore(), meeting_store=module.InMemoryMeetingStore(),
        run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(), rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(),
        confirmation_store=module.InMemoryConfirmationStore(), llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(),
        persona_store=module.InMemoryPersonaStore(), search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False)
    store = core.state.meeting_store

    async def seed():
        meeting = await store.create_meeting(title="Tone sync", audio=wav(), source_filename="tones.wav", content_type="audio/wav", participants=["Dana Lee"])
        store._touch(meeting, status="complete", duration_seconds=60.0,
                     transcript_segments=[{"start": s, "end": e, "text": TEXT} for s, e, _, _ in PLAN],
                     diarization_segments=[{"start": s, "end": e, "speaker": who} for s, e, _, who in PLAN],
                     aligned_segments=[{"start": s, "end": e, "text": TEXT, "speaker": who} for s, e, _, who in PLAN])

    asyncio.run(seed())
    client = module.make_client(companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
                                enrollment_store=InMemoryEnrollmentStore())
    client.cookies.clear()
    return client


async def serve(client, port: int):
    await uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning")).serve()


if __name__ == "__main__":
    asyncio.run(serve(build(), int(sys.argv[1])))
