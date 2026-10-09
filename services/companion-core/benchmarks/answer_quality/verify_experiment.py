"""Benchmark post-answer claim checks against each other on new development cases (dev2 and dev3 replies), including a second pass by the local model.

    python verify_experiment.py results/dev2-1500-*.json results/dev3-1500-*.json --out results/verify-experiment.json [--llm]

Ground truth comes from the deterministic case scorer, not from any verifier: an *unsupported* reply is a fabrication on an abstention case, a forbidden
assertion, or an asserted required fact the evidence did not contain; a *conflict miss* is an expected-conflict case whose reply lacks a required value.
For each check: how well it finds those replies (precision, recall) and what it costs good replies (flag rate on fully-correct answers). A simulated gate
replaces a flagged reply with an abstention and reports the net effect on correct answers and fabrications. Only replies given evidence are used."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aq import cases as caselib
from aq import llm as llmlib
from aq import verify
from aq.scoring_v2 import entry_texts

SUPPORT_PROMPT = ("You check whether an ANSWER is supported by EVIDENCE. Reply with exactly one word. SUPPORTED if every claim in the answer is stated in the evidence. "
                  "UNSUPPORTED if the answer states anything the evidence does not say, infers something the evidence does not state, or answers a question the evidence does not address.")
CONFLICT_PROMPT = ("You check an ANSWER against EVIDENCE. Reply with exactly one word. NO_CONFLICT if no two evidence items give different values for the same thing. "
                   "REPORTED if some do and the answer states each of the different values. NOT_REPORTED if some do and the answer leaves one out.")


def load_pool(paths: list[str]) -> list[dict]:
    cases = {}
    for split in ("dev2", "dev3"):
        cases.update({c["id"]: c for c in caselib.load_cases(split)})
    pool = []
    for path in paths:
        run = json.loads(Path(path).read_text())
        for row in run["rows"]:
            if row["condition"] == "none" or row["condition"] == "p43" or not row["context"].get("text"):
                continue
            case = cases.get(row["id"])
            if case is None or not entry_texts(row["context"]["text"]) and not row["context"]["entries"]:
                continue
            sc = row["score"]
            unsupported = bool(sc.get("fabricated") and case["abstain"]) or bool(sc["forbidden_asserted"]) or sc["ungrounded_facts"] > 0
            conflict_miss = bool(case["expect_conflict"] and not all(sc["facts_met"]))
            pool.append({"run": Path(path).stem, "id": row["id"], "condition": row["condition"], "case": case, "row": row, "unsupported": unsupported,
                         "conflict_miss": conflict_miss, "good": sc["correctness"] == "full"})
    return pool


def llm_flags(llm: llmlib.Local, item: dict) -> tuple[set[str], int]:
    row, case = item["row"], item["case"]
    evidence = "\n".join(f"[{eid}] {text}" for eid, text in entry_texts(row["context"]["text"]).items()) or "(none)"
    body = f"QUESTION: {case['question']}\nEVIDENCE:\n{evidence}\nANSWER: {row['reply']}"
    flags, tokens = set(), 0
    for name, prompt, bad in (("V6_llm_support", SUPPORT_PROMPT, "UNSUPPORTED"), ("V6_llm_conflict", CONFLICT_PROMPT, "NOT_REPORTED")):
        done = llm.complete([{"role": "system", "content": prompt}, {"role": "user", "content": body}], max_tokens=8)
        tokens += done.prompt_tokens + done.completion_tokens
        if bad in done.text.upper().replace(" ", "_"):
            flags.add(name)
    return flags, tokens


def score(pool: list[dict], flags_of, name: str, target: str) -> dict:
    tp = fp = fn = tn = 0
    good_flagged = good = 0
    for item in pool:
        flagged = bool(flags_of(item))
        truth = item[target]
        tp += flagged and truth
        fp += flagged and not truth
        fn += (not flagged) and truth
        tn += (not flagged) and not truth
        if item["good"]:
            good += 1
            good_flagged += flagged
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return {"check": name, "target": target, "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": None if p is None else round(p, 3),
            "recall": None if r is None else round(r, 3), "flag_rate_on_correct_answers": round(good_flagged / good, 3) if good else None}


def gate_effect(pool: list[dict], flags_of) -> dict:
    """Replace a flagged reply with an abstention and count what changes (answerable cases lose a reply; abstention cases gain one)."""
    correct = fabricated = answerable_lost = 0
    for item in pool:
        case, sc = item["case"], item["row"]["score"]
        flagged = bool(flags_of(item))
        if case["abstain"]:
            fab = (not flagged) and bool(sc.get("fabricated"))
            fabricated += fab
            correct += (flagged or sc["correctness"] == "full")
        else:
            ok = sc["correctness"] == "full" and not flagged
            correct += ok
            answerable_lost += (sc["correctness"] == "full") and flagged
    return {"correct_after_gate": correct, "fabrications_after_gate": fabricated, "good_answers_lost_to_the_gate": answerable_lost}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="+")
    p.add_argument("--out")
    p.add_argument("--llm", action="store_true", help="also run the local model as a second-pass verifier (calls the production vLLM, serially)")
    args = p.parse_args()
    pool = load_pool(args.runs)
    for item in pool:
        q = item["case"]["question"]
        item["flags"] = {name: verify.check(name, item["row"], q) for name in verify.DETERMINISTIC}
    llm_cost = {"calls": 0, "tokens": 0, "seconds": 0.0}
    if args.llm:
        llm = llmlib.Local()
        for item in pool:
            t = time.perf_counter()
            flags, tokens = llm_flags(llm, item)
            item["flags"].update({k: ({k} if k in flags else set()) for k in ("V6_llm_support", "V6_llm_conflict")})
            llm_cost["calls"] += 2
            llm_cost["tokens"] += tokens
            llm_cost["seconds"] += time.perf_counter() - t
    unsup = {"V0_none": lambda i: set(), "V1_lexical": lambda i: i["flags"]["V1_lexical"], "V2_anchors": lambda i: i["flags"]["V2_anchors"],
             "V3_cited": lambda i: i["flags"]["V3_cited"], "V5_relevance": lambda i: i["flags"]["V5_relevance"],
             "V1+V2+V5": lambda i: i["flags"]["V1_lexical"] | i["flags"]["V2_anchors"] | i["flags"]["V5_relevance"],
             "V2+V5": lambda i: i["flags"]["V2_anchors"] | i["flags"]["V5_relevance"]}
    conf = {"V4_conflict": lambda i: i["flags"]["V4_conflict"]}
    if args.llm:
        unsup["V6_llm_support"] = lambda i: i["flags"]["V6_llm_support"]
        unsup["V6+V2+V5"] = lambda i: i["flags"]["V6_llm_support"] | i["flags"]["V2_anchors"] | i["flags"]["V5_relevance"]
        conf["V6_llm_conflict"] = lambda i: i["flags"]["V6_llm_conflict"]
    conflict_pool = [i for i in pool if i["case"]["expect_conflict"]]
    result = {
        "pool": {"replies": len(pool), "unsupported": sum(i["unsupported"] for i in pool), "correct": sum(i["good"] for i in pool), "conflict_cases": len(conflict_pool),
                 "conflict_misses": sum(i["conflict_miss"] for i in conflict_pool), "runs": sorted({i["run"] for i in pool})},
        "unsupported_inference": [score(pool, f, n, "unsupported") for n, f in unsup.items()],
        "unsupported_gate_effect": {n: gate_effect(pool, f) for n, f in unsup.items()},
        "conflict_reporting": [score(conflict_pool, f, n, "conflict_miss") for n, f in conf.items()],
        "llm_second_pass_cost": llm_cost if args.llm else None,
    }
    by = defaultdict(int)
    for i in pool:
        by[i["condition"]] += 1
    result["pool"]["by_condition"] = dict(by)
    text = json.dumps(result, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
