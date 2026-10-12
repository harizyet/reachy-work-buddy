"""Throwaway hub for the Android Documents and chat-picker device checks: a REAL in-process hub in front of a REAL companion-core, with the document library and the chat archive on a
disposable REAL PostgreSQL (migrated with core's own migrations) and a REAL document worker (MinerU). Only the sync loop (core's lifespan does not run in process) is played by a background task.

    DISPOSABLE_PG_URL=postgresql://postgres:iso@127.0.0.1:55432/postgres DOCUMENT_WORKER_URL=http://127.0.0.1:18700 DOCUMENT_WORKER_TOKEN=... \\
        [E2E_LLM_BASE_URL=http://127.0.0.1:8003/v1] python clients/android/e2e/android_hub_server.py PORT

Owner login `owner` / `correct-password`. Test fixture only; never a deployment. The emulator reaches it with `adb reverse tcp:PORT tcp:PORT`.
"""

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import uvicorn

os.environ["DOCUMENT_LIBRARY_ENABLED"] = "true"
tests = Path(__file__).resolve().parents[3] / "services" / "reachy-hub" / "tests" / "test_web_client.py"
spec = importlib.util.spec_from_file_location("test_web_client", tests)
module = importlib.util.module_from_spec(spec)
sys.modules["test_web_client"] = module
spec.loader.exec_module(module)

from companion_core.document_library.postgres_store import (
    PostgresDocumentStore,
)
from companion_core.document_library.source_store import SourceStore
from companion_core.document_library.worker_client import (
    DocumentWorkerClient,
)
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring
from reachy_hub.chat_store import PostgresChatStore
from reachy_hub.companion_core_client import CompanionCoreClient
from reachy_hub.enrollment_store import InMemoryEnrollmentStore


async def build():
    root = os.environ["DISPOSABLE_PG_URL"]
    name = "android_" + uuid4().hex[:12]
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    dsn = psycopg.conninfo.make_conninfo(root, dbname=name)
    upgrade(dsn, Keyring("one", {"one": b"\x01" * 32}))
    library = await PostgresDocumentStore.connect(dsn)
    chats = await PostgresChatStore.connect(dsn)
    worker = DocumentWorkerClient(os.environ["DOCUMENT_WORKER_URL"], os.environ["DOCUMENT_WORKER_TOKEN"],
                                  client=httpx.AsyncClient(base_url=os.environ["DOCUMENT_WORKER_URL"], timeout=300))
    core = module.create_core_app(
        calendar_store=module.InMemoryCalendarStore(), task_store=module.InMemoryTaskStore(), planner_store=module.InMemoryPlannerStore(), meeting_store=module.InMemoryMeetingStore(),
        run_meeting_worker_task=False, memory_store=module.InMemoryMemoryStore(), rag_store=module.InMemoryDocumentStore(), email_store=module.InMemoryEmailStore(),
        confirmation_store=module.InMemoryConfirmationStore(), llm_settings_store=module.InMemoryLLMSettingsStore(), llm_usage_store=module.InMemoryLLMUsageStore(),
        persona_store=module.InMemoryPersonaStore(), search_settings_store=module.InMemorySearchSettingsStore(), run_email_dispatch_task=False,
        document_store=library, document_sources=SourceStore(Path(tempfile.mkdtemp(prefix="docs-android-"))), document_worker=worker, run_document_sync=False)
    # make_client bootstraps its user with asyncio.run, which cannot run inside this loop, so it runs in a thread; the pools stay on this loop.
    client = await asyncio.to_thread(
        module.make_client, companion_core_client=CompanionCoreClient("http://core", transport=httpx.ASGITransport(app=core)), accounts_service_token="e2e-service",
        enrollment_store=InMemoryEnrollmentStore(), chat_store=chats,
    )
    client.cookies.clear()
    return client, core, name


async def main(port: int):
    client, core, name = await build()
    if os.environ.get("E2E_LLM_BASE_URL"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core), base_url="http://core") as direct:
            (await direct.put("/settings/llm", json={"local": {"base_url": os.environ["E2E_LLM_BASE_URL"], "model": os.environ.get("E2E_LLM_MODEL", "reachy-local")}})).raise_for_status()
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning"))

    async def sync():
        while True:
            try:
                await core.state.document_library.sync_once()
            except Exception as exc:  # noqa: BLE001 - a fixture loop must keep going
                print(f"sync: {exc!r}", flush=True)
            await asyncio.sleep(1)

    print(f"database {name}", flush=True)
    task = asyncio.create_task(sync())
    try:
        await server.serve()
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
