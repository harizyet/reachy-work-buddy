"""What does migration 027 cost? (Phase 44B deployment gate.)

On a disposable Postgres with pgvector it builds a synthetic database at revision 026, times the same write workload before and after the
migration (so the difference is the triggers), times the migration itself, then builds the index with the real embedder and reports
storage growth, indexing time, CPU and peak memory.

    DATABASE_MIGRATION_TEST_URL=postgresql://... python index_overhead.py [--scale 2000] [--meetings 40]

Never point it at production: it creates and drops its own databases on the server it is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import resource
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Json

sys.path.insert(0, str(Path(__file__).resolve().parent))

WORDS = ["queue", "retry", "model", "falcon", "harbor", "lantern", "deploy", "rollback", "budget", "security", "review", "release", "platform", "latency", "benchmark", "meeting", "notes", "summary", "owner", "schedule", "incident", "credential", "audit"]


def sentence(rng: random.Random, n: int = 14) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n))


def seed(conn, scale: int, meetings: int, rng: random.Random) -> None:
    now = datetime.now(UTC)
    zeros = "[" + ",".join(["0"] * 384) + "]"
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO notes (id, title, body, created_at, updated_at) VALUES (%s,%s,%s,%s,%s)",
                        [(f"n{i}", sentence(rng, 4), sentence(rng, 40), now, now) for i in range(scale)])
        cur.executemany("INSERT INTO tasks (id, text, status, created_at) VALUES (%s,%s,'open',%s)",
                        [(f"t{i}", sentence(rng, 8), now) for i in range(scale)])
        cur.executemany("INSERT INTO memories (id, type, content, source, confidence, sensitivity, created_at) VALUES (%s,'working',%s,'seed',1.0,'work-private',%s)",
                        [(f"m{i}", sentence(rng, 20), now) for i in range(scale)])
        cur.executemany(f"INSERT INTO document_chunks (id, document_id, document_title, section, content, source, chunk_index, created_at, embedding) "
                        f"VALUES (%s,%s,'Doc',NULL,%s,'seed',%s,%s,'{zeros}')",
                        [(f"c{i}", f"d{i // 5}", sentence(rng, 60), i % 5, now) for i in range(scale)])
        for k in range(meetings):
            segs = [{"start": float(i * 5), "end": float(i * 5 + 4), "text": sentence(rng, 12)} for i in range(140)]
            diar = [{"start": s["start"], "end": s["end"], "speaker": f"SPEAKER_0{i % 3}"} for i, s in enumerate(segs)]
            cur.execute("INSERT INTO meetings (id, title, source_filename, content_type, audio_path, status, transcript_segments, diarization_segments) "
                        "VALUES (%s,%s,'a','b','c','aligning',%s,%s)", (f"mt{k}", f"Meeting {k}", Json(segs), Json(diar)))
    conn.commit()


def write_workload(dsn: str, n: int, tag: str) -> dict:
    """Autocommit inserts, updates and deletes through the same SQL the stores use; returns per-operation latency in microseconds."""
    out: dict[str, list[float]] = {}
    now = datetime.now(UTC)
    with psycopg.connect(dsn, autocommit=True) as conn:
        def timed(name, query, params):
            t = time.perf_counter()
            conn.execute(query, params)
            out.setdefault(name, []).append((time.perf_counter() - t) * 1e6)
        for i in range(n):
            timed("note insert", "INSERT INTO notes (id, title, body, created_at, updated_at) VALUES (%s,'t','body',%s,%s)", (f"w{tag}{i}", now, now))
            timed("task insert", "INSERT INTO tasks (id, text, status, created_at) VALUES (%s,'do it','open',%s)", (f"w{tag}{i}", now))
            timed("memory insert", "INSERT INTO memories (id, type, content, source, confidence, sensitivity, created_at) VALUES (%s,'working','a fact','s',1.0,'work-private',%s)", (f"w{tag}{i}", now))
        for i in range(n):
            timed("note update", "UPDATE notes SET body = 'edited body' WHERE id = %s", (f"w{tag}{i}",))
            timed("memory forget", "UPDATE memories SET forgotten_at = %s WHERE id = %s", (now, f"w{tag}{i}"))
            timed("memory read stamp", "UPDATE memories SET last_accessed = %s WHERE id = %s", (now, f"m{i}"))
            timed("meeting correction", "UPDATE meetings SET transcript_corrections = jsonb_build_object('3', 'fixed') WHERE id = %s", (f"mt{i % 1}",))
        for i in range(n):
            timed("note delete", "DELETE FROM notes WHERE id = %s", (f"w{tag}{i}",))
            timed("task delete", "DELETE FROM tasks WHERE id = %s", (f"w{tag}{i}",))
    return {k: {"mean_us": round(statistics.mean(v), 1), "p95_us": round(sorted(v)[int(len(v) * 0.95) - 1], 1), "n": len(v)} for k, v in out.items()}


def sizes(dsn: str) -> dict:
    with psycopg.connect(dsn) as conn:
        def one(q):
            return conn.execute(q).fetchone()[0]
        return {
            "knowledge_items_total_bytes": one("SELECT coalesce(pg_total_relation_size('knowledge_items'), 0)"),
            "knowledge_items_table_bytes": one("SELECT coalesce(pg_relation_size('knowledge_items'), 0)"),
            "knowledge_items_indexes_bytes": one("SELECT coalesce(pg_indexes_size('knowledge_items'), 0)"),
            "knowledge_outbox_total_bytes": one("SELECT coalesce(pg_total_relation_size('knowledge_outbox'), 0)"),
            "rows": one("SELECT count(*) FROM knowledge_items"),
            "sources_total_bytes": one("SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                      "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname IN ('notes','tasks','memories','document_chunks','meetings','reminders')"),
        }


async def build_index(dsn: str) -> dict:
    import torch
    from companion_core.knowledge.index import PostgresKnowledgeIndex
    from companion_core.knowledge.outbox import PostgresOutbox
    from companion_core.knowledge.sources import build_adapters
    from companion_core.knowledge.worker import IndexingWorker
    from companion_core.meetings.postgres_store import PostgresMeetingStore
    from companion_core.memory.postgres_store import PostgresMemoryStore
    from companion_core.planner.postgres_store import PostgresPlannerStore
    from companion_core.rag import embeddings
    from companion_core.rag.postgres_store import PostgresDocumentStore
    from companion_core.tasks.postgres_store import PostgresTaskStore

    torch.set_num_threads(int(os.environ.get("KNOWLEDGE_EMBED_THREADS", "2")))
    embeddings.embed(["warm up"])
    memory, planner, tasks = await PostgresMemoryStore.connect(dsn), await PostgresPlannerStore.connect(dsn), await PostgresTaskStore.connect(dsn)
    documents, meetings = await PostgresDocumentStore.connect(dsn), await PostgresMeetingStore.connect(dsn, audio_dir="/tmp/overhead-audio")
    index, outbox = await PostgresKnowledgeIndex.connect(dsn), await PostgresOutbox.connect(dsn)
    worker = IndexingWorker(adapters=build_adapters(memory=memory, documents=documents, meetings=meetings, planner=planner, tasks=tasks),
                            index=index, outbox=outbox, embed_fn=embeddings.embed, embedding_model=embeddings._MODEL_NAME)
    cpu0, t0 = time.process_time(), time.perf_counter()
    result = await worker.drain(max_rounds=100000)
    wall, cpu = time.perf_counter() - t0, time.process_time() - cpu0
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    for part in (memory, planner, tasks, documents, meetings, index, outbox):
        await part.close()
    return {"sources_synced": result.processed, "rows_written": result.upserted, "failed": result.failed, "wall_seconds": round(wall, 1),
            "cpu_seconds": round(cpu, 1), "rows_per_second": round(result.upserted / wall, 1), "peak_rss_mb": round(rss_mb)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", type=int, default=2000)
    parser.add_argument("--meetings", type=int, default=40)
    parser.add_argument("--writes", type=int, default=500)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--no-index", action="store_true", help="skip the (slow) real-embedder indexing and storage measurement")
    args = parser.parse_args()
    root = os.environ["DATABASE_MIGRATION_TEST_URL"]
    name = "overhead_" + uuid4().hex[:8]
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(root, dbname=name)
    try:
        from alembic import command
        from alembic.config import Config
        from companion_core.migrations import __main__ as migrations
        from companion_core.migrations.__main__ import upgrade
        from companion_core.secrets import Keyring
        from sqlalchemy import create_engine

        keys = Keyring("one", {"one": b"\x01" * 32})
        engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), hide_parameters=True)
        with engine.begin() as conn:
            config = Config()
            config.set_main_option("script_location", str(Path(migrations.__file__).parent))
            config.attributes.update(connection=conn, keyring=keys, adopt_legacy=False)
            command.upgrade(config, "026_source_sensitivity")
        engine.dispose()
        rng = random.Random(44)
        with psycopg.connect(dsn) as conn:
            seed(conn, args.scale, args.meetings, rng)
        t = time.perf_counter()
        upgrade(dsn, keys)
        migration_seconds = time.perf_counter() - t
        with psycopg.connect(dsn) as conn:
            queued = conn.execute("SELECT count(*) FROM knowledge_outbox").fetchone()[0]
            conn.execute("DELETE FROM knowledge_outbox")  # measure steady-state writes, not a pre-queued backlog
            conn.commit()
        # The same workload with the triggers disabled and enabled, alternating, on identical data: the difference is the triggers.
        # Each operation is its own transaction (as the application does it) so commit latency, which is noisy on shared storage, is
        # in both columns; the medians over several rounds remove most of that noise.
        tables = {"notes": "knowledge_notes", "tasks": "knowledge_tasks", "memories": "knowledge_memories", "meetings": "knowledge_meetings"}
        rounds: dict[str, dict[str, list[float]]] = {"off": {}, "on": {}}
        for round_no in range(args.rounds):
            order = ("off", "on") if round_no % 2 == 0 else ("on", "off")
            for state in order:
                with psycopg.connect(dsn, autocommit=True) as conn:
                    for table, trigger in tables.items():
                        conn.execute(f"ALTER TABLE {table} {'DISABLE' if state == 'off' else 'ENABLE'} TRIGGER {trigger}")
                result = write_workload(dsn, args.writes, f"{state}{round_no}")
                for op, stats in result.items():
                    rounds[state].setdefault(op, []).append(stats["mean_us"])
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute("DELETE FROM knowledge_outbox")
        for table, trigger in tables.items():
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
        overhead = {
            op: {"without_triggers_median_us": round(statistics.median(rounds["off"][op]), 1),
                 "with_triggers_median_us": round(statistics.median(rounds["on"][op]), 1),
                 "added_us": round(statistics.median(rounds["on"][op]) - statistics.median(rounds["off"][op]), 1),
                 "rounds": args.rounds}
            for op in rounds["on"]
        }
        with psycopg.connect(dsn) as conn:
            conn.execute("INSERT INTO knowledge_outbox (source_type, source_id) SELECT 'note', id FROM notes UNION ALL SELECT 'task', id FROM tasks "
                         "UNION ALL SELECT 'memory', id FROM memories UNION ALL SELECT DISTINCT 'document', document_id FROM document_chunks "
                         "UNION ALL SELECT 'meeting', id FROM meetings ON CONFLICT DO NOTHING")
            conn.commit()
        sources = sizes(dsn)["sources_total_bytes"]
        indexing = {} if args.no_index else asyncio.run(build_index(dsn))
        grown = sizes(dsn)
        print(json.dumps({
            "scale": {"notes": args.scale, "tasks": args.scale, "memories": args.scale, "document_chunks": args.scale, "meetings": args.meetings, "segments_per_meeting": 140},
            "migration_027": {"seconds": round(migration_seconds, 2), "outbox_rows_queued_by_backfill": queued},
            "write_overhead_per_operation": overhead, "indexing": indexing,
            "storage": {**grown, "index_bytes_per_row": round(grown["knowledge_items_total_bytes"] / max(grown["rows"], 1)) if grown["rows"] else None,
                        "index_vs_sources_ratio": round(grown["knowledge_items_total_bytes"] / max(sources, 1), 2)},
        }, indent=2, default=float))
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


if __name__ == "__main__":
    main()
