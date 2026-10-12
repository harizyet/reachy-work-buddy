"""Phase 50 integrated-gate drill: the two scenarios worth running against a REAL document worker before activation (docs/verification/phase-50c-integration-2026-10-12.md).

  1. Identical bytes, two policies: document A (work-private, Basic) and B (sensitive, Standard) share one backend object. Reprocessing A must leave B valid; deleting A must leave B
     valid; deleting B finally removes the original and the worker's state.
  2. Restore: back up PostgreSQL and the source store, destroy the worker's derived state, the database and the source store, restore the first two, start a FRESH worker, and let the
     sync loop rebuild the documents from the restored originals.

The library service runs in this process with a real PostgreSQL (a throwaway container this script starts and removes) and a real source store in a temporary directory; only the worker is
external. Nothing here touches production data. For step 2 the worker's state must be wiped and the worker restarted: pass --reset-worker-cmd (a shell command that does that; run on this
machine) or, for a remote worker, do it by hand when prompted.

  uv run python tools/document_gate_drill.py --worker-url http://127.0.0.1:18700 --token ... --sample-dir <dir with scanned.pdf and sample.docx> --reset-worker-cmd '...'
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from companion_core.document_library.models import DocumentState, Priority
from companion_core.document_library.postgres_store import PostgresDocumentStore
from companion_core.document_library.service import DocumentService
from companion_core.document_library.source_store import SourceStore
from companion_core.document_library.worker_client import DocumentWorkerClient
from companion_core.migrations.__main__ import upgrade
from companion_core.secrets import Keyring
from companion_core.semantic.access import access_for_owner

from shared.models.response import Privacy

OWNER_SENSITIVE = access_for_owner("owner", channel_private=True, allow_sensitive=True)
READY = DocumentState.READY


def say(message: str) -> None:
    print(message, flush=True)


async def chunks(data: bytes):
    yield data


async def wait_state(service: DocumentService, document_id: str, want=(READY, DocumentState.FAILED), timeout=300.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await service.sync_once()
        document = await service.get(document_id)
        if document.state in want:
            return document
        await asyncio.sleep(1)
    raise SystemExit(f"timed out waiting for {document_id} ({document.state})")


def check(condition: bool, label: str) -> None:
    say(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


async def refused(awaitable, status: int) -> bool:
    try:
        await awaitable
    except Exception as exc:  # noqa: BLE001
        return getattr(exc, "status", None) == status
    return False


class Postgres:
    def __init__(self) -> None:
        self.name = "drill-pg-" + uuid.uuid4().hex[:8]
        self.port = 56000 + int(uuid.uuid4().int % 1000)
        subprocess.run(["docker", "run", "-d", "--name", self.name, "-e", "POSTGRES_PASSWORD=pw", "-p", f"127.0.0.1:{self.port}:5432", "pgvector/pgvector:pg16"], check=True, capture_output=True)
        for _ in range(60):
            if subprocess.run(["docker", "exec", self.name, "pg_isready", "-U", "postgres"], capture_output=True, check=False).returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)
        self.dsn = f"postgresql://postgres:pw@127.0.0.1:{self.port}/reachy"
        self.sql("CREATE DATABASE reachy")
        upgrade(self.dsn, Keyring("one", {"one": b"\x01" * 32}))

    def sql(self, statement: str, db: str = "postgres") -> None:
        subprocess.run(["docker", "exec", self.name, "psql", "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-c", statement], check=True, capture_output=True)

    def dump(self, path: Path) -> None:
        with path.open("wb") as out:
            subprocess.run(["docker", "exec", self.name, "pg_dump", "-U", "postgres", "-Fc", "reachy"], check=True, stdout=out)

    def restore(self, path: Path) -> None:
        self.sql("DROP DATABASE IF EXISTS reachy WITH (FORCE)")
        self.sql("CREATE DATABASE reachy")
        with path.open("rb") as handle:
            subprocess.run(["docker", "exec", "-i", self.name, "pg_restore", "-U", "postgres", "-d", "reachy", "--no-owner"], check=True, stdin=handle, capture_output=True)

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, check=False)


async def build(pg: Postgres, root: Path, args) -> tuple[DocumentService, PostgresDocumentStore]:
    store = await PostgresDocumentStore.connect(pg.dsn)
    worker = DocumentWorkerClient(args.worker_url, args.token, client=httpx.AsyncClient(base_url=args.worker_url, timeout=180))
    return DocumentService(store, SourceStore(root / "source"), worker), store


def reset_worker(args) -> None:
    """Wipe the worker's derived state and bring up a fresh one (blocking: run in a thread)."""
    if args.reset_worker_cmd:
        subprocess.run(args.reset_worker_cmd, shell=True, check=True)
    else:
        input("     wipe the worker's state (its volume) and restart it with a fresh MinerU, then press Enter: ")
    for _ in range(90):
        try:
            if httpx.get(args.worker_url + "/health", timeout=3).json().get("ok"):
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit("the restarted worker never became healthy")


