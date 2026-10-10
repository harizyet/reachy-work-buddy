"""Isolated probe of the random-ID tie-breaker hypothesis (Phase 44, P0 reproducibility correction, 2026-10-10). Consumed dev15 questions and the invented corpus only; a disposable database; NO model call and no
server contact (retrieval layer only).

Hypothesis: the lexical search orders results by (rank DESC, ref_key); `ref_key` embeds the store id (a random UUID assigned when the database is built), so records with EQUAL rank change places between builds.
Predictions, each checked directly against the search layer of two independently built databases:
  P1 the multiset of scores is identical across builds (relevance is content-determined);
  P2 the logical-key sequences differ between builds only where the scores are equal (inside a tie group, including one truncated by the limit);
  P3 inside every equal-score group, each build's order equals the ascending order of that build's own ref_keys;
  P4 the sets of logical records in each fully-contained tie group are identical across builds (only their order changes);
  P5 a tie group that straddles the LIMIT can differ in membership between builds.
A control builds the same two databases with the stable-id option (when available) and expects zero differences.

    python dev16_p0_tiebreak_probe.py <output-json> [--stable]       (KBENCH_DATABASE_URL must name the disposable server)
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parents[1] / "knowledge_retrieval")]


async def build(stable: bool):
    from companion_core.knowledge.search import SearchFilter
    from companion_core.rag import embeddings
    from kbench.corpus import build_corpus
    from kbench.pg_env import build_pg_corpus

    spec = (await build_corpus()).spec
    embeddings.embed(["warm up"])
    kwargs = {"stable": True} if stable else {}
    env = await build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME, **kwargs)
    return env, SearchFilter(sensitivities=("public", "work-private", "sensitive"))


async def hits(env, flt, questions: list[str], limit: int) -> dict:
    out = {}
    for q in questions:
        out[q] = [(h.ref_key, round(h.score, 9)) for h in await env.search.lexical(q, flt, limit)]
    return out


def groups(seq: list[tuple[str, float]]):
    g = collections.OrderedDict()
    for key, score in seq:
        g.setdefault(score, []).append(key)
    return g


async def main(out: Path, stable: bool) -> dict:
    os.environ.setdefault("KBENCH_CORPUS", str(HERE / "corpus_v4.json"))
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    questions = sorted({c["question"] for c in cases})
    limit = 40
    env_a, flt = await build(stable)
    ha = await hits(env_a, flt, questions, limit)
    la, ids_a = env_a.logical_key, dict(env_a.store_id)
    env_b, _ = await build(stable)
    hb = await hits(env_b, flt, questions, limit)
    lb, ids_b = env_b.logical_key, dict(env_b.store_id)
    res = collections.Counter()
    examples, outside = [], []
    for q in questions:
        a, b = ha[q], hb[q]
        res["queries"] += 1
        res["P1_scores_identical"] += sorted(s for _, s in a) == sorted(s for _, s in b)
        seq_a, seq_b = [la(k) for k, _ in a], [lb(k) for k, _ in b]
        differs = seq_a != seq_b
        res["sequences_differ"] += differs
        ga, gb = groups(a), groups(b)
        last = list(ga)[-1] if ga else None
        res["P3_within_group_order_is_ref_key_order"] += all([k for k in v] == sorted(v) for v in ga.values()) and all([k for k in v] == sorted(v) for v in gb.values())
        inside_ok = True
        for score, keys in ga.items():
            if score == last and len(a) == limit:
                continue
            other = gb.get(score, [])
            if sorted(la(k) for k in keys) != sorted(lb(k) for k in other):
                inside_ok = False
        res["P4_contained_groups_same_membership"] += inside_ok
        diff_outside_ties = False
        for pos, (x, y) in enumerate(zip(seq_a, seq_b, strict=False)):
            if x != y and a[pos][1] != b[pos][1]:  # records differ AND the scores differ: not explained by a tie (a tie group truncated by the limit keeps equal scores in both builds)
                diff_outside_ties = True
                outside.append({"query": q[:70], "position": pos, "score_a": a[pos][1], "score_b": b[pos][1], "group_size_a": len(ga.get(a[pos][1], [])), "group_size_b": len(gb.get(b[pos][1], [])), "record_a": x, "record_b": y,
                                "scores_around_a": [s for _, s in a[max(0, pos - 2):pos + 3]], "scores_around_b": [s for _, s in b[max(0, pos - 2):pos + 3]]})
        res["differences_outside_tie_groups"] += diff_outside_ties
        boundary_differs = len(a) == limit and set(seq_a) != set(seq_b)
        res["P5_cut_membership_differs"] += boundary_differs
        res["queries_with_any_tie_group"] += any(len(v) > 1 for v in ga.values())
        if differs and len(examples) < 3:
            examples.append({"query": q[:80], "tie_groups_sizes": [len(v) for v in ga.values() if len(v) > 1][:6]})
    res["store_ids_identical_across_builds"] = int(ids_a == ids_b)
    report = {"stable_ids": stable, "limit": limit, "results": dict(res), "examples": examples, "outside_tie_group_details": outside}
    await env_a.close()
    await env_b.close()
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(Path(ORIG[1]), "--stable" in ORIG)), indent=1))
