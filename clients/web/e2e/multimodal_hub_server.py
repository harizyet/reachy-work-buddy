"""Real in-process hub in front of a REAL companion-core app with the document library and multimodal meeting intelligence on, for the Phase 53 browser test and the UAT rehearsal.
Test fixture only; never a deployment. Everything lives in memory unless MM_DATABASE_URL names a DISPOSABLE PostgreSQL server (then restarts keep their runs).

    python e2e/multimodal_hub_server.py PORT

Environment (all optional): MM_WORKER_URL / MM_WORKER_TOKEN (a disposable document worker: the real reader; without it page text comes from a fixed fake reader under the real access rules),
MM_LLM_URL (an OpenAI-compatible chat endpoint: the real local model; without it a scripted model), MM_TRANSCRIPT (a JSON file of {"segments": [{start, end, text}]} to use as the meeting),
MM_DATABASE_URL, MM_DATA_DIR (document originals; default a temp dir), MM_STALL_SECONDS (hold every analysis model call this long, to rehearse a slow run).
"""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

os.environ["MEETING_MULTIMODAL_ENABLED"] = "true"
os.environ["DOCUMENT_LIBRARY_ENABLED"] = "true"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "companion-core" / "tests"))
spec = importlib.util.spec_from_file_location("test_web_client", ROOT / "services" / "reachy-hub" / "tests" / "test_web_client.py")
module = importlib.util.module_from_spec(spec)
sys.modules["test_web_client"] = module
spec.loader.exec_module(module)

from companion_core.document_library.source_store import SourceStore  # noqa: E402
from companion_core.document_library.store import InMemoryDocumentStore as LibraryStore  # noqa: E402
from companion_core.document_library.worker_client import DocumentWorkerClient  # noqa: E402
from companion_core.meeting_multimodal.store import InMemoryMultimodalStore  # noqa: E402
from companion_core.meetings.models import Meeting, MeetingJobStatus  # noqa: E402
from reachy_hub.companion_core_client import CompanionCoreClient  # noqa: E402
from reachy_hub.enrollment_store import InMemoryEnrollmentStore  # noqa: E402

MEETING_ID = "uat-meeting"
SEEDED = [
    "Now the architecture: inference runs on the Jetson edge node,", "and the control plane is kept separate from inference on purpose.", "That separation is the key point of the edge architecture for us.",
    "Telemetry ingestion goes through Kafka streaming,", "we keep seven days of retention with compaction on the topics,", "so the pipeline can replay events after an outage.",
    "How was everyone's weekend, did you get out of the city at all?", "I went hiking near the lake, the weather was lovely for it.", "Anyway, shall we get started with the agenda for today?",
]
STALL = float(os.environ.get("MM_STALL_SECONDS", "0"))


def meeting() -> Meeting:
    if os.environ.get("MM_TRANSCRIPT"):
        segments = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in json.load(open(os.environ["MM_TRANSCRIPT"]))["segments"]]
    else:
        segments, clock = [], 0.0
        for n, text in enumerate(SEEDED):
            segments.append({"start": clock, "end": clock + 8.0, "text": text})
            clock += 9.0 + (12.0 if n % 3 == 2 else 0.0)
    return Meeting(id=MEETING_ID, title="Architecture review", source_filename="a.wav", content_type="audio/wav", audio_path="/none", started_at=datetime.now(UTC) - timedelta(days=1),
                   duration_seconds=segments[-1]["end"], status=MeetingJobStatus.COMPLETE, transcript_segments=segments,
                   aligned_segments=[{**s, "speaker": "speaker_0" if i % 2 == 0 else "speaker_1"} for i, s in enumerate(segments)], diarization_segments=[])


