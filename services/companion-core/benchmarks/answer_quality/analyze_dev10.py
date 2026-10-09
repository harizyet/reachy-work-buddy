"""Report the consumed dev10 comparison against docs/phase-44e-section-coverage-protocol.md. Reads results/dev10-section-7b.json only."""
from __future__ import annotations

import collections
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
run = json.loads((HERE / "results/dev10-section-7b.json").read_text())
cases = {c["id"]: c for c in json.loads((HERE / "cases_dev10.json").read_text())["cases"]}
by: dict = collections.defaultdict(dict)
for r in run["rows"]:
    by[r["id"]][r["condition"]] = r
A, B, C, D = "b1a+routed", "b1a+routed+suff", "b1a+routed+sec", "b1a+routed+secd"
ARMS = {"A baseline": A, "B existing coverage": B, "C section-level": C, "D section+descriptors": D}


def full(r):
    return r["score"]["correctness"] == "full"


def unsupported(r):
    return bool(r["score"]["forbidden_asserted"]) or bool(r["score"].get("fabricated") and cases[r["id"]]["abstain"])


answerable = [c for c in by if not cases[c]["abstain"]]
abstain = [c for c in by if cases[c]["abstain"]]
print("rows", len(run["rows"]), "cases", len(by), "answerable", len(answerable), "abstention", len(abstain), "commit", run["git_commit"])
print("\nAGGREGATE")
for label, c in [*ARMS.items(), ("oracle", "oracle"), ("distractor", "distractor")]:
    rows = [d[c] for d in by.values() if c in d]
    g = collections.Counter(r["score"]["correctness"] for r in rows)
    fa = sum(bool(by[i][c]["score"].get("over_abstained")) for i in answerable if c in by[i])
    print(f"  {label:24} n={len(rows):2} full {g['full']:2} partial {g['partial']} wrong {g['wrong']:2} | UNSUPPORTED {sum(unsupported(r) for r in rows):2} | false abstention {fa} | abstention cases correct {sum(full(by[i][c]) for i in abstain if c in by[i])}/{len(abstain)}")
print("\nPER CATEGORY fully correct / unsupported (A | B | C | D ; oracle)")
cat = collections.defaultdict(list)
for cid in by:
    cat[cases[cid]["category"]].append(cid)
for k, ids in cat.items():
    f = " | ".join(f"{sum(full(by[i][c]) for i in ids)}/{sum(unsupported(by[i][c]) for i in ids)}" for c in (A, B, C, D))
    print(f"  {k:16} n={len(ids):2}  {f} ; oracle {sum(full(by[i]['oracle']) for i in ids)}")


def pair(x, y):
    w = [i for i in by if full(by[i][y]) and not full(by[i][x])]
    l = [i for i in by if full(by[i][x]) and not full(by[i][y])]
    return w, l


print("\nPAIRED on fully correct (second arm better / worse / ties)")
for x, y, name in ((A, B, "B vs A"), (A, C, "C vs A"), (A, D, "D vs A"), (B, C, "C vs B"), (B, D, "D vs B")):
    w, l = pair(x, y)
    print(f"  {name}: better {len(w)} {w}, worse {len(l)} {l}, ties {len(by) - len(w) - len(l)}")
print("\nPAIRED on unsupported claims (second arm fewer / more)")
for x, y, name in ((A, B, "B vs A"), (A, C, "C vs A"), (A, D, "D vs A"), (B, C, "C vs B")):
    fewer = [i for i in by if unsupported(by[i][x]) and not unsupported(by[i][y])]
    more = [i for i in by if unsupported(by[i][y]) and not unsupported(by[i][x])]
    print(f"  {name}: fewer {len(fewer)} {fewer}, more {len(more)} {more}")
print("\nVERDICTS (first assessment, per question)")
for label, c in ((B, B), (C, C), (D, D)):
    tr = [by[i][c].get("suff") for i in by if by[i][c].get("suff")]
    print(f"  {label:20} assessed {len(tr)}: {dict(collections.Counter(t['first'] for t in tr))}; retried {sum(bool(t.get('retried')) for t in tr)}; retry added items {sum(bool(t.get('retry_added')) for t in tr)}; final changed {sum(t['final'] != t['first'] for t in tr)}")
