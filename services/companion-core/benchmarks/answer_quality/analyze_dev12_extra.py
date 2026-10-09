"""Supplementary tables for the consumed dev12 run (reads results/dev12-acceptance-7b.json only): C1 effect case by case, C2 false positives and negatives, the oracle arm's citation, scorer review,
latency and resource overhead."""
from __future__ import annotations

import collections
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib
from aq.scoring import ref_matches

run = json.loads((HERE / "results/dev12-acceptance-7b.json").read_text())
cases = {c["id"]: c for c in caselib.load_cases("dev12")}
by = collections.defaultdict(dict)
for r in run["rows"]:
    by[r["condition"]][r["id"]] = r
B, C1, N, C12 = "b1a", "b1a+c1f", "b1a+c2n", "b1a+c1f+c2n"


def full(r):
    return r["score"]["correctness"] == "full"


def unsup(r):
    return bool(r["score"]["forbidden_asserted"]) or bool(r["score"].get("fabricated") and cases[r["id"]]["abstain"])


def gold_present(r, gold):
    refs = [k for e in r["context"]["entries"] for k in e["refs"]]
    return all(any(ref_matches(k, g) for k in refs) for g in gold) if gold else None


def nongold(r, gold):
    refs = [k for e in r["context"]["entries"] for k in e["refs"]]
    return sum(1 for k in refs if not any(ref_matches(k, g) for g in gold))


print("C1 FILTER vs BASELINE, case by case")
improved, regressed, goldlost = [], [], []
for i, c in cases.items():
    b, f = by[B][i], by[C1][i]
    gp_b, gp_f = gold_present(b, c["gold_refs"]), gold_present(f, c["gold_refs"])
    if gp_b and gp_f is False:
        goldlost.append(i)
    if full(f) and not full(b):
        improved.append(i)
    if full(b) and not full(f):
        regressed.append(i)
print(f"  records shown: B {statistics.mean(r['cost']['shown'] for r in by[B].values()):.1f} -> C1 {statistics.mean(r['cost']['shown'] for r in by[C1].values()):.1f}; non-gold shown: {statistics.mean(nongold(by[B][i], c['gold_refs']) for i, c in cases.items()):.1f} -> {statistics.mean(nongold(by[C1][i], c['gold_refs']) for i, c in cases.items()):.1f}")
print(f"  improved {len(improved)}, regressed {len(regressed)}, gold evidence removed by C1 in {len(goldlost)} cases {goldlost}")
for i in improved:
    c = cases[i]
    print(f"  + {i} {c['label']}{':' + c['reason'] if c['reason'] else ''} | non-gold {nongold(by[B][i], c['gold_refs'])}->{nongold(by[C1][i], c['gold_refs'])}, shown {by[B][i]['cost']['shown']}->{by[C1][i]['cost']['shown']} | {c['question']}")
for i in regressed:
    c = cases[i]
    print(f"  - {i} {c['label']}{':' + c['reason'] if c['reason'] else ''} | gold present {gold_present(by[B][i], c['gold_refs'])}->{gold_present(by[C1][i], c['gold_refs'])} | {c['question']}\n       B : {by[B][i]['reply'][:140]!r}\n       C1: {by[C1][i]['reply'][:140]!r}")
print("\nC1 gold removed (any case where baseline shows all gold and C1 does not):", goldlost)
print("\nC2 ANSWERABILITY DECISIONS (state computed on the C2-note arm; the generator plays no part)")
rows = by[N]
want = {"ESTABLISHED": "ESTABLISHED", "CONFLICTED": "CONFLICTED", "PARTIAL": "PARTIAL", "UNESTABLISHED": "UNESTABLISHED"}
fp = [i for i, r in rows.items() if cases[i]["label"] != "UNESTABLISHED" and r["g"]["state"] == "UNESTABLISHED"]
fn = [i for i, r in rows.items() if cases[i]["label"] == "UNESTABLISHED" and r["g"]["state"] != "UNESTABLISHED"]
print(f"  false UNESTABLISHED (would wrongly withhold an answerable question): {len(fp)} of {sum(c['label'] != 'UNESTABLISHED' for c in cases.values())} answerable-labelled: {collections.Counter(cases[i]['label'] for i in fp)}")
print(f"  missed UNESTABLISHED (state says ESTABLISHED/CONFLICTED/PARTIAL for an unanswerable question): {len(fn)} of {sum(c['label'] == 'UNESTABLISHED' for c in cases.values())}: by relation {collections.Counter(cases[i]['relation'] for i in fn)}; held-out relation share {sum(cases[i]['relation'] in ('on_call', 'budget_through', 'deadline') for i in fn)}/{len(fn)}")
print(f"  fp by relation {collections.Counter(cases[i]['relation'] for i in fp)}")
print("  did the note change answers where C2 was wrong? answerable false-UNESTABLISHED: fully correct with note vs baseline:", sum(full(by[N][i]) for i in fp), "vs", sum(full(by[B][i]) for i in fp), f"(n={len(fp)})")
print("  missed unanswerable: unsupported with note vs baseline:", sum(unsup(by[N][i]) for i in fn), "vs", sum(unsup(by[B][i]) for i in fn))
print("\nORACLE ARM CITATION OUTSIDE THE CANDIDATES (reported; guardrail 5 applies to candidate arms)")
for i, r in by["oracle"].items():
    ci = r["g"]["citations"]
    if ci["nonexistent"] or ci["unauthorized"]:
        print("  ", i, ci, "|", r["reply"][:160])
print("\nLATENCY AND RESOURCES (ms / tokens)")
for arm in by:
    rs = list(by[arm].values())
    t = sorted(r["cost"]["total_ms"] for r in rs)
    print(f"  {arm:24} model call median {statistics.median(t):6.0f} p95 {t[int(.95 * len(t)) - 1]:6.0f} | retrieval median {statistics.median(r['cost']['retrieval_ms'] for r in rs):5.1f} | prompt tokens median {statistics.median(r['cost']['prompt_tokens'] for r in rs):5.0f} completion {statistics.median(r['cost']['completion_tokens'] for r in rs):4.0f} | model calls skipped {sum(r['cost']['finish'] == 'fixed' for r in rs)}")
print("\nSCORER REVIEW: non-full replies of the C1+C2 candidate (automatic score unmodified)")
for i, c in cases.items():
    r = by[C12][i]
    if not full(r):
        print(f"- {i} [{c['label']}{':' + c['reason'] if c['reason'] else ''}] {r['score']['correctness']} forb={r['score']['forbidden_asserted'][:1]} facts_met={r['score']['facts_met']} | {c['question']}\n    {r['reply'][:230]!r}")
