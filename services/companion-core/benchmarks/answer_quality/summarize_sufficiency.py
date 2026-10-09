"""Tables for the evidence-sufficiency record: per-condition and per-category correctness on the fresh sets (dev6, dev7), the over-abstention regression on the older development splits, and the
retry statistics. Reads stored result files only; runs no model.

    python summarize_sufficiency.py > results/sufficiency-summary.txt"""
from __future__ import annotations

import collections
import json
from math import comb
from pathlib import Path

R = Path(__file__).resolve().parent / "results"
CONDS = ("none", "b1a+routed", "b1a+routed+suff", "b1a+routed+gate", "b1a+routed+suff+cf", "oracle", "distractor")


def load(*names):
    rows = []
    for n in names:
        rows += json.loads((R / n).read_text())["rows"]
    return rows


def table(rows, label):
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[r["condition"]][r["score"]["correctness"]] += 1
    print(f"\n{label}")
    for c in CONDS:
        if c in by:
            v = by[c]; n = sum(v.values())
            print(f"  {c:22} full {v['full']:3}/{n:<3} partial {v['partial']:2} wrong {v['wrong']:2}")


def categories(rows, label):
    cat = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in rows:
        cat[r["category"]][r["condition"]][r["score"]["correctness"] == "full"] += 1
    print(f"\n{label}: fully correct / cases, by category")
    for c, d in sorted(cat.items()):
        cells = []
        for k in ("b1a+routed", "b1a+routed+suff", "oracle"):
            if k in d:
                cells.append(f"{k.replace('b1a+routed', 'b1a'):10} {d[k][True]}/{d[k][True] + d[k][False]}")
        print(f"  {c:18} " + "   ".join(cells))


def paired(rows, a, b):
    by = collections.defaultdict(dict)
    for r in rows:
        by[(r["id"])][r["condition"]] = r["score"]["correctness"] == "full"
    w = sum(1 for d in by.values() if a in d and b in d and d[b] and not d[a])
    l = sum(1 for d in by.values() if a in d and b in d and d[a] and not d[b])
    n = w + l
    p = min(1.0, 2 * sum(comb(n, k) for k in range(min(w, l) + 1)) / 2 ** n) if n else 1.0
    return w, l, round(p, 4)


fresh6, fresh7 = load("dev6-7b-suff.json"), load("dev7-7b.json")
table(fresh6, "dev6 (32 cases; written before the mechanism, failures seen before it was built)")
table(fresh7, "dev7 (21 cases; written after the mechanism was frozen: evaluated once)")
fresh = fresh6 + fresh7
categories(fresh, "dev6 + dev7")
w, l, p = paired(fresh, "b1a+routed", "b1a+routed+suff")
print(f"\npaired, fresh sets, b1a+routed -> +suff: better {w}, worse {l}, two-sided sign p {p}")
w, l, p = paired(fresh7, "b1a+routed", "b1a+routed+suff")
print(f"paired, dev7 only:                      better {w}, worse {l}, two-sided sign p {p}")
old = []
for s in ("dev", "dev2", "dev3", "dev4", "dev5"):
    old += load(f"suffreg-{s}.json")
table(old, "older development splits dev..dev5 (113 cases; regression: did the note cost answerable cases?)")
ws, ls, ps = paired(old, "b1a+routed", "b1a+routed+suff")
wg, lg, pg = paired(old, "b1a+routed", "b1a+routed+gate")
print(f"\nolder splits, b1a+routed -> +suff: better {ws}, worse {ls}, p {ps}; -> +gate: better {wg}, worse {lg}, p {pg}")
over = collections.Counter(r["condition"] for r in old if r["score"].get("over_abstained"))
print("over-abstained (older splits):", dict(over))
retry = collections.Counter()
for r in fresh + old:
    s = r.get("suff")
    if s and r["condition"] == "b1a+routed+suff":
        retry["assessed"] += 1
        retry["insufficient_first"] += s["first"] != "sufficient"
        retry["retried"] += bool(s.get("retried"))
        retry["retry_added_items"] += bool(s.get("retry_added"))
        retry["still_insufficient_after_retry"] += bool(s.get("retried")) and s["final"] != "sufficient"
print("\nretry (b1a+routed+suff rows):", dict(retry))
