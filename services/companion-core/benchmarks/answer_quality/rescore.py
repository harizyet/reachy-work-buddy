"""Apply scorer v2 to a stored run and write the DIFFERENCES from the original scores as annotations. The original file is never modified.

    python rescore.py results/holdout-44E-first-look.json --split holdout --out results/holdout-44E-first-look.rescore-v2.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aq import cases as caselib
from aq import scoring_v2

WATCH = ("correctness", "abstained", "fabricated")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("run")
    p.add_argument("--split", default="holdout")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    run = json.loads(Path(args.run).read_text())
    cases = {c["id"]: c for c in caselib.load_cases(args.split)}
    notes, rows = [], []
    for row in run["rows"]:
        case = cases[row["id"]]
        ctx = {"entries": row["context"]["entries"], "has_ids": bool(row["score"].get("citation")), "text": row["context"].get("text", ""),
               "prompt_violations": [v for v in row["score"]["privacy"]["rule_violations_in_prompt"]]}
        new = scoring_v2.score_answer(case, row["reply"], ctx)
        old = row["score"]
        diff = {}
        for key, a, b in (
            ("privacy.canary_in_reply", old["privacy"]["canary_in_reply"], new["privacy"]["canary_in_reply"]),
            ("privacy.clean", old["privacy"]["clean"], new["privacy"]["clean"]),
            ("injection.followed", (old["injection"] or {}).get("followed"), (new["injection"] or {}).get("followed")),
            ("citation.correct", (old.get("citation") or {}).get("correct"), (new.get("citation") or {}).get("correct")),
            ("citation.uncited_answer", (old.get("citation") or {}).get("uncited_answer"), (new.get("citation") or {}).get("uncited_answer")),
            *((k, old.get(k), new.get(k)) for k in WATCH),
        ):
            if a != b:
                diff[key] = {"v1": a, "v2": b}
        rows.append({**{k: row[k] for k in ("id", "category", "condition", "reply", "cost", "context")}, "score": new})
        if diff:
            notes.append({"id": row["id"], "category": row["category"], "condition": row["condition"], "changes": diff})
    out = {"annotation_of": args.run, "scorer": "v2", "original_scores_unchanged": True, "changed_rows": len(notes), "changes": notes}
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    Path(args.out.replace(".json", ".rows.json")).write_text(json.dumps({**{k: v for k, v in run.items() if k != "rows"}, "scorer": "v2", "rows": rows}))
    print(f"{len(notes)} rows differ under v2 of {len(run['rows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
