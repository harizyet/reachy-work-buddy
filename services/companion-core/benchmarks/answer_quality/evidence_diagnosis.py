"""Descriptive, no-model diagnosis of the evidence B1a hands the model, on the DEVELOPMENT sets dev6 and dev7 only (never dev8, dev10 or the holdout): for each case, were the gold sources among the
evidence items (recall), and how many non-gold items came with them (precision)? Motivation for the groundedness design (docs/phase-44-groundedness-milestone-design.md)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib
from aq.scoring import ref_matches

rows = []
for f, split in (("results/dev6-7b-suff.json", "dev6"), ("results/dev7-7b.json", "dev7")):
    cs = {c["id"]: c for c in caselib.load_cases(split)}
    for r in json.loads((HERE / f).read_text())["rows"]:
        if r["condition"] != "b1a+routed":
            continue
        c = cs[r["id"]]
        refs = [k for e in r["context"]["entries"] for k in e["refs"]]
        gold = c["gold_refs"]
        have = [any(ref_matches(k, g) for k in refs) for g in gold]
        extra = [k for k in refs if not any(ref_matches(k, g) for g in gold)]
        rows.append({"id": r["id"], "abstain": c["abstain"], "ok": r["score"]["correctness"] == "full", "gold": len(gold), "recall": sum(have), "n": len(refs), "extra": len(extra)})


def summ(sub, label):
    n = max(1, len(sub))
    print(f"{label:34} n={len(sub):2} mean items {sum(r['n'] for r in sub) / n:.1f}, mean non-gold items {sum(r['extra'] for r in sub) / n:.1f}, all gold present {sum(r['recall'] == r['gold'] for r in sub if r['gold'])}/{sum(1 for r in sub if r['gold'])}")


ans = [r for r in rows if not r["abstain"]]
ab = [r for r in rows if r["abstain"]]
summ([r for r in ans if r["ok"]], "answerable, fully correct")
summ([r for r in ans if not r["ok"]], "answerable, not correct")
summ([r for r in ab if r["ok"]], "abstention, correct")
summ([r for r in ab if not r["ok"]], "abstention, invented an answer")
fails = [r for r in ans if not r["ok"]]
print("answerable failures with gold missing from the evidence:", sum(r["recall"] < r["gold"] for r in fails), "of", len(fails))
