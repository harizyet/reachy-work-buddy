"""Evaluate the post-generation checks (aq/postcheck.py) on stored replies. Label: the case scorer's "bad" (a forbidden assertion, or a fabrication on an abstention case). That label has known
false positives, so precision here is a lower bound; recall is against the scorer's own failures. Rows from the consumed holdout are never read.

    python postcheck_eval.py results/dev6-7b-suff.json results/suffreg-dev5.json ... --out results/postcheck-eval.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib
from aq import postcheck
from aq.scoring_v2 import entry_texts

CHECKS = ("novel_specific", "world_negative", "recency_claim", "subject_property")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("results", nargs="+")
    p.add_argument("--out")
    p.add_argument("--show", action="store_true")
    a = p.parse_args()
    cases = {}
    for split in ("dev", "dev2", "dev3", "dev4", "dev5", "dev6", "dev7"):
        try:
            cases.update({c["id"]: c for c in caselib.load_cases(split)})
        except (KeyError, FileNotFoundError):
            pass
    pool = []
    for path in a.results:
        r = json.loads(Path(path).read_text())
        if r["split"] == "holdout":
            raise SystemExit("the consumed holdout is not used")
        for row in r["rows"]:
            if not row["context"].get("text") or row["id"] not in cases:
                continue
            c, sc = cases[row["id"]], row["score"]
            flags = postcheck.run_all(row["reply"], c["question"], entry_texts(row["context"]["text"]))
            bad = bool(sc["forbidden_asserted"]) or bool(sc.get("fabricated") and c["abstain"]) or sc["ungrounded_facts"] > 0
            pool.append({"id": row["id"], "cond": row["condition"], "flags": flags, "bad": bad, "reply": row["reply"], "split": r["split"]})
    out = {"rows": len(pool), "bad": sum(r["bad"] for r in pool), "checks": {}}
    def stats(flagged):
        tp = sum(1 for r in pool if flagged(r) and r["bad"]); fp = sum(1 for r in pool if flagged(r) and not r["bad"]); fn = sum(1 for r in pool if not flagged(r) and r["bad"])
        return {"flagged": tp + fp, "tp": tp, "fp": fp, "fn": fn, "precision": round(tp / (tp + fp), 2) if tp + fp else None, "recall": round(tp / (tp + fn), 2) if tp + fn else None}
    for name in CHECKS:
        out["checks"][name] = stats(lambda r, n=name: bool(r["flags"][n]))
    out["checks"]["any"] = stats(lambda r: any(r["flags"].values()))
    out["checks"]["any_but_subject_property"] = stats(lambda r: any(r["flags"][n] for n in CHECKS if n != "subject_property"))
    print(json.dumps(out, indent=1))
    if a.show:
        for r in pool:
            f = [n for n in CHECKS if r["flags"][n]]
            if f and not r["bad"]:
                print("FP", r["id"], r["cond"], f, r["reply"][:160].replace("\n", " "))
            if r["bad"] and not f:
                print("FN", r["id"], r["cond"], r["reply"][:160].replace("\n", " "))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
