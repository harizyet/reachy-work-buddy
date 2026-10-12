"""Real in-process hub in front of a REAL companion-core app with meeting analysis on, for the Phase 31 browser test. The only stand-in is the local model: a scripted provider that answers
with what a 7B might say about the seeded meeting, including a fabricated quote and a decision that is only a suggestion, which the deterministic validator must drop or label. A background
task plays the runner (core's lifespan is not run in process). Test fixture only; never a deployment.

    python e2e/analysis_hub_server.py PORT [off]

With `off` the same hub and core run with MEETING_ANALYSIS_ENABLED false (as deployed on 2026-10-12): the Meetings interface must work exactly as before and show no Analysis tab.
"""

import asyncio
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

ANALYSIS_ON = not (len(sys.argv) > 2 and sys.argv[2] == "off")
os.environ["MEETING_ANALYSIS_ENABLED"] = "true" if ANALYSIS_ON else "false"
tests = Path(__file__).resolve().parents[3] / "services" / "reachy-hub" / "tests" / "test_web_client.py"
spec = importlib.util.spec_from_file_location("test_web_client", tests)
module = importlib.util.module_from_spec(spec)
sys.modules["test_web_client"] = module
spec.loader.exec_module(module)

from companion_core.meeting_analysis.store import InMemoryMeetingAnalysisStore  # noqa: E402
from companion_core.meetings.models import Meeting, MeetingJobStatus  # noqa: E402
from reachy_hub.companion_core_client import CompanionCoreClient  # noqa: E402
from reachy_hub.enrollment_store import InMemoryEnrollmentStore  # noqa: E402

# Speech-to-text cuts sentences into fragments: the third and fourth segments are one sentence.
TEXTS = [
    "Let's settle the migration date first.",
    "Agreed, we will migrate the cluster in the first week of November.",
    "Alice will contact the vendor",
    "about compatibility by next Friday.",
    "We could maybe look at a second region at some point.",
    "Nobody knows who owns the backup budget yet?",
]
MODEL_ITEMS = [
    {"type": "decision", "text": "Migrate the cluster in the first week of November", "evidence": [{"segment": 1, "quote": "we will migrate the cluster in the first week of November"}]},
    {"type": "action", "text": "Contact the vendor about compatibility", "evidence": [{"segment": 2, "quote": "Alice will contact the vendor about compatibility by next Friday"}], "assignee": "Alice", "stated_time": "next Friday"},
    {"type": "decision", "text": "Add a second region", "evidence": [{"segment": 4, "quote": "We could maybe look at a second region at some point"}]},
    {"type": "open_question", "text": "Who owns the backup budget", "evidence": [{"segment": 5, "quote": "Nobody knows who owns the backup budget yet"}]},
    {"type": "decision", "text": "Buy new servers", "evidence": [{"segment": 3, "quote": "we agreed to buy new servers"}]},
]


async def provider():
    async def ask(messages, max_tokens):
        return json.dumps({"items": MODEL_ITEMS})

    return ask, "scripted-7b"


def build():
    core = module.create_core_app(
        calendar_store=module.InMemoryCalendarStore(), task_store=module.InMemoryTaskStore(), planner_store=module.InMemoryPlannerStore(), meeting_store=module.InMemoryMeetingStore(),
        run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(), rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(),
        confirmation_store=module.InMemoryConfirmationStore(), llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(),
        persona_store=module.InMemoryPersonaStore(), search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        meeting_analysis_store=InMemoryMeetingAnalysisStore() if ANALYSIS_ON else None, meeting_analysis_provider=provider, run_meeting_analysis_runner=False)
    segments = [{"start": 10.0 * i, "end": 10.0 * i + 8, "text": t} for i, t in enumerate(TEXTS)]
    meeting = Meeting(
        title="Cluster sync", source_filename="a.wav", content_type="audio/wav", audio_path="/none", started_at=datetime.now(UTC) - timedelta(days=1), duration_seconds=60.0,
        status=MeetingJobStatus.COMPLETE, transcript_segments=segments,
        aligned_segments=[{**s, "speaker": "speaker_0" if i % 2 == 0 else "speaker_1"} for i, s in enumerate(segments)], diarization_segments=[])
    core.state.meeting_store._meetings[meeting.id] = meeting
    client = module.make_client(companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
                                enrollment_store=InMemoryEnrollmentStore())
    client.cookies.clear()
    return client, core


async def serve(client, core, port: int):
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning"))

    async def runner():
        while True:
            try:
                if core.state.meeting_analysis_service is None or not await core.state.meeting_analysis_service.process_next():
                    await asyncio.sleep(0.2)
            except Exception:  # noqa: BLE001 - a fixture runner must keep going
                await asyncio.sleep(0.2)

    task = asyncio.create_task(runner())
    try:
        await server.serve()
    finally:
        task.cancel()


if __name__ == "__main__":
    hub, core_app = build()
    asyncio.run(serve(hub, core_app, int(sys.argv[1])))
