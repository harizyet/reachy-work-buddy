"""Compare two models on IDENTICAL stored prompts (the 7B's stored replies against a replay of the same rows on a larger model). Reads result files only.

    python compare_models.py --pair results/dev6-7b-suff.json results/dev6-replay-14b.json --pair results/dev7-7b.json results/dev7-replay-14b.json ... --out results/larger-model-comparison.json

Per condition and per failure group: fully correct, unsupported claims (a forbidden assertion or a fabrication), abstention, instruction contamination, latency and tokens."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib

GROUPS = {
    "no_evidence": "correct abstention (no support)", "wrong_entity": "evidence about the wrong entity", "partial_evidence": "partially supporting evidence",
    "conflict": "conflicting evidence", "supersession": "invented supersession / temporal", "attribution": "actor / assignee attribution",
    "negative_claim": "negative claims", "injection": "retrieved instruction contamination",
}


def sign_p(w: int, l: int) -> float:
    n = w + l
    return round(min(1.0, 2 * sum(comb(n, k) for k in range(min(w, l) + 1)) / 2 ** n), 4) if n else 1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", nargs=2, action="append", required=True, metavar=("BASE", "OTHER"))
    ap.add_argument("--patch", action="append", default=[], help="replay files whose rows replace the same (case, condition) rows of the larger model's replays (a corrected re-run)")
    ap.add_argument("--out")
    a = ap.parse_args()
    cases = {}
    for split in ("dev6", "dev7"):
        cases.update({c["id"]: c for c in caselib.load_cases(split)})
    patches = {}
    for path in a.patch:
        for r in json.loads((HERE / path).read_text())["rows"]:
            patches[(r["id"], r["condition"])] = r
    joined = []
    for base_path, other_path in a.pair:
        base = {(r["id"], r["condition"]): r for r in json.loads((HERE / base_path).read_text())["rows"]}
        for r in json.loads((HERE / other_path).read_text())["rows"]:
            b = base.get((r["id"], r["condition"]))
            if b is None:
                continue
            r = patches.get((r["id"], r["condition"]), r)
            joined.append({"id": r["id"], "cond": r["condition"], "cat": cases[r["id"]]["category"], "abstain": cases[r["id"]]["abstain"], "base": b, "other": r})
    # one row per (case, condition) even if a pair repeats it
    seen, rows = set(), []
    for j in joined:
        k = (j["id"], j["cond"])
        if k not in seen:
            seen.add(k)
            rows.append(j)
    out: dict = {"rows": len(rows), "patched_rows": len([1 for j in rows if (j["id"], j["cond"]) in patches]), "by_condition": {}, "by_group": {}, "latency": {}}

    def stat(subset, which):
        n = len(subset)
        sc = [r[which]["score"] for r in subset]
        return {"n": n, "full": sum(s["correctness"] == "full" for s in sc), "wrong": sum(s["correctness"] == "wrong" for s in sc),
                "unsupported_claims": sum(bool(s["forbidden_asserted"]) or bool(s.get("fabricated") and r["abstain"]) for s, r in zip(sc, subset, strict=True)),
                "abstained_correctly": sum(r["abstain"] and s["correctness"] == "full" for s, r in zip(sc, subset, strict=True)), "abstention_cases": sum(r["abstain"] for r in subset),
                "contamination": sum(bool((s.get("injection") or {}).get("followed")) or bool((s.get("injection") or {}).get("planted_text_echoed_in_reply")) for s in sc)}

    for cond in sorted({r["cond"] for r in rows}):
        sub = [r for r in rows if r["cond"] == cond]
        w = sum(1 for r in sub if r["other"]["score"]["correctness"] == "full" and r["base"]["score"]["correctness"] != "full")
        l = sum(1 for r in sub if r["base"]["score"]["correctness"] == "full" and r["other"]["score"]["correctness"] != "full")
        out["by_condition"][cond] = {"base": stat(sub, "base"), "other": stat(sub, "other"), "other_better": w, "other_worse": l, "sign_p": sign_p(w, l)}
    evid = [r for r in rows if r["cond"] in ("b1a+routed", "b1a+routed+suff", "b1a+routed+suff+cf")]
    orac = [r for r in rows if r["cond"] == "oracle"]
    for label, pool in (("b1a family", evid), ("oracle", orac)):
        for g, name in GROUPS.items():
            sub = [r for r in pool if r["cat"] == g]
            if sub:
                out["by_group"].setdefault(label, {})[name] = {"base": stat(sub, "base"), "other": stat(sub, "other")}
    for which in ("base", "other"):
        ms = [r[which]["cost"]["total_ms"] for r in rows if r[which]["cost"].get("finish") != "fixed" and r[which]["cost"]["total_ms"]]
        tt = [r[which]["cost"]["ttft_ms"] for r in rows if r[which]["cost"].get("finish") != "fixed" and r[which]["cost"]["ttft_ms"]]
        ct = [r[which]["cost"]["completion_tokens"] for r in rows if r[which]["cost"].get("completion_tokens")]
        pt = [r[which]["cost"]["prompt_tokens"] for r in rows if r[which]["cost"].get("prompt_tokens")]
        out["latency"][which] = {"n": len(ms), "total_ms_median": round(statistics.median(ms)), "total_ms_p95": round(sorted(ms)[int(0.95 * len(ms)) - 1]), "ttft_ms_median": round(statistics.median(tt)),
                                 "completion_tokens_median": statistics.median(ct), "prompt_tokens_median": statistics.median(pt)}
    print(json.dumps(out, indent=1))
    if a.out:
        (HERE / a.out).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
