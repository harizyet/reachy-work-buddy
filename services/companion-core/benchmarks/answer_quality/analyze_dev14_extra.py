"""Supplementary tables for the dev14 acceptance run of the revised C1/C2 (reads results/dev14-acceptance-7b.json only): unseen-paraphrase recall, gold retention, C1/C2/C3 contributions, C2 calibration,
paired outcomes by case id, and the timing of the complete path."""
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

run = json.loads((HERE / "results/dev14-acceptance-7b.json").read_text())
cases = {c["id"]: c for c in caselib.load_cases("dev14")}
by = collections.defaultdict(dict)
for r in run["rows"]:
    by[r["condition"]][r["id"]] = r
B, V1, R1, R2, CAND, CAND3 = "b1a", "b1a+c1f+c2n", "b1a+r1q", "b1a+r2", "b1a+r1q+r2", "b1a+r1q+r2+c3"
HELD_REL = {"release_day", "escalation_contact", "storage_limit"}


def full(r):
    return r["score"]["correctness"] == "full"


def gold_present(r, gold):
    refs = [k for e in r["context"]["entries"] for k in e["refs"]]
    return all(any(ref_matches(k, g) for k in refs) for g in gold) if gold else None


print("UNSEEN-PARAPHRASE RECALL (relation recognised as the registry relation; C1 gold retention), design relations only, ESTABLISHED and CONFLICTED questions")
sel = [i for i, c in cases.items() if c["label"] in ("ESTABLISHED", "CONFLICTED") and c["relation"] not in HELD_REL]
for name, ids in (("bank B phrasings 2/3 (unseen) on design relations and design projects", [i for i in sel if cases[i]["bank"] == "B"]), ("all of the above", sel)):
    rec = [i for i in ids if by[CAND][i]["g"].get("relation") == cases[i]["relation"]]
    retained = [i for i in ids if gold_present(by[CAND][i], cases[i]["gold_refs"])]
    base = [i for i in ids if gold_present(by[B][i], cases[i]["gold_refs"])]
    print(f"  {name}: n={len(ids)}; relation recognised {len(rec)}/{len(ids)} = {len(rec) / max(1, len(ids)):.0%}; gold retained by revised C1 {len(retained)}/{len(ids)} vs B1a top 10 {len(base)}/{len(ids)} ({(len(retained) - len(base)) / max(1, len(ids)):+.1%})")
held = [i for i, c in cases.items() if c["relation"] in HELD_REL and c["label"] == "ESTABLISHED"]
print(f"  new held-out relations (generic path), answerable: n={len(held)}; gold retained {sum(bool(gold_present(by[CAND][i], cases[i]['gold_refs'])) for i in held)}/{len(held)} vs B1a {sum(bool(gold_present(by[B][i], cases[i]['gold_refs'])) for i in held)}/{len(held)}; fully correct {sum(full(by[CAND][i]) for i in held)} vs B1a {sum(full(by[B][i]) for i in held)} vs frozen v1 {sum(full(by[V1][i]) for i in held)}")
print("\nPAIRED vs baseline (fully correct), wins / losses / ties; and vs the frozen v1 comparator")
for arm in (V1, R1, R2, CAND, CAND3, "oracle"):
    w = [i for i in by[arm] if full(by[arm][i]) and not full(by[B][i])]
    l = [i for i in by[arm] if full(by[B][i]) and not full(by[arm][i])]
    w1 = [i for i in by[arm] if full(by[arm][i]) and not full(by[V1][i])]
    l1 = [i for i in by[arm] if full(by[V1][i]) and not full(by[arm][i])]
    print(f"  {arm:20} vs B0: {len(w)}/{len(l)}/{len(by[arm]) - len(w) - len(l)} losses {sorted(l)} | vs v1: {len(w1)}/{len(l1)}")
print("\nC2 CALIBRATION on the candidate arm (state vs registry label)")
conf = collections.Counter()
for i, r in by[CAND].items():
    lab = cases[i]["label"]
    conf[(lab, r["g"].get("state"))] += 1
pred = collections.Counter()
gold = collections.Counter()
hit = collections.Counter()
for (lab, st), n in conf.items():
    pred[st] += n
    gold[lab] += n
    if lab == st:
        hit[lab] += n
print("  confusion", dict(sorted(conf.items())))
print("  precision per predicted state", {s: f"{hit[s]}/{pred[s]}" for s in pred}, "| recall per gold label", {s: f"{hit[s]}/{gold[s]}" for s in gold})
un = [i for i, c in cases.items() if c["label"] == "UNESTABLISHED"]
print(f"  UNESTABLISHED labels called UNESTABLISHED {sum(by[CAND][i]['g']['state'] == 'UNESTABLISHED' for i in un)}/{len(un)}; answerable labels wrongly called UNESTABLISHED {sum(r['g']['state'] == 'UNESTABLISHED' for i, r in by[CAND].items() if cases[i]['label'] != 'UNESTABLISHED')}/{sum(c['label'] != 'UNESTABLISHED' for c in cases.values())}")
print("\nTIMING OF THE COMPLETE PATH (ms; medians and p95) per arm: preparation, model call, end to end; stages for the revised arms")
for arm in by:
    rs = list(by[arm].values())
    e2e = sorted(r["timings"]["end_to_end_ms"] for r in rs)
    prep = [r["timings"]["prepare_total_ms"] for r in rs]
    model = [r["timings"]["model_ms"] for r in rs]
    stage = ""
    if "select_ms" in rs[0]["timings"]:
        stage = f" | retrieval30 {statistics.median(r['timings']['retrieval30_ms'] for r in rs):.1f} select {statistics.median(r['timings']['select_ms'] for r in rs):.2f} (p95 {sorted(r['timings']['select_ms'] for r in rs)[int(.95 * len(rs)) - 1]:.1f}) c2 {statistics.median(r['timings']['c2_ms'] for r in rs):.2f} build {statistics.median(r['timings'].get('build_ms', 0) for r in rs):.1f}"
    print(f"  {arm:20} prepare median {statistics.median(prep):6.1f} | model median {statistics.median(model):6.0f} | end-to-end median {statistics.median(e2e):6.0f} p95 {e2e[int(.95 * len(e2e)) - 1]:6.0f}{stage} | prompt tokens {statistics.median(r['cost']['prompt_tokens'] for r in rs):.0f}")
print("\nREGRESSIONS of the candidate against the baseline, with the shown records")
for i in cases:
    b, c = by[B][i], by[CAND][i]
    if full(b) and not full(c):
        print(f"- {i} [{cases[i]['label']}{':' + cases[i]['reason'] if cases[i]['reason'] else ''}] relation={cases[i]['relation']} bank={cases[i]['bank']} gold {gold_present(b, cases[i]['gold_refs'])}->{gold_present(c, cases[i]['gold_refs'])} state={c['g']['state']} | {cases[i]['question']}\n    B: {b['reply'][:120]!r}\n    C: {c['reply'][:160]!r}")
