"""Tables for a groundedness ablation run (corpus v2): per arm correctness, unsupported material claims, false abstention, the owner's acceptance guardrails, paired outcomes against the baseline, claim-level
validation statistics and latency. Reads a results file only.

    python analyze_g.py results/dev11-ablation-7b.json [--baseline b1a]"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib

ap = argparse.ArgumentParser()
ap.add_argument("run")
ap.add_argument("--baseline", default="b1a")
ap.add_argument("--list", action="store_true")
a = ap.parse_args()
run = json.loads(Path(a.run).read_text())
cases = {c["id"]: c for c in caselib.load_cases(run["split"])}
by: dict = collections.defaultdict(dict)
for r in run["rows"]:
    by[r["condition"]][r["id"]] = r
arms = list(by)


def unsupported(r):
    return bool(r["score"]["forbidden_asserted"]) or bool(r["score"].get("fabricated") and cases[r["id"]]["abstain"])


def full(r):
    return r["score"]["correctness"] == "full"


def false_abstain(r):
    return (not cases[r["id"]]["abstain"]) and bool(r["score"].get("over_abstained"))


def specific(r):
    """A correction that is not a blanket refusal: an answerable case that now states a required fact, or an unanswerable case whose reply is not a fixed template and says something specific."""
    c = cases[r["id"]]
    if r["cost"]["finish"] == "fixed":
        return False
    if not c["abstain"]:
        return any(r["score"]["facts_met"])
    return len(r["reply"].split()) >= 12


ans = [i for i, c in cases.items() if not c["abstain"]]
print(f"{run['split']}: {len(cases)} cases, {len(ans)} answerable; arms {len(arms)}; model {run['model']}\n")
hdr = f"{'arm':36} {'full':>5} {'unsup':>5} {'falseAbs':>8} {'ansFull':>7} {'corrAbs':>7} {'better':>6} {'worse':>5} {'regress':>7} {'corrected':>9} {'citBad':>6} {'ms med':>7}"
print(hdr)
base = by[a.baseline]
for arm in arms:
    rs = by[arm]
    f = sum(full(r) for r in rs.values())
    u = sum(unsupported(r) for r in rs.values())
    fa = sum(false_abstain(r) for r in rs.values())
    af = sum(full(rs[i]) for i in ans)
    ca = sum(full(rs[i]) for i, c in cases.items() if c["abstain"])
    better = [i for i in rs if full(rs[i]) and not full(base[i])]
    worse = [i for i in rs if full(base[i]) and not full(rs[i])]
    corrected = [i for i in rs if unsupported(base[i]) and not unsupported(rs[i]) and specific(rs[i])]
    cit = sum(len(r["g"]["citations"]["nonexistent"]) + len(r["g"]["citations"]["unauthorized"]) + r["g"].get("accepted_invalid", 0) for r in rs.values())
    ms = statistics.median(r["cost"]["total_ms"] for r in rs.values())
    print(f"{arm:36} {f:5} {u:5} {fa:8} {af:7} {ca:7} {len(better):6} {len(worse):5} {len(worse):7} {len(corrected):9} {cit:6} {ms:7.0f}")
print("\nGUARDRAILS (candidate arms vs baseline; owner-fixed 2026-10-12)")
bu = sum(unsupported(r) for r in base.values())
bfa = sum(false_abstain(r) for r in base.values())
baf = sum(full(base[i]) for i in ans)
for arm in arms:
    if arm == a.baseline or arm.startswith("oracle"):
        continue
    rs = by[arm]
    u = sum(unsupported(r) for r in rs.values())
    fa = sum(false_abstain(r) for r in rs.values())
    af = sum(full(rs[i]) for i in ans)
    net_loss = baf - af
    corrected = [i for i in rs if unsupported(base[i]) and not unsupported(rs[i]) and specific(rs[i])]
    cit = sum(len(r["g"]["citations"]["nonexistent"]) + len(r["g"]["citations"]["unauthorized"]) + r["g"].get("accepted_invalid", 0) for r in rs.values())
    g1, g2, g3, g4, g5 = u < bu, (fa - bfa) <= 1 and ((fa - bfa) / len(ans)) <= 0.03, net_loss <= 1, len(corrected) >= 1, cit == 0
    print(f"{arm:36} 1 fewer unsupported {u}<{bu}: {g1!s:5} | 2 false abstention +{fa - bfa} ({(fa - bfa) / len(ans):+.1%}): {g2!s:5} | 3 answerable net loss {net_loss}: {g3!s:5} | 4 specific corrections {len(corrected)}: {g4!s:5} | 5 bad citations {cit}: {g5!s:5} | ALL {all([g1, g2, g3, g4, g5])}")
print("\nBY LABEL (fully correct / n) baseline | arms")
lab = collections.defaultdict(list)
for i, c in cases.items():
    lab[c["label"] + (":" + c["reason"] if c["reason"] else "")].append(i)
for l, ids in lab.items():
    print(f"  {l:28} n={len(ids):2} " + " | ".join(f"{arm.replace('b1a', 'B'):>20} {sum(full(by[arm][i]) for i in ids)}" for arm in arms if arm in ("b1a", "b1a+c1f+c2t", "b1a+c4+c5", "b1a+c1f+c2t+c3+c4+c5", "oracle")))
print("\nCLAIM-LEVEL (c4 arms)")
for arm in arms:
    if "c4" in arm:
        rows = list(by[arm].values())
        rej = collections.Counter(x for r in rows for x in r["g"].get("rejections", []))
        print(f"  {arm:36} parse_ok {sum(r['g'].get('parse_ok', False) for r in rows)}/{len(rows)}; claims {sum(r['g'].get('claims', 0) for r in rows)}; valid {sum(r['g'].get('valid_claims', 0) for r in rows)}; rejections {dict(rej)}; accepted invalid {sum(r['g'].get('accepted_invalid', 0) for r in rows)}")
print("\nC2 STATE vs LABEL on arms that computed it")
for arm in ("b1a+c2n", "b1a+c1f+c2t"):
    if arm in by:
        conf = collections.Counter((cases[i]["label"] + (":" + cases[i]["reason"] if cases[i]["reason"] else ""), r["g"].get("state")) for i, r in by[arm].items())
        print(" ", arm, dict(sorted(conf.items())))
if a.list:
    for arm in arms:
        if arm in ("b1a+c1f+c2t+c3+c4+c5", "b1a+c4+c5"):
            for i in cases:
                r, b = by[arm][i], base[i]
                if full(b) != full(r) or unsupported(b) != unsupported(r):
                    print(f"\n[{arm}] {i} {cases[i]['label']} base={b['score']['correctness']}/{unsupported(b)} arm={r['score']['correctness']}/{unsupported(r)}\n  Q: {cases[i]['question']}\n  base: {b['reply'][:200]!r}\n  arm : {r['reply'][:260]!r}")