agree = [i for i in by if by[i][C].get("suff") and by[i][C]["suff"]["first"] == by[i][C]["suff"]["item_level"]]
tot = [i for i in by if by[i][C].get("suff")]
print(f"  verdict agreement C vs B (section vs item level): {len(agree)}/{len(tot)} = {len(agree) / len(tot):.0%}; differing: {[(i, by[i][C]['suff']['item_level'], by[i][C]['suff']['first']) for i in tot if i not in agree]}")
for label, c in ((B, B), (C, C), (D, D)):
    noted = [i for i in answerable if by[i][c].get("suff") and by[i][c]["suff"]["final"] != "sufficient"]
    print(f"  answerable questions given a coverage note, {label}: {len(noted)}/{len(answerable)} {noted}")
nonote_same = sum(1 for i in by if by[i][B]["context"]["text"] == by[i][A]["context"]["text"])
print(f"  prompt identity: B's evidence message equals A's on {nonote_same}/{len(by)} cases; C equals B on {sum(1 for i in by if by[i][C]['context']['text'] == by[i][B]['context']['text'])}/{len(by)}; D equals B on {sum(1 for i in by if by[i][D]['context']['text'] == by[i][B]['context']['text'])}/{len(by)}")
print("\nLATENCY (ms): model total median/p95 | retrieval median | retried | evidence tokens median")
for label, c in ARMS.items():
    rs = [by[i][c] for i in by]
    t = sorted(r["cost"]["total_ms"] for r in rs)
    print(f"  {label:24} {statistics.median(t):.0f}/{t[int(.95 * len(t)) - 1]:.0f} | {statistics.median(r['cost']['retrieval_ms'] for r in rs):.1f} | {sum(bool((r.get('suff') or {}).get('retried')) for r in rs)} | {statistics.median(r['cost']['evidence_tokens'] for r in rs)}")
print("\nPRE-REGISTERED READING")
uA, uB, uC, uD = (sum(unsupported(by[i][c]) for i in by) for c in (A, B, C, D))
fA, fB, fC, fD = (sum(full(by[i][c]) for i in by) for c in (A, B, C, D))
faA, faB, faC, faD = (sum(bool(by[i][c]["score"].get("over_abstained")) for i in answerable) for c in (A, B, C, D))
leak = [(r["id"], r["condition"]) for r in run["rows"] if not r["score"]["privacy"]["clean"] or (r["score"].get("injection") or {}).get("followed")]
for name, u, f, fa in (("C", uC, fC, faC), ("D (exploratory)", uD, fD, faD)):
    ok = u <= uA and f >= fA and fa <= faA and not leak
    print(f"  1. {name} acceptable vs baseline: unsupported {u} <= {uA}, fully correct {f} >= {fA}, false abstention {fa} <= {faA}, privacy/instruction events {leak or 'none'} -> {ok}")
w, l = pair(B, C)
print(f"  2. C distinguishable from B: unsupported C {uC} <= B {uB} - 2: {uC <= uB - 2}; or paired wins>=3 & losses==0: {len(w) >= 3 and not l} (wins {len(w)}, losses {len(l)}) -> {(uC <= uB - 2) or (len(w) >= 3 and not l)}")
print(f"  4. verdict agreement >= 90%: {len(agree) / len(tot):.0%} -> {len(agree) / len(tot) >= 0.9}")
print("\nNON-FULL ROWS FOR SCORER REVIEW (A / B / C / D / oracle)")
for cid, d in by.items():
    if any(not full(d[c]) for c in (A, B, C, D, "oracle")):
        print(f"--- {cid} [{cases[cid]['category']}] {cases[cid]['question']}")
        seen = {}
        for c in (A, B, C, D, "oracle"):
            r = d[c]; sc = r["score"]
            key = r["reply"]
            tag = f"(same reply as {seen[key]})" if key in seen else r["reply"][:240].replace("\n", " ")
            seen.setdefault(key, c)
            print(f"   {c.replace('b1a+routed', 'b1a'):12} {sc['correctness']:7} forb={sc['forbidden_asserted'][:2]} abst={sc['abstained']} | {tag}")
