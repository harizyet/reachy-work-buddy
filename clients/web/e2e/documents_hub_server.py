"""Real in-process hub in front of a REAL companion-core with the document library on and a REAL document worker (MinerU) for the Phase 50 inspector browser check. Nothing is scripted
except that the sync loop (core's lifespan does not run in process) is played by a background task. Needs a running worker:

    DOCUMENT_WORKER_URL=http://127.0.0.1:18700 DOCUMENT_WORKER_TOKEN=... [E2E_LLM_BASE_URL=http://127.0.0.1:8003/v1] python e2e/documents_hub_server.py PORT

Owner login `owner` / `correct-password`. Test fixture only; never a deployment; it needs a MinerU worker, so it is not part of the default Playwright suite.
"""

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn

os.environ["DOCUMENT_LIBRARY_ENABLED"] = "true"
tests = Path(__file__).resolve().parents[3] / "services" / "reachy-hub" / "tests" / "test_web_client.py"
spec = importlib.util.spec_from_file_location("test_web_client", tests)
module = importlib.util.module_from_spec(spec)
sys.modules["test_web_client"] = module
spec.loader.exec_module(module)

from companion_core.document_library.source_store import SourceStore  # noqa: E402
from companion_core.document_library.store import InMemoryDocumentStore as InMemoryLibraryStore  # noqa: E402
from companion_core.document_library.worker_client import DocumentWorkerClient  # noqa: E402
from reachy_hub.companion_core_client import CompanionCoreClient  # noqa: E402
from reachy_hub.enrollment_store import InMemoryEnrollmentStore  # noqa: E402


def build():
    worker = DocumentWorkerClient(os.environ["DOCUMENT_WORKER_URL"], os.environ["DOCUMENT_WORKER_TOKEN"], client=httpx.AsyncClient(base_url=os.environ["DOCUMENT_WORKER_URL"], timeout=300))
    core = module.create_core_app(
        calendar_store=module.InMemoryCalendarStore(), task_store=module.InMemoryTaskStore(), planner_store=module.InMemoryPlannerStore(), meeting_store=module.InMemoryMeetingStore(),
        run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(), rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(),
        confirmation_store=module.InMemoryConfirmationStore(), llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(),
        persona_store=module.InMemoryPersonaStore(), search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        document_store=InMemoryLibraryStore(), document_sources=SourceStore(Path(tempfile.mkdtemp(prefix="docs-e2e-"))), document_worker=worker, run_document_sync=False)
    client = module.make_client(companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
                                enrollment_store=InMemoryEnrollmentStore())
    client.cookies.clear()
    return client, core


async def serve(client, core, port: int):
    if os.environ.get("E2E_LLM_BASE_URL"):  # a real local model for the chat checks (the fixture core is otherwise unconfigured)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core), base_url="http://core") as direct:
            reply = await direct.put("/settings/llm", json={"local": {"base_url": os.environ["E2E_LLM_BASE_URL"], "model": os.environ.get("E2E_LLM_MODEL", "reachy-local")}})
            reply.raise_for_status()
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning"))

    async def sync():
        while True:
            try:
                await core.state.document_library.sync_once()
            except Exception:  # noqa: BLE001 - a fixture loop must keep going
                pass
            await asyncio.sleep(1)

    task = asyncio.create_task(sync())
    try:
        await server.serve()
    finally:
        task.cancel()


if __name__ == "__main__":
    hub, core_app = build()
    asyncio.run(serve(hub, core_app, int(sys.argv[1])))
