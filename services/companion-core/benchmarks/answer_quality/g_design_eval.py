"""Component-level design evaluation of C1 and C2 on corpus v2 (no model): for each DESIGN question (not held out, phrasings 0 and 1), B1a retrieval of 30 candidates, then
 C1: gold-source recall and the number of non-gold records shown, against B1a's top 10; and the share of questions where the selected records contain the gold sources;
 C2: the answerability state against the registry's label (null generator).
Never reads the acceptance set or any held-out question.

    KBENCH_CORPUS=.../corpus_v2.json python g_design_eval.py [--show]"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "corpus_v2"))
from aq import cases as _cases  # noqa: F401  (puts the kbench path on sys.path)
from aq.conditions_sec import SecConditions
from aq.scoring import ref_matches
from companion_core.knowledge.grounding import answerability, propositions
from companion_core.knowledge.sufficiency import pieces_from_items
from gen import PEOPLE


class FakeLLM:
    def count_tokens(self, text):
        return max(1, len(text) // 4)


async def main_async(show, limit, strict=False):
    from companion_core.rag import embeddings
    from companion_core.semantic.model import SourceFilters
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus
    from kbench.security import access_context

    spec = (await build_corpus()).spec
    embeddings.embed(["warm up"])
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME)
    runner = SecConditions(env, spec, FakeLLM(), budget=1500, minilm_embed=embeddings.embed)
    pool = [c for c in json.loads((HERE / "corpus_v2/pool_v2.json").read_text())["cases"] if not c["held_out"] and c["phrasing"] in (0, 1)]
    if limit:
        pool = pool[::max(1, len(pool) // limit)]
    rows = []
    try:
        for c in pool:
            access = access_context(spec["access_profiles"][c["access"]])
            res = await runner.retriever("b1a").retrieve(c["question"], access, SourceFilters(), temporal=c["temporal"], limit=30)
            items = list(res.bundle.items)
            pieces = pieces_from_items(items)
            keys = [runner.env.logical_key(i.ref.key) for i in items]
            from datetime import UTC, datetime

            from companion_core.knowledge.context import _is_historical

            now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
            skip = {i for i, it in enumerate(items) if c['temporal'] != 'include_historical' and _is_historical(it, now)}
            sel = propositions.select(c["question"], pieces, known_people=PEOPLE, skip=skip, strict_qualifiers=strict)
            ans = answerability.assess(sel, strict_qualifiers=strict)
            gold = c["gold_refs"]

            def has_gold(idxs, keys=keys, gold=gold):
                got = [keys[i] for i in idxs]
                return all(any(ref_matches(k, g) for k in got) for g in gold) if gold else None

            top10 = list(range(min(10, len(items))))
            filt = [items.index(x) for x in propositions.reorder(items, sel, "filter")]
            rows.append({"id": c["id"], "label": c["label"], "reason": c["reason"], "relation": c["relation"], "q": c["question"], "gold": len(gold),
                         "b1a_has_gold": has_gold(top10), "c1_has_gold": has_gold(filt), "b1a_shown": len(top10), "c1_shown": len(filt),
                         "b1a_nongold": sum(1 for i in top10 if not any(ref_matches(keys[i], g) for g in gold)), "c1_nongold": sum(1 for i in filt if not any(ref_matches(keys[i], g) for g in gold)),
                         "state": ans.state, "recognised": sel.propositions[0].relation, "diag": [[a.item_index, list(a.values), a.unit[:90]] for a in sel.assertions[0]][:5], "props": [[list(p.subjects), p.relation, list(p.cues)] for p in sel.propositions]})
    finally:
        await env.close()
    answerable = [r for r in rows if r["gold"]]
    print(f"design questions {len(rows)} (answerable-with-gold {len(answerable)})")
    print(f"C1 gold recall: B1a top10 {sum(bool(r['b1a_has_gold']) for r in answerable)}/{len(answerable)}; C1 filter {sum(bool(r['c1_has_gold']) for r in answerable)}/{len(answerable)}")
    print(f"mean records shown: B1a {sum(r['b1a_shown'] for r in rows) / len(rows):.1f}, C1 {sum(r['c1_shown'] for r in rows) / len(rows):.1f}; mean non-gold shown: B1a {sum(r['b1a_nongold'] for r in rows) / len(rows):.1f}, C1 {sum(r['c1_nongold'] for r in rows) / len(rows):.1f}")
    print(f"relation recognised on {sum(bool(r['recognised']) for r in rows)}/{len(rows)}")
    want = {"ESTABLISHED": "ESTABLISHED", "CONFLICTED": "CONFLICTED", "PARTIAL": "PARTIAL", "SUPERSEDED": "ESTABLISHED", "UNESTABLISHED": "UNESTABLISHED"}
    for r in rows:  # "which model does the deep path serve" is unestablished as asked, although the document answers part of it
        if r["relation"] == "deep_path_model":
            r["label"] = "UNESTABLISHED"
    conf = collections.Counter((want[r["label"]], r["state"]) for r in rows)
    print("C2 confusion (label -> state):")
    for (l, s), n in sorted(conf.items()):
        print(f"   {l:14} -> {s:14} {n}")
    amb = [r for r in rows if want[r["label"]] != "UNESTABLISHED"]
    print(f"false UNESTABLISHED on answerable-labelled questions: {sum(r['state'] == 'UNESTABLISHED' for r in amb)}/{len(amb)}")
    un = [r for r in rows if want[r["label"]] == "UNESTABLISHED"]
    print(f"UNESTABLISHED correctly detected: {sum(r['state'] == 'UNESTABLISHED' for r in un)}/{len(un)}")
    if show:
        for r in rows:
            if (want[r["label"]] != r["state"]):
                print(f"   {r['id']} {r['label']}:{r['reason']} -> {r['state']} rel={r['recognised']} | {r['q']}")
    Path(HERE / "results/g-design-eval.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    asyncio.run(main_async(a.show, a.limit, a.strict))
