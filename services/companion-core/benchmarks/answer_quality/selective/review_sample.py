"""Preselect the manual-review sample for the I-2 follow-up (2026-10-10). Run ONCE, before any reply of the new registry / decomposer path is rendered; the output and this script are then frozen by hash
(`REVIEW_SAMPLE_FREEZE.sha256`) and `i2b_eval.py` refuses to run if they changed.

Inputs are only things that exist before the new path does: the dev15 gold structure (status, family), the OLD committed I-2 replies (used solely to find questions whose old reply was an "unclear"
ambiguity reply) and the corpus-v5 sweep worlds. No new reply is read. Selection is seeded and stratified; a question is drawn into the first stratum that wants it (rarest first).

    python review_sample.py     -> review_sample_frozen.json
"""
from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SEED = 20261010
ANSWERED = {"SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED"}
WITHHELD = {"UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED"}


def main():
    rnd = random.Random(SEED)
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    old = {json.loads(line)["id"]: json.loads(line) for line in (HERE.parent / "results" / "i2-dev15-replies.jsonl").read_text().splitlines()}
    statuses = {c["id"]: [a["status"] for a in c["atoms"]] for c in cases}

    def pick(pred, n, taken):
        pool = sorted(c["id"] for c in cases if c["id"] not in taken and pred(c))
        rnd.shuffle(pool)
        return sorted(pool[:n])

    strata = [
        ("ambiguous (old reply was an unclear-records reply)", lambda c: "unclear" in old[c["id"]]["answer"], 5),
        ("ordering", lambda c: "ORDER_UNSUPPORTED" in statuses[c["id"]], 3),
        ("negative (existence)", lambda c: c["family"] == "negative", 4),
        ("historical", lambda c: "HISTORICAL" in statuses[c["id"]], 5),
        ("conflicted", lambda c: "CONFLICTED" in statuses[c["id"]], 5),
        ("abstained (every part withheld)", lambda c: all(s in WITHHELD for s in statuses[c["id"]]), 4),
        ("supported (every part answerable)", lambda c: all(s in ANSWERED | {"CONFLICTED"} for s in statuses[c["id"]]) and "CONFLICTED" not in statuses[c["id"]], 4),
        ("partial (an answerable part and a withheld part)", lambda c: any(s in ANSWERED for s in statuses[c["id"]]) and any(s in WITHHELD for s in statuses[c["id"]]), 8),
        ("unconstrained draw", lambda c: True, 4),
    ]
    taken: dict[str, str] = {}
    for name, pred, n in strata:
        for cid in pick(pred, n, taken):
            taken[cid] = name

    import corpus_gen_v5 as g5

    sweep = []
    for seed in (101, 102):
        _, registry = g5.build(seed)
        facts = [(seed, f["subject"], f["relation"], f["state"]) for f in registry["facts"] if f["relation"] in g5.FAMILIES]
        sweep.extend(facts)
    by_cond = collections.defaultdict(list)
    for s in sweep:
        by_cond[s[3]].append(s)
    chosen = []
    for cond, n in (("incomplete_scope", 6), ("explicit_absence", 1), ("source_disagreement", 1), ("unauthorized_only", 1)):
        pool = sorted(by_cond[cond])
        rnd.shuffle(pool)
        chosen.extend(pool[:n])
    out = {
        "seed": SEED, "frozen_before_any_new_reply": True,
        "dev15": [{"id": cid, "stratum": taken[cid], "family": next(c["family"] for c in cases if c["id"] == cid)} for cid in sorted(taken)],
        "existence_sweep": [{"seed": s, "subject": sub, "relation": rel, "condition": cond} for s, sub, rel, cond in chosen],
        "strata_counts": dict(collections.Counter(taken.values())),
    }
    (HERE / "review_sample_frozen.json").write_text(json.dumps(out, indent=1) + "\n")
    print(len(out["dev15"]), "dev15 questions;", len(out["existence_sweep"]), "sweep facts;", out["strata_counts"])


if __name__ == "__main__":
    main()
