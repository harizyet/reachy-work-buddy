"""Retrieval-only design evaluation of the coverage assessors (no model is called): for each case, B1a retrieval through the harness, then the verdict of the item-level comparator and the section-level
variants on the evidence the model would see. Used on the DESIGN set (dev9) and, as a false-note regression only, on the older development splits. Never on dev8 or the acceptance set.

    python sec_design_eval.py --splits dev9 [--show]"""
from __future__ import annotations

import argparse
import asyncio
import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib
from aq.conditions_sec import SecConditions

ALLOWED = ("dev", "dev2", "dev3", "dev4", "dev5", "dev6", "dev7", "dev9")


class FakeLLM:
    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


async def main_async(splits, show):
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus

    spec = (await build_corpus()).spec
    from companion_core.rag import embeddings

    embeddings.embed(["warm up"])
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME)
    runner = SecConditions(env, spec, FakeLLM(), budget=1500, minilm_embed=embeddings.embed)
    rows = []
    try:
        for split in splits:
            for c in caselib.load_cases(split):
                out = {}
                for v in ("sec", "secd"):
                    prep = await runner.prepare(f"b1a+routed+{v}", c)
                    out[v] = prep.suff or {}
                rows.append({"split": split, "id": c["id"], "cat": c["category"], "abstain": c["abstain"], "q": c["question"],
                             "item": out["sec"].get("item_level"), "sec": out["sec"].get("first"), "secd": out["secd"].get("first")})
    finally:
        await env.close()
    for label in ("item", "sec", "secd"):
        print(f"\n== {label}")
        for grp, pick in (("answerable", lambda r: not r["abstain"]), ("abstention", lambda r: r["abstain"]), ("wrong_entity+cross_section", lambda r: r["cat"] in ("wrong_entity", "cross_section"))):
            sub = [r for r in rows if r[label] is not None and pick(r)]
            flagged = [r for r in sub if r[label] != "sufficient"]
            print(f"  {grp:28} n={len(sub):3} flagged {len(flagged):3}  {dict(collections.Counter(r[label] for r in sub))}")
    if show:
        for r in rows:
            exp_flag = r["abstain"] or r["cat"] in ("wrong_entity", "cross_section")
            if any(r[v] is not None and ((r[v] != "sufficient") != exp_flag) for v in ("item", "sec", "secd")):
                print(f"{r['id']:6} {r['cat']:16} item={r['item']} sec={r['sec']} secd={r['secd']} | {r['q']}")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", default="dev9")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    bad = [s for s in a.splits.split(",") if s not in ALLOWED]
    if bad:
        raise SystemExit(f"not allowed for design: {bad}")
    asyncio.run(main_async(a.splits.split(","), a.show))
