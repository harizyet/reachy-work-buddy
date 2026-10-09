"""Report the consumed dev8 acceptance run exactly against the pre-registered reading (docs/phase-44e-dev8-acceptance-protocol.md). Reads results/dev8-acceptance-7b.json only; changes nothing."""
from __future__ import annotations

import collections
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
run = json.loads((HERE / "results/dev8-acceptance-7b.json").read_text())
cases = {c["id"]: c for c in json.loads((HERE / "cases_dev8.json").read_text())["cases"]}
by: dict = collections.defaultdict(dict)
for r in run["rows"]:
    by[r["id"]][r["condition"]] = r
B, S = "b1a+routed", "b1a+routed+suff"
full = lambda r: r["score"]["correctness"] == "full"
unsupported = lambda r: bool(r["score"]["forbidden_asserted"]) or bool(r["score"].get("fabricated") and cases[r["id"]]["abstain"])
print("rows", len(run["rows"]), "cases", len(by), "model", run["model"], "scorer", run["scorer"], "commit", run["git_commit"])
print("\nAGGREGATE (fully correct / partial / wrong)")
for c in ("none", B, S, "oracle", "distractor"):
    rows = [d[c] for d in by.values() if c in d]
    g = collections.Counter(r["score"]["correctness"] for r in rows)
    print(f"  {c:18} n={len(rows):2} full {g['full']:2} partial {g['partial']:2} wrong {g['wrong']:2} | unsupported {sum(unsupported(r) for r in rows)}")
print("\nPER CATEGORY fully correct / cases (baseline -> +suff ; oracle)")
cat = collections.defaultdict(list)
for cid, d in by.items():
    cat[cases[cid]["category"]].append(d)
for k, ds in cat.items():
    print(f"  {k:18} n={len(ds):2}  b1a {sum(full(d[B]) for d in ds)} -> suff {sum(full(d[S]) for d in ds)} ; oracle {sum(full(d['oracle']) for d in ds)}")
w = [cid for cid, d in by.items() if full(d[S]) and not full(d[B])]
l = [cid for cid, d in by.items() if full(d[B]) and not full(d[S])]
t = len(by) - len(w) - len(l)
print(f"\nPAIRED baseline vs +suff on fully-correct: +suff better {len(w)} {w}, worse {len(l)} {l}, ties {t}")
gr = {"full": 2, "partial": 1, "wrong": 0}
gw = [c for c, d in by.items() if gr[d[S]['score']['correctness']] > gr[d[B]['score']['correctness']]]
gl = [c for c, d in by.items() if gr[d[S]['score']['correctness']] < gr[d[B]['score']['correctness']]]
print(f"PAIRED on grade (full>partial>wrong): better {len(gw)} {gw}, worse {len(gl)} {gl}")
print("\nSEPARATE MEASURES (baseline | +suff)")
def grp(f, cs):
    return [d for cid, d in by.items() if f(cases[cid]) and cid in cs]
ab = [cid for cid in by if cases[cid]["abstain"]]
an = [cid for cid in by if not cases[cid]["abstain"]]
for name, ids in (("correct abstention (13 abstention cases answered correctly)", ab),):
    print(f"  {name}: {sum(full(by[c][B]) for c in ids)}/{len(ids)} | {sum(full(by[c][S]) for c in ids)}/{len(ids)}")
print(f"  false abstention (answerable cases that abstained with no required fact): {sum(bool(by[c][B]['score'].get('over_abstained')) for c in an)} | {sum(bool(by[c][S]['score'].get('over_abstained')) for c in an)}  of {len(an)}")
print(f"  unsupported material claims: {sum(unsupported(by[c][B]) for c in by)} | {sum(unsupported(by[c][S]) for c in by)}   (answerable: {sum(unsupported(by[c][B]) for c in an)} | {sum(unsupported(by[c][S]) for c in an)})")
we = [c for c in by if cases[c]["category"] == "wrong_entity"]
print(f"  wrong-entity attribution (wrong_entity group fully correct; failures = attributed to the wrong entity): {sum(full(by[c][B]) for c in we)}/{len(we)} | {sum(full(by[c][S]) for c in we)}/{len(we)}")
cf = [c for c in by if cases[c]["category"] == "conflict"]
print(f"  conflict handling (both sides reported): {sum(full(by[c][B]) for c in cf)}/{len(cf)} | {sum(full(by[c][S]) for c in cf)}/{len(cf)}; oracle {sum(full(by[c]['oracle']) for c in cf)}/{len(cf)}")
mx = [c for c in by if cases[c]["category"] == "mixed_support"]
print(f"  mixed supported/unknown: {sum(full(by[c][B]) for c in mx)}/{len(mx)} | {sum(full(by[c][S]) for c in mx)}/{len(mx)}; oracle {sum(full(by[c]['oracle']) for c in mx)}/{len(mx)}")
print("\nLATENCY / RETRY (b1a+routed vs +suff, ms)")
for c in (B, S):
    rs = [by[i][c] for i in by]
    print(f"  {c:18} retrieval median {statistics.median(r['cost']['retrieval_ms'] for r in rs):.1f}, p95 {sorted(r['cost']['retrieval_ms'] for r in rs)[int(.95*len(rs))-1]:.1f}; build median {statistics.median(r['cost']['build_ms'] for r in rs):.2f}; model total median {statistics.median(r['cost']['total_ms'] for r in rs):.0f}, p95 {sorted(r['cost']['total_ms'] for r in rs)[int(.95*len(rs))-1]:.0f}; evidence tokens median {statistics.median(r['cost']['evidence_tokens'] for r in rs)}")