async def scenario_duplicate_bytes(args, sample: bytes) -> None:
    say("\n== 1. identical bytes, two policies ==")
    pg, root = Postgres(), Path(tempfile.mkdtemp(prefix="drill-"))
    try:
        service, store = await build(pg, root, args)
        a = await service.upload("A.pdf", chunks(sample), title="A", sensitivity=Privacy.WORK_PRIVATE, priority=Priority.BACKGROUND)
        b = await service.upload("B.pdf", chunks(sample), title="B", sensitivity=Privacy.SENSITIVE, priority=Priority.INTERACTIVE)
        a, b = await wait_state(service, a.id), await wait_state(service, b.id)
        check(a.state is READY and b.state is READY and a.tier == "basic" and b.tier == "standard", f"A ready at {a.tier}, B ready at {b.tier}, one blob ({a.source_hash == b.source_hash})")
        check(len(list((root / "source" / "sha256").rglob(a.source_hash))) == 1, "one authoritative original for both")
        ceiling_a = access_for_owner("owner", channel_private=True)
        check(await refused(service.read(b.id, ceiling_a), 403), "B (sensitive) is refused at the work-private ceiling, A is not")
        check("retention" in (await service.read(a.id, ceiling_a, page_range="1")).content, "A readable at its tier")
        await service.reprocess(a.id)
        a = await wait_state(service, a.id)
        check(a.state is READY and "retention" in (await service.read(b.id, OWNER_SENSITIVE, page_range="1")).content, "after reprocessing A, B is still valid and readable")
        check(bool((await service.search(b.id, OWNER_SENSITIVE, "retention")).hits) and bool((await service.search(a.id, ceiling_a, "retention")).hits), "search works for both")
        await service.delete(a.id)
        check("retention" in (await service.read(b.id, OWNER_SENSITIVE, page_range="1")).content and (root / "source" / "sha256").exists(), "after deleting A, B is valid and the original remains")
        await service.delete(b.id)
        check(not list((root / "source" / "sha256").rglob(a.source_hash)) and await store.count_by_hash(a.source_hash) == 0, "after deleting B the original and the records are gone")
        for gone in (a.id, b.id):
            try:
                await service.worker.status(gone)
                check(False, f"worker still knows {gone}")
            except Exception as exc:  # noqa: BLE001
                check(getattr(exc, "status", None) == 404, f"worker no longer knows {gone[:8]}")
        await store.close()
        await service.worker.close()
    finally:
        pg.close()
        shutil.rmtree(root, ignore_errors=True)


async def scenario_restore(args, pdf: bytes, docx: bytes) -> None:
    say("\n== 2. restore: database + source store back, a fresh worker, documents rebuilt ==")
    pg, root = Postgres(), Path(tempfile.mkdtemp(prefix="drill-"))
    try:
        service, store = await build(pg, root, args)
        x = await service.upload("Report.pdf", chunks(pdf), title="Report", priority=Priority.NORMAL)
        y = await service.upload("Memo.docx", chunks(docx), title="Memo", sensitivity=Privacy.SENSITIVE)
        x, y = await wait_state(service, x.id), await wait_state(service, y.id)
        check(x.state is READY and y.state is READY, "two documents ready before the backup")
        before = {d.id: (d.title, d.sensitivity, d.source_hash) for d in await store.list()}
        dump = root / "reachy.dump"
        pg.dump(dump)
        shutil.copytree(root / "source", root / "source-backup")
        say("     backed up PostgreSQL and the source store")
        await store.close()
        await service.worker.close()
        # --- disaster: the database, the source store and the worker's state are all gone
        pg.sql("DROP DATABASE reachy WITH (FORCE)")
        shutil.rmtree(root / "source")
        await asyncio.to_thread(reset_worker, args)
        say("     database, source store and worker state destroyed; worker restarted fresh")
        # --- restore the two things that matter
        pg.restore(dump)
        shutil.copytree(root / "source-backup", root / "source")
        service, store = await build(pg, root, args)
        after = {d.id: (d.title, d.sensitivity, d.source_hash) for d in await store.list()}
        check(after == before, "restored catalogue matches (titles, classes, hashes)")
        check(all([(await service.sources.verify(h)) > 0 for _t, _s, h in after.values()]) is True, "restored originals pass their integrity check")
        try:
            await service.worker.status(x.id)
            check(False, "the fresh worker should not know the document")
        except Exception as exc:  # noqa: BLE001
            check(getattr(exc, "status", None) == 404, "the fresh worker knows nothing yet")
        check(await refused(service.read(x.id, OWNER_SENSITIVE), 409) and (await service.get(x.id)).state is DocumentState.UPLOADED, "a read finds the worker empty: a clean 409 and the document goes back to the loop")
        changed = await service.sync_once(include_ready=True)
        say(f"     reconcile pass changed {changed} document(s)")
        x, y = await wait_state(service, x.id), await wait_state(service, y.id)
        check(x.state is READY and y.state is READY, "both documents are READY again, rebuilt from the restored originals")
        check("retention" in (await service.read(x.id, OWNER_SENSITIVE, page_range="1")).content and bool((await service.search(y.id, OWNER_SENSITIVE, "two-factor")).hits), "content and search work again")
        for d in (x, y):
            await service.delete(d.id)
        check(await store.list() == [], "cleaned up")
        await store.close()
        await service.worker.close()
    finally:
        pg.close()
        shutil.rmtree(root, ignore_errors=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worker-url", required=True)
    parser.add_argument("--token", default=os.environ.get("DOCUMENT_WORKER_TOKEN", ""))
    parser.add_argument("--sample-dir", type=Path, required=True, help="a directory with scanned.pdf and sample.docx")
    parser.add_argument("--reset-worker-cmd", default="")
    parser.add_argument("--only", choices=("duplicate", "restore"))
    args = parser.parse_args()
    if not args.token:
        sys.exit("a worker token is required")
    pdf, docx = (args.sample_dir / "scanned.pdf").read_bytes(), (args.sample_dir / "sample.docx").read_bytes()
    if args.only != "restore":
        await scenario_duplicate_bytes(args, pdf)
    if args.only != "duplicate":
        await scenario_restore(args, pdf, docx)
    say("\ndrill passed")


if __name__ == "__main__":
    asyncio.run(main())
