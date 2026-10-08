"""Why do the lexical and hybrid configurations differ? Development cases only.

For each DEVELOPMENT case it runs B1b with a full trace and reports, for every expected source, its rank in the lexical list, the vector
list, the fused list and the final result, so a difference between B1a (lexical) and B1b (hybrid) can be traced to the leg that caused it.
It never loads the holdout and cannot change a configuration: it only reads.

    DATABASE_MIGRATION_TEST_URL=postgresql://... python b1_investigate.py [--out FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from companion_core.knowledge.retrieval import B1A, B1B, Retriever
from companion_core.rag import embeddings
from kbench.corpus import build_corpus
from kbench.fixtures import load_cases, load_corpus
from kbench.pg_env import build_pg_corpus
from kbench.scoring import dedupe, matches
from kbench.security import access_context


def rank_of(keys: list[str], expected: str) -> int | None:
    for i, key in enumerate(dedupe(keys), start=1):
        if matches(key, expected):
            return i
    return None


async def main(out: str | None) -> None:
    corpus = load_corpus()
    env = await build_pg_corpus((await build_corpus()).spec, embeddings.embed, embeddings._MODEL_NAME)
    lexical = Retriever(search=env.search, adapters=env.adapters, config=B1A)
    hybrid = Retriever(search=env.search, adapters=env.adapters, config=B1B, embed_fn=embeddings.embed)
    rows = []
    for case in load_cases("dev"):  # development only, by construction
        if not case["expected_refs"]:
            continue
        access = access_context(corpus["access_profiles"][case["access"]])
        a = await lexical.retrieve(case["question"], access, temporal=case["temporal"])
        b = await hybrid.retrieve(case["question"], access, temporal=case["temporal"])
        final_a = [env.logical_key(i.ref.key) for i in a.bundle.items]
        final_b = [env.logical_key(i.ref.key) for i in b.bundle.items]
        by_key = {env.logical_key(c.ref_key): c for c in b.trace.candidates}
        detail = []
        for expected in case["expected_refs"]:
            hit = next((c for k, c in by_key.items() if matches(k, expected)), None)
            detail.append({
                "expected": expected, "lexical_rank": hit.lexical_rank if hit else None, "vector_rank": hit.vector_rank if hit else None,
                "fused_rank": hit.fused_rank if hit else None, "final_rank_b1a": rank_of(final_a, expected), "final_rank_b1b": rank_of(final_b, expected),
            })
        ahead = [
            {"key": k, "lexical_rank": c.lexical_rank, "vector_rank": c.vector_rank}
            for k, c in sorted(by_key.items(), key=lambda kv: kv[1].fused_rank)[:5]
            if not any(matches(k, e) for e in case["expected_refs"])
        ]
        in5_a = sum(1 for e in case["expected_refs"] if (rank_of(final_a, e) or 99) <= 5)
        in5_b = sum(1 for e in case["expected_refs"] if (rank_of(final_b, e) or 99) <= 5)
        rows.append({"id": case["id"], "category": case["category"], "question": case["question"], "expected_in_top5": {"b1a": in5_a, "b1b": in5_b, "of": len(case["expected_refs"])},
                     "differs": in5_a != in5_b, "expected": detail, "unneeded_in_fused_top5": ahead})
    await env.close()
    report = {"split": "dev", "differing_cases": [r["id"] for r in rows if r["differs"]], "cases": rows}
    text = json.dumps(report, indent=2)
    if out:
        Path(out).write_text(text + "\n")
    else:
        print(text)
    for r in rows:
        if r["differs"]:
            print(f"\n{r['id']} ({r['category']}): {r['question']}\n  expected in top 5: B1a {r['expected_in_top5']['b1a']}, B1b {r['expected_in_top5']['b1b']} of {r['expected_in_top5']['of']}")
            for d in r["expected"]:
                print(f"    {d['expected']}: lexical rank {d['lexical_rank']}, vector rank {d['vector_rank']}, fused {d['fused_rank']}, final B1a {d['final_rank_b1a']}, B1b {d['final_rank_b1b']}")
            for x in r["unneeded_in_fused_top5"][:3]:
                print(f"    ahead of it in the fused list: {x['key']} (lexical {x['lexical_rank']}, vector {x['vector_rank']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out")
    asyncio.run(main(parser.parse_args().out))