async def provider():
    if os.environ.get("MM_LLM_URL"):
        client = httpx.AsyncClient(timeout=600)

        async def ask(messages, max_tokens):
            if STALL and messages[0]["content"].startswith("You read part of ONE meeting transcript together"):
                await asyncio.sleep(STALL)
            r = await client.post(os.environ["MM_LLM_URL"], json={"model": "reachy-local", "messages": messages, "max_tokens": max_tokens, "temperature": 0.0})
            r.raise_for_status()
            reply = r.json()["choices"][0]["message"]["content"]
            if os.environ.get("MM_LOG_RAW"):  # rehearsal only: the raw model reply, to see why a reply was unusable (this fixture holds disposable data)
                print("RAW", messages[0]["content"][:40].replace("\n", " "), "=>", reply[:1500].replace("\n", "\\n"), flush=True)
            return reply

        return ask, "reachy-local"
    from mm_fixtures import Model

    model = Model([("jetson edge node", None, "Edge Architecture"), ("kafka streaming", None, "Telemetry Pipeline")])

    async def ask(messages, max_tokens):
        if STALL:
            await asyncio.sleep(STALL)
        return await (await model.provider())[0](messages, max_tokens)

    return ask, "scripted-7b"


async def main(port: int):
    dsn = os.environ.get("MM_DATABASE_URL")
    if dsn:
        from companion_core.document_library.postgres_store import PostgresDocumentStore as PgLibrary
        from companion_core.meeting_multimodal.postgres_store import PostgresMultimodalStore
        from companion_core.migrations.__main__ import upgrade
        from companion_core.secrets import Keyring

        await asyncio.to_thread(upgrade, dsn, Keyring("one", {"one": b"\x01" * 32}))
        mm_store, library = await PostgresMultimodalStore.connect(dsn), await PgLibrary.connect(dsn)
    else:
        mm_store, library = InMemoryMultimodalStore(), LibraryStore()
    data = Path(os.environ.get("MM_DATA_DIR") or tempfile.mkdtemp())
    worker = DocumentWorkerClient(os.environ["MM_WORKER_URL"], os.environ.get("MM_WORKER_TOKEN", ""), timeout=300) if os.environ.get("MM_WORKER_URL") else None

    def build():
        core = module.create_core_app(
            calendar_store=module.InMemoryCalendarStore(), task_store=module.InMemoryTaskStore(), planner_store=module.InMemoryPlannerStore(), meeting_store=module.InMemoryMeetingStore(),
            run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(), rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(),
            confirmation_store=module.InMemoryConfirmationStore(), llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(),
            persona_store=module.InMemoryPersonaStore(), search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False,
            document_store=library, document_sources=SourceStore(data / "source"), document_worker=worker, run_document_sync=False,
            meeting_multimodal_store=mm_store, meeting_multimodal_provider=provider, run_multimodal_runner=False)
        core.state.meeting_store._meetings[MEETING_ID] = meeting()
        client = module.make_client(companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
                                    enrollment_store=InMemoryEnrollmentStore())
        client.cookies.clear()
        return client, core

    hub, core = await asyncio.to_thread(build)
    lib = core.state.document_library
    if worker is None:  # the fixed fake reader, still under the real access and deletion rules
        from mm_fixtures import DECK_A

        async def read(document_id, access, *, page_range=None, after=None, limit=8000):
            from shared.models.document_library import DocumentContentOut

            document = await lib.require_usable(document_id)
            lib.authorize(document, access)
            n = int(page_range)
            return DocumentContentOut(document_id=document.id, title=document.title, source_hash=document.source_hash, evidence_type="derived_extraction", tier="basic", content=f"<!-- page {n} of 6 -->\n{DECK_A[1][n - 1]}")

        lib.read = read  # type: ignore[method-assign]
    server = uvicorn.Server(uvicorn.Config(hub.app, host="127.0.0.1", port=port, log_level="warning"))
    service = core.state.meeting_multimodal_service
    await service.requeue_interrupted()  # a restart: runs the dead process left processing are queued again at once

    async def runner():
        while True:
            try:
                if worker is not None:
                    await lib.sync_once()
                if not await service.process_next():
                    await asyncio.sleep(0.5)
            except Exception as exc:  # noqa: BLE001 - a fixture runner must keep going
                print("runner", type(exc).__name__, exc, flush=True)
                await asyncio.sleep(0.5)

    task = asyncio.create_task(runner())
    try:
        await server.serve()
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
