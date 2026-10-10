"""Phase 48F offline probe: runs the deterministic selective-answering path (classification, retrieval, revalidation, evidence rules, verification, rendering) over a frozen
question file and records what it WOULD do, with the same code, access derivation and retrieval configuration the shadow and the live answerer use. It serves no one: nothing is
sent anywhere, nothing is written to a database, and it does not enable anything. Run it inside a throwaway container from the production core image against a database.

  python knowledge_selective_probe.py CASES.json [--text] > results.json

Case file: {"cases": [{"id", "category", "question", "modality": "text" | "voice", "truth": "answerable" | "absent" | "not_knowledge" | "status" | "restricted",
                        "must_cite": ["note:<id>", ...]}]}                 # sources a correct answer is allowed to rest on (source-level)

The result carries only categories (class, reason, state, citation count) plus whether every cited source is in `must_cite`. With --text it also carries the rendered reply, which can
contain private record text: the person reading it must keep it out of the repository."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from datetime import UTC, datetime

from companion_core.knowledge import qualify as knowledge_qualify
from companion_core.knowledge.index import PostgresKnowledgeIndex
from companion_core.knowledge.retrieval import B1A, Retriever
from companion_core.knowledge.search import PostgresSearch
from companion_core.knowledge.selective_answer import SelectiveAnswerer
from companion_core.knowledge.sources import build_adapters
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.memory.postgres_store import PostgresMemoryStore
from companion_core.planner.postgres_store import PostgresPlannerStore
from companion_core.rag.postgres_store import PostgresDocumentStore
from companion_core.tasks.postgres_store import PostgresTaskStore

from shared.database import DatabaseManager


async def main(path: str, with_text: bool) -> None:
    db = await DatabaseManager(os.environ["DATABASE_URL"], vector=True, min_size=1, max_size=2).start()
    adapters = build_adapters(memory=await PostgresMemoryStore.connect(db), documents=await PostgresDocumentStore.connect(db), meetings=await PostgresMeetingStore.connect(db),
                              planner=await PostgresPlannerStore.connect(db), tasks=await PostgresTaskStore.connect(db))

    async def vocabulary() -> frozenset[str]:
        return await knowledge_qualify.build_vocabulary(adapters)

    answerer = SelectiveAnswerer(retriever=Retriever(search=PostgresSearch(db.pool), adapters=adapters, config=B1A, clock=lambda: datetime.now(UTC)),
                                 index_count=PostgresKnowledgeIndex(db.pool).count, vocabulary=vocabulary)
    await answerer.start()
    results = []
    for case in json.loads(pathlib.Path(path).read_text())["cases"]:
        text, modality = case["question"], case.get("modality", "text")
        klass = answerer.classify(text, attached_meeting=False)
        record = {"id": case["id"], "category": case["category"], "modality": modality, "truth": case["truth"], "klass": klass.klass, "reason": klass.reason,
                  "anchors": list(klass.anchors), "clauses": klass.clauses, "typed_clauses": klass.typed}
        if klass.klass in ("typed", "ambiguous"):
            outcome, n, state, qualified = await answerer._pipeline(text, modality)  # the same call the shadow's assessment and the live path make
            cited = set(outcome.cited)
            allowed = set(case.get("must_cite", []))
            record.update({"state": state, "zero_evidence_qualified": qualified, "citations": n, "privacy": outcome.privacy.value,
                           "cited_sources": sorted(c.split("#")[0] for c in cited), "cites_only_allowed_sources": (all(c.split("#")[0] in allowed for c in cited) if cited else None)})
            if with_text:
                record["reply"] = outcome.reply
        if with_text:
            record["question"] = text
        results.append(record)
    json.dump({"cases": results}, sys.stdout, indent=1)
    await db.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--text", action="store_true", help="include the question and the rendered reply (private; never commit)")
    args = ap.parse_args()
    asyncio.run(main(args.cases, args.text))
