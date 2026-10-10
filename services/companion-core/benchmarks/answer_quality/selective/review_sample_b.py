"""Preselect the PROSPECTIVE development review sample for the changed wording (Phase 44, final development pass, 2026-10-10). Run ONCE; the output and this script are then frozen by hash
(`REVIEW_SAMPLE_B_FREEZE.sha256`).

What it is for: the wording changes of this pass (the record's relative time kept, decisions and plans reported as such, explicit value transitions read, plural agreement, templates for decisions and
reviews, question order kept, double "for" removed, the "cannot read safely" wording). It is a NEW sample: no question of the earlier frozen 51-sample (`review_sample_frozen.json`) can be drawn.

Selection uses only the dev15 gold structure (the relations and statuses of each question's atoms), never a reply. Disclosure: before this sample was drawn the author had already printed the rendered text of
the 13 false abstentions and 16 template-check misses of the new path (for example the "decided on" sentence and the reworded ordering sentence); the strata do not use any of that text, and the overlap with
the drawn sample is reported by the review packet.

    python review_sample_b.py     -> review_sample_b_frozen.json
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261011


def main():
    rnd = random.Random(SEED)
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    prior = {d["id"] for d in json.loads((HERE / "review_sample_frozen.json").read_text())["dev15"]}
    rel = {c["id"]: [a["relation"] for a in c["atoms"]] for c in cases}
    status = {c["id"]: [a["status"] for a in c["atoms"]] for c in cases}
    strata = [  # rarest first; a question is drawn into the first stratum that wants it
        ("decision relation (decision template)", lambda i: "decision" in rel[i], 3),
        ("review text (review template)", lambda i: "reviews" in rel[i], 2),
        ("vacation (reworded label)", lambda i: "vacation" in rel[i], 2),
        ("support hours (plural agreement)", lambda i: "support_hours" in rel[i], 2),
        ("ordering (reworded ordering sentence)", lambda i: "ORDER_UNSUPPORTED" in status[i], 3),
        ("on call (relative time kept)", lambda i: "on_call" in rel[i], 4),
        ("default model, history (explicit transition)", lambda i: "default_model_history" in rel[i], 4),
        ("default model, current (decision versus configured)", lambda i: "default_model" in rel[i], 4),
        ("three or more parts (question order kept)", lambda i: len(rel[i]) >= 3, 4),
    ]
    taken: dict[str, str] = {}
    for name, pred, n in strata:
        pool = sorted(c["id"] for c in cases if c["id"] not in prior and c["id"] not in taken and pred(c["id"]))
        rnd.shuffle(pool)
        for cid in sorted(pool[:n]):
            taken[cid] = name
    counts: dict[str, int] = {}
    for v in taken.values():
        counts[v] = counts.get(v, 0) + 1
    out = {"seed": SEED, "frozen_before_any_reply_was_chosen_from": True, "excluded_prior_sample": len(prior), "dev15": [{"id": c, "stratum": taken[c]} for c in sorted(taken)], "strata_counts": counts}
    (HERE / "review_sample_b_frozen.json").write_text(json.dumps(out, indent=1) + "\n")
    print(len(out["dev15"]), "questions;", counts)


if __name__ == "__main__":
    main()