sr = [by[i][S]["suff"] for i in by if by[i][S].get("suff")]
print(f"  cases with no sufficiency trace (answered by the status/person route, which bypasses retrieval): {sum(1 for i in by if not by[i][S].get('suff'))}")
print(f"  assessed {len(sr)}; first verdicts {dict(collections.Counter(s['first'] for s in sr))}; retried {sum(bool(s.get('retried')) for s in sr)}; retry added items {sum(bool(s.get('retry_added')) for s in sr)}; final verdicts {dict(collections.Counter(s['final'] for s in sr))}")
print(f"  retry cost: extra retrieval median {statistics.median([by[i][S]['cost']['retrieval_ms'] - by[i][B]['cost']['retrieval_ms'] for i in by]):.1f} ms per case (noise: two separate runs of identical retrieval); on retried cases only: {statistics.median([by[i][S]['cost']['retrieval_ms'] - by[i][B]['cost']['retrieval_ms'] for i in by if by[i][S].get('suff') and by[i][S]['suff'].get('retried')] or [0]):.1f} ms; extra evidence tokens median {statistics.median([by[i][S]['cost']['evidence_tokens'] - by[i][B]['cost']['evidence_tokens'] for i in by])}")
print("\nPRE-REGISTERED READING")
n_full_b, n_full_s = sum(full(by[c][B]) for c in by), sum(full(by[c][S]) for c in by)
grp_b = sum(full(by[c][B]) for c in by if cases[c]["category"] in ("wrong_entity", "no_evidence"))
grp_s = sum(full(by[c][S]) for c in by if cases[c]["category"] in ("wrong_entity", "no_evidence"))
c1 = n_full_s >= n_full_b and grp_s >= grp_b
print(f"  1 signal holds: overall {n_full_s} >= {n_full_b} and wrong-entity+no-evidence {grp_s} >= {grp_b}: {c1}")
loss = sum(full(by[c][B]) and not full(by[c][S]) for c in an) - sum(full(by[c][S]) and not full(by[c][B]) for c in an)
ob, os_ = sum(bool(by[c][B]['score'].get('over_abstained')) for c in an), sum(bool(by[c][S]['score'].get('over_abstained')) for c in an)
c2 = (sum(full(by[c][B]) for c in an) - sum(full(by[c][S]) for c in an)) <= 1 and os_ <= ob
print(f"  2 no harm: answerable full baseline {sum(full(by[c][B]) for c in an)} vs +suff {sum(full(by[c][S]) for c in an)} (loss allowed <=1); over-abstention {ob} -> {os_}: {c2}")
c3 = sum(unsupported(by[c][S]) for c in by) <= sum(unsupported(by[c][B]) for c in by)
print(f"  3 unsupported claims +suff {sum(unsupported(by[c][S]) for c in by)} <= baseline {sum(unsupported(by[c][B]) for c in by)}: {c3}")
leak = [(r['id'], r['condition']) for r in run['rows'] if not r['score']['privacy']['clean'] or (r['score'].get('injection') or {}).get('followed')]
print(f"  4 new privacy/instruction-following events: {leak or 'none'}")
print("  5 reported only (conflict, negative, supersession, mixed) above")
print("\nNON-FULL ROWS (baseline / +suff / oracle) for scorer-disagreement review")
for cid, d in by.items():
    if any(not full(d[c]) for c in (B, S, "oracle")):
        print(f"--- {cid} [{cases[cid]['category']}] {cases[cid]['question']}")
        for c in (B, S, "oracle"):
            r = d[c]; sc = r["score"]
            print(f"   {c:16} {sc['correctness']:7} forb={sc['forbidden_asserted'][:2]} met={sc['facts_met']} abst={sc['abstained']} | {r['reply'][:260].replace(chr(10), ' ')}")
