"""How sensitive is the hybrid (B1b) result to its two free parameters? Runs B1b on the DEVELOPMENT split only for a small grid of
reciprocal-rank-fusion constants and per-leg candidate counts, with the real MiniLM embedder, and prints one line per setting. This is a
robustness check, not a tuning step: the settings used elsewhere stay at the standard values (k=60, 40 candidates).

    DATABASE_MIGRATION_TEST_URL=postgresql://... python b1_sensitivity.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from companion_core.knowledge.retrieval import B1B
from kbench.b1 import B1Adapter
from kbench.report import evaluate


async def main() -> None:
    rows = []
    for k in (10, 30, 60, 100):
        for candidates in (20, 40, 100):
            config = replace(B1B, name=f"B1b-k{k}-n{candidates}", rrf_k=k, candidates=candidates)
            report = await evaluate(B1Adapter("b1b", config=config), "dev", embedder="minilm", probes=False)
            s = report["summary"]
            rows.append({"k": k, "candidates": candidates, "recall@3": s["recall@3"], "recall@5": s["recall@5"], "recall@10": s["recall@10"],
                         "mrr": s["mrr"], "full_recall@5": s["full_recall@5"]["successes"], "exposed_leaks": s["leakage"]["leaked_hits"]})
            print(json.dumps(rows[-1]), flush=True)
    print(json.dumps({"summary": {"recall@5_range": [min(r["recall@5"] for r in rows), max(r["recall@5"] for r in rows)],
                                  "mrr_range": [min(r["mrr"] for r in rows), max(r["mrr"] for r in rows)],
                                  "exposed_leaks_total": sum(r["exposed_leaks"] for r in rows)}}))


if __name__ == "__main__":
    asyncio.run(main())
