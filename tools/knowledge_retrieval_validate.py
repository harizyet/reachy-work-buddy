"""Phase 48E retrieval-only validation: runs the production retrieval configuration (B1a, the one the answerer would use) over a frozen case file and
reports per-case and aggregate metrics. It never generates text and never writes: no outbox row, no index write, no source write. Run it inside a
throwaway container from the production core image (see docs/verification/phase-48e-*.md), with DATABASE_URL pointing at the database to read.

  python knowledge_retrieval_validate.py CASES.json > results.json

Case file: {"cases": [{"id", "category", "query", "access": "owner" | "shared" | "owner_sensitive" | "scope:<name>[,<name>]",
                        "temporal": "current" | "include_historical",
                        "expect": [{"source_type", "source_id", "locators": [optional line/locator prefixes]}],   # sources that answer the query
                        "forbid": [{"source_type", "source_id", "why"}],          # sources that must not appear for this caller
                        "forbid_query_from": {"memory_id": ...}}]}                # query taken from a record the owner forgot, never printed

Checks that apply to every returned item regardless of the case: its sensitivity is within the caller's ceiling, its scope is allowed for the caller,
and its source is, in the authoritative store right now, visible (not forgotten, expired, deleted or cancelled) and contains the cited part (the
citation resolves). Generated summaries and minutes must be labelled `model_generated`. The results contain identifiers, ranks and counts, not text,
except when --text is given."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys

from companion_core.knowledge.retrieval import B1A, Retriever
from companion_core.knowledge.search import PostgresSearch
from companion_core.knowledge.sources import build_adapters
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.semantic.access import access_for_owner
from companion_core.tasks.postgres_store import PostgresTaskStore

from shared.database import DatabaseManager

RANK = {"public": 0, "work-private": 1, "sensitive": 2}
KS = (1, 3, 5)


def access_for(spec: str):
    if spec == "shared":
        return access_for_owner("owner", channel_private=False), "public", None
    if spec == "owner_sensitive":
        return access_for_owner("owner", channel_private=True, allow_sensitive=True), "sensitive", None
    if spec.startswith("scope:"):
        scopes = frozenset(s for s in spec[6:].split(",") if s)
        return access_for_owner("owner", channel_private=True, project_scopes=scopes), "work-private", scopes
    return access_for_owner("owner", channel_private=True), "work-private", None


def matches(item, want: dict) -> bool:
    ref = item.ref
    if ref.source_type != want["source_type"] or ref.source_id != want["source_id"]:
        return False
    locators = want.get("locators")
    return not locators or any(str(ref.locator or "").startswith(str(p)) for p in locators)


async def main(cases_path: str, with_text: bool) -> None:
    db = await DatabaseManager(os.environ["DATABASE_URL"], vector=True, min_size=1, max_size=2).start()
    memories = await PostgresMemoryStore.connect(db)
    adapters = build_adapters(memory=memories, documents=await PostgresDocumentStore.connect(db), meetings=await PostgresMeetingStore.connect(db),
                              planner=await PostgresPlannerStore.connect(db), tasks=await PostgresTaskStore.connect(db))
    retriever = Retriever(search=PostgresSearch(db.pool), adapters=adapters, config=B1A)
    cases = json.loads(pathlib.Path(cases_path).read_text())["cases"]
    out = []
    for case in cases:
        access, ceiling, scopes = access_for(case.get("access", "owner"))
        query = case["query"]
        if "forbid_query_from" in case:  # a forgotten or expired memory's own words, taken here so the person writing the cases never has to read it
            async with db.pool.connection() as conn:
                row = await (await conn.execute("SELECT content FROM memories WHERE id = %s", (case["forbid_query_from"]["memory_id"],))).fetchone()
            query = " ".join(row[0].split()[: case["forbid_query_from"].get("words", 6)]) if row else ""
        result = await retriever.retrieve(query, access, temporal=case.get("temporal", "current"), limit=10)
        items = result.bundle.items
        expect, forbid = case.get("expect", []), case.get("forbid", [])
        ranks = [next((i for i, it in enumerate(items, 1) if matches(it, w)), None) for w in expect]
        first = min((r for r in ranks if r), default=None)
        top5_sources = {(it.ref.source_type, it.ref.source_id) for it in items[:5]}
        want_sources = {(w["source_type"], w["source_id"]) for w in expect}
        violations: list[str] = []
        for it in items:
            if RANK[it.sensitivity.value] > RANK[ceiling]:
                violations.append(f"restricted:{it.ref.key}")
            if scopes is not None and it.project_scope is not None and it.project_scope not in scopes:
                violations.append(f"cross_scope:{it.ref.key}")  # another project's record. An UNSCOPED record is, by design (D8; search.py "these scopes plus unscoped rows"), visible to a scoped caller
            if it.provenance.authority != "model_generated" and it.kind in ("meeting_summary", "meeting_minutes"):
                violations.append(f"generated_unlabelled:{it.ref.key}")
            state = await adapters[it.ref.source_type].state(it.ref.source_id)
            if state.status != "visible":
                violations.append(f"stale_{state.status}:{it.ref.key}")
            elif it.ref.key not in {x.ref.key for x in state.items}:
                violations.append(f"citation_unresolved:{it.ref.key}")
        unscoped_seen = [it.ref.key for it in items if scopes is not None and it.project_scope is None]
        for f in forbid:
            if any(it.ref.source_type == f["source_type"] and it.ref.source_id == f["source_id"] for it in items):
                violations.append(f"forbidden_present:{f['source_type']}:{f['source_id']}:{f.get('why', '')}")
        record = {
            "id": case["id"], "category": case["category"], "access": case.get("access", "owner"), "temporal": case.get("temporal", "current"),
            "expected_sources": [f"{w['source_type']}:{w['source_id']}" for w in expect], "n_returned": len(items), "first_hit_rank": first,
            "hit_at": {str(k): bool(first and first <= k) for k in KS},
            "precision_at_5": (sum((it.ref.source_type, it.ref.source_id) in want_sources for it in items[:5]) / max(1, len(items[:5]))) if expect and items else None,
            "all_expected_in_top5": all(r and r <= 5 for r in ranks) if expect else None,
            "top5": [{"ref": it.ref.key, "kind": it.kind, "sensitivity": it.sensitivity.value, "scope": it.project_scope, "authority": it.provenance.authority} for it in items[:5]],
            "dropped": dict(result.bundle.dropped), "violations": violations, "unscoped_items_shown_to_scoped_caller": unscoped_seen, "top5_source_types": sorted({s[0] for s in top5_sources}),
            "latency_ms": round(sum(result.trace.timings_ms.values()), 1),
        }
        if with_text:
            record["query"], record["top5_text"] = query, [it.text[:160] for it in items[:5]]
        out.append(record)
    json.dump({"cases": out}, sys.stdout, indent=1)
    await db.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--text", action="store_true", help="include query and the first 160 characters of each hit (private; never commit)")
    args = ap.parse_args()
    asyncio.run(main(args.cases, args.text))
