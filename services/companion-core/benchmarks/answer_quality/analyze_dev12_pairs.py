"""Paired outcomes by case id, per-label results for every arm, and the scorer-annotation of the generic no-record forbidden pattern (reads the consumed dev12 results only)."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib

run = json.loads((HERE / "results/dev12-acceptance-7b.json").read_text())
cases = {c["id"]: c for c in caselib.load_cases("dev12")}
by = collections.defaultdict(dict)
for r in run["rows"]:
    by[r["condition"]][r["id"]] = r
B = "b1a"
full = lambda r: r["score"]["correctness"] == "full"
GENERIC = "signs off|reviewer|approves"


def unsup(r):
    return bool(r["score"]["forbidden_asserted"]) or bool(r["score"].get("fabricated") and cases[r["id"]]["abstain"])


def unsup_annotated(r):
    """Same, but a forbidden hit that is ONLY the generic no-record pattern ('signs off|reviewer|approves') inside a reply that abstains is a question echo, not a claim."""
    forb = [p for p in r["score"]["forbidden_asserted"] if p != GENERIC]
    return bool(forb) or bool(r["score"].get("fabricated") and cases[r["id"]]["abstain"]) or (GENERIC in r["score"]["forbidden_asserted"] and not r["score"]["abstained"])


labels = collections.defaultdict(list)
for i, c in cases.items():
    labels[c["label"] + (":" + c["reason"] if c["reason"] else "")].append(i)
print("PER LABEL, fully correct / n")
print(f"{'arm':26}" + "".join(f"{l[:14]:>16}" for l in labels))
for arm, rs in by.items():
    print(f"{arm:26}" + "".join(f"{sum(full(rs[i]) for i in ids):>13}/{len(ids):<2}" for ids in labels.values()))
print("\nPAIRED vs baseline (fully correct): wins / losses / ties")
for arm, rs in by.items():
    if arm == B:
        continue
    w = [i for i in rs if full(rs[i]) and not full(by[B][i])]
    l = [i for i in rs if full(by[B][i]) and not full(rs[i])]
    print(f"  {arm:26} {len(w):2} / {len(l):2} / {len(rs) - len(w) - len(l):2}   losses: {sorted(l)}")
print("\nPAIRED on unsupported claims vs baseline: fewer / more")
for arm, rs in by.items():
    if arm == B:
        continue
    f = [i for i in rs if unsup(by[B][i]) and not unsup(rs[i])]
    m = [i for i in rs if unsup(rs[i]) and not unsup(by[B][i])]
    print(f"  {arm:26} fewer {len(f):2}  more {len(m):2}   more: {sorted(m)}")
print("\nSCORER ANNOTATION: unsupported claims, automatic vs excluding question-echo hits of the generic no-record pattern in abstaining replies")
for arm, rs in by.items():
    print(f"  {arm:26} automatic {sum(unsup(r) for r in rs.values()):2}  annotated {sum(unsup_annotated(r) for r in rs.values()):2}  (echo hits {sum(unsup(r) and not unsup_annotated(r) for r in rs.values())})")
