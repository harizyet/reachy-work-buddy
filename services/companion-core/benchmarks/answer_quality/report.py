"""Summaries of an answer-quality run: each dimension separately, per condition and per category, plus paired comparisons.

    python report.py results/dev-1500.json [--markdown out.md]

Correctness here is `full` on the deterministic scorer (answerable: every required fact and nothing forbidden; abstention case: the reply
says the records do not have it). Rates carry Wilson intervals; paired tests are exact McNemar (sign test on discordant cases)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "knowledge_retrieval"))

from kbench.paired import bootstrap_ci, sign_test_p
from kbench.scoring import percentile, wilson


def rate(num: int, den: int) -> dict:
    ci = wilson(num, den)
    return {"n": den, "k": num, "rate": round(num / den, 3) if den else None, "wilson95": [round(ci[0], 2), round(ci[1], 2)] if ci else None}


def summarise(rows: list[dict]) -> dict:
    ans = [r for r in rows if not r["_abstain"]]
    abst = [r for r in rows if r["_abstain"]]
    out: dict = {"cases": len(rows)}
    out["correctness_answerable"] = {
        "full": rate(sum(r["score"]["correctness"] == "full" for r in ans), len(ans)),
        "partial": rate(sum(r["score"]["correctness"] == "partial" for r in ans), len(ans)),
        "wrong": rate(sum(r["score"]["correctness"] == "wrong" for r in ans), len(ans)),
        "over_abstained": rate(sum(bool(r["score"].get("over_abstained")) for r in ans), len(ans)),
    }
    out["abstention"] = {"correct": rate(sum(r["score"]["correctness"] == "full" for r in abst), len(abst)),
                         "fabricated": rate(sum(bool(r["score"]["fabricated"]) for r in abst), len(abst))}
    out["hallucinations_total"] = sum(r["score"]["hallucinations"] for r in rows)
    asserted = sum(r["score"]["facts_asserted"] for r in rows)
    out["groundedness"] = {"facts_asserted": asserted, "grounded": rate(sum(r["score"]["facts_grounded"] for r in rows), asserted),
                           "answers_with_ungrounded_fact": sum(r["score"]["ungrounded_facts"] > 0 for r in rows)}
    cit = [r for r in ans if r["score"].get("citation")]
    if cit:
        precisions = [r["score"]["citation"]["precision"] for r in cit if r["score"]["citation"]["precision"] is not None]
        out["citations"] = {
            "correct": rate(sum(r["score"]["citation"]["correct"] for r in cit), len(cit)),
            "uncited_answers": rate(sum(r["score"]["citation"]["uncited_answer"] for r in cit), len(cit)),
            "unknown_ids": sum(r["score"]["citation"]["unknown_ids"] for r in cit),
            "mean_precision": round(sum(precisions) / len(precisions), 3) if precisions else None,
        }
    else:
        out["citations"] = "not applicable (no ids offered)"
    priv = [r["score"]["privacy"] for r in rows if r["_has_privacy"]]
    out["privacy"] = {
        "cases_with_canaries_or_exclusions": len(priv),
        "canary_in_reply": sum(bool(p["canary_in_reply"]) for p in priv),
        "canary_in_prompt": sum(bool(p["canary_in_prompt"]) for p in priv),
        "excluded_source_in_prompt": sum(bool(p["excluded_in_prompt"]) for p in priv),
        "rule_violations_in_any_prompt": sum(bool(r["score"]["privacy"]["rule_violations_in_prompt"]) for r in rows),
    }
    inj = [r for r in rows if r["score"]["injection"]]
    out["injection"] = {"cases": len(inj), "reply_followed_stored_instruction": sum(bool(r["score"]["injection"]["followed"]) for r in inj),
                        "planted_text_in_prompt": sum(bool(r["score"]["injection"]["planted_text_in_prompt"]) for r in inj),
                        "planted_text_echoed_in_reply": sum(bool(r["score"]["injection"]["planted_text_echoed_in_reply"]) for r in inj)}
    voice = [r for r in rows if r["score"].get("voice")]
    out["voice"] = {"cases": len(voice), "ok": sum(r["score"]["voice"]["ok"] for r in voice)}
    cost = [r["cost"] for r in rows]

    def stat(key, unit=""):
        values = [c[key] for c in cost if c[key] is not None]
        return {"p50": round(percentile(values, 50) or 0, 1), "p95": round(percentile(values, 95) or 0, 1), "mean": round(sum(values) / len(values), 1)} if values else None

    out["latency_ms"] = {"retrieval": stat("retrieval_ms"), "build": stat("build_ms"), "ttft": stat("ttft_ms"), "total": stat("total_ms")}
    out["tokens"] = {"evidence": stat("evidence_tokens"), "prompt": stat("prompt_tokens"), "completion": stat("completion_tokens")}
    dropped: dict[str, int] = defaultdict(int)
    for r in rows:
        for reason, n in r["context"]["dropped"].items():
            dropped[reason] += n
    out["context_exclusions_by_reason"] = dict(sorted(dropped.items()))
    out["truncated_replies"] = sum(c["finish"] == "length" for c in cost)
    return out


def paired(a_rows: dict, b_rows: dict, label: str) -> dict:
    ids = [i for i in a_rows if i in b_rows]
    only_b = sum(b_rows[i]["score"]["correctness"] == "full" and a_rows[i]["score"]["correctness"] != "full" for i in ids)
    only_a = sum(a_rows[i]["score"]["correctness"] == "full" and b_rows[i]["score"]["correctness"] != "full" for i in ids)
    deltas = [(b_rows[i]["score"]["correctness"] == "full") - (a_rows[i]["score"]["correctness"] == "full") for i in ids]
    ci = bootstrap_ci([float(d) for d in deltas]) if deltas else None
    return {"comparison": label, "cases": len(ids), "b_only_full": only_b, "a_only_full": only_a, "mcnemar_exact_p": (round(sign_test_p(only_b, only_a), 4) if sign_test_p(only_b, only_a) is not None else None),
            "mean_difference_in_full_rate": round(sum(deltas) / len(deltas), 3) if deltas else None, "bootstrap95": [round(ci[0], 3), round(ci[1], 3)] if ci else None,
            "cases_b_better": [i for i, d in zip(ids, deltas, strict=True) if d > 0], "cases_a_better": [i for i, d in zip(ids, deltas, strict=True) if d < 0]}


def build(report: dict, cases: list[dict]) -> dict:
    meta = {c["id"]: c for c in cases}
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for r in report["rows"]:
        c = meta[r["id"]]
        r["_abstain"], r["_has_privacy"] = c["abstain"], bool(c["canaries"] or c["excluded_refs"])
        by_cond[r["condition"]].append(r)
    result = {"split": report["split"], "budget": report["budget"], "hashes": report["hashes"], "git_commit": report["git_commit"], "model": report["model"],
              "wall_seconds": report["wall_seconds"], "conditions": {c: summarise(rows) for c, rows in by_cond.items()}, "by_category": {}, "paired": []}
    for cond, rows in by_cond.items():
        cats: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            cats[r["category"]].append(r)
        result["by_category"][cond] = {cat: {"n": len(v), "full": sum(r["score"]["correctness"] == "full" for r in v)} for cat, v in sorted(cats.items())}
    idx = {c: {r["id"]: r for r in rows} for c, rows in by_cond.items()}
    for a, b in (("none", "b1a"), ("none", "b1b"), ("p43", "b1a"), ("p43", "b1b"), ("b1a", "b1b"), ("b1a", "oracle"), ("b1b", "oracle"),
                 ("b1a", "b1a+v2"), ("b1a", "b1a+routed"), ("b1a", "b1a+routed+v2"), ("b1a+routed", "b1a+routed+v2"), ("b1a+v2", "b1a+routed+v2"),
                 ("b1a+routed+v2", "oracle"), ("none", "b1a+routed+v2"),
                 ("b1a", "b1a+cf"), ("b1a+routed", "b1a+routed+cf"), ("b1a", "b1a+routed+cf"), ("b1a+routed+cf", "oracle")):
        if a in idx and b in idx:
            result["paired"].append(paired(idx[a], idx[b], f"{a} -> {b}"))
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("report")
    p.add_argument("--out")
    args = p.parse_args()
    report = json.loads(Path(args.report).read_text())
    cases = json.loads((Path(__file__).resolve().parent / f"cases_{report['split']}.json").read_text())["cases"]
    text = json.dumps(build(report, cases), indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
