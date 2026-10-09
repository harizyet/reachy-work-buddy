"""Evaluate the conflict-omission detector against the hand labels (conflict_labels_dev4.json) on the dev4 replies, plus a hand-written stress set of reply variants.

    python conflict_eval.py results/dev4-1500-a.json results/dev4-1500-b.json [--out results/conflict-detector-eval.json]
Reports, for v1 and v2: precision, recall and false positives per unique labelled reply and per row; identification of the disagreeing items (reported pairs that are true conflicts,
true conflicts found); temporal consistency (flags raised only because of an older item); and runtime. It does not touch any answer or gate."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aq import conflicts

BLOCK = re.compile(r'<evidence id="(E\d+)" info="(.*?)">\n(.*?)\n</evidence>', re.DOTALL)

# Hand-written reply variants over fixed evidence, to test number formats and attributions (labels: does the reply omit a side?).
STRESS_EVIDENCE = {
    "hours": ({"E1": ("document chunk | \"Vendor note: Beacon Analytics\" | recorded", "Beacon Analytics support hours are 9 to 5 on weekdays. The support line is 555-0142."),
               "E2": ("memory | recorded", "Beacon Analytics support hours are 8 to 6 on weekdays.")}, "When is Beacon Analytics support available on weekdays?"),
    "rollback": ({"E1": ("document chunk | \"Lantern runbook\" | recorded", "Roll back within 30 minutes of a failed deploy by running the rollback script."),
                  "E2": ("memory | recorded", "The Lantern rollback window is 60 minutes after a failed deploy.")}, "How long is the Lantern rollback window after a failed deploy?"),
    "retries": ({"E1": ("document chunk | \"Harbor architecture\" | recorded", "Jobs flow through the Quill message queue. A failed job is retried up to 5 times before it is parked."),
                 "E2": ("document chunk | \"Harbor architecture v1 (archived)\" | recorded", "Jobs flow through the Quill message queue. A failed job is retried up to 3 times before it is parked."),
                 "E3": ("memory | recorded", "Failed Harbor jobs are retried 10 times before they are parked.")}, "How many times is a failed Harbor job retried before it is parked?"),
}
STRESS = [
    ("hours", "Support is 9 to 5 on weekdays [E1], though another record says 8 to 6 [E2].", False),
    ("hours", "The hours are nine to five according to the vendor note, and eight to six according to a memory.", False),
    ("hours", "Support runs 9-5 [E1]; a second source gives 8-6 [E2].", False),
    ("hours", "Support is open from 9 to 5.", True),
    ("hours", "Support is open from nine to five on weekdays [E1].", True),
    ("hours", "They answer 8 to 6 on weekdays [E2].", True),
    ("hours", "The sources disagree about the hours.", True),
    ("rollback", "30 minutes per the runbook [E1], 60 minutes per a memory [E2].", False),
    ("rollback", "It is a thirty-minute window in the runbook but sixty minutes in your notes.", False),
    ("rollback", "Within half an hour [E1]. One record says an hour [E2].", False),
    ("rollback", "You have 30 minutes [E1].", True),
    ("rollback", "The window is 60 minutes [E2].", True),
    ("rollback", "Roll back within 30 minutes of a failed deploy [E1]; the memory says 60 [E2], so the sources disagree.", False),
    ("retries", "Five retries [E1], though the archived version said three [E2] and a memory says ten [E3].", False),
    ("retries", "Jobs are retried 5 times [E1]; a memory says 10 [E3].", False),
    ("retries", "Jobs are retried 5 times [E1].", True),
    ("retries", "Jobs are retried 10 times [E3].", True),
    ("retries", "The limit is five, raised from three.", True),
    ("retries", "The limit is 5, but one memory says 10, and the archived document said 3.", False),
    ("retries", "Failed jobs are retried five times before parking.", True),
]


def parse_items(context_text: str) -> dict[str, tuple[str, str]]:
    return {eid: (info.replace("&quot;", '"'), body) for eid, info, body in BLOCK.findall(context_text)}


def run(paths: list[str]) -> dict:
    labels = json.loads((HERE / "conflict_labels_dev4.json").read_text())["labels"]
    cases = {c["id"]: c for c in json.loads((HERE / "cases_dev4.json").read_text())["cases"]}
    rows = []
    for path in paths:
        for row in json.loads(Path(path).read_text())["rows"]:
            key = f"{row['id']}|{row['condition']}"
            if key in labels:
                rows.append({"key": key, "run": Path(path).stem, "question": cases[row["id"]]["question"], "reply": row["reply"], "items": parse_items(row["context"]["text"]), "label": labels[key]})
    out: dict = {"rows": len(rows), "unique": len(labels)}
    for version in ("v1", "v2", "v3"):
        tp = fp = fn = tn = 0
        wrong, timings = [], []
        pair_true_hits = pair_reported = true_pairs_total = true_pairs_found = temporal_only_flags = temporal_seen = 0
        for r in rows:
            t = time.perf_counter()
            d = conflicts.detect(r["question"], r["reply"], r["items"], version)
            timings.append((time.perf_counter() - t) * 1e6)
            truth = r["label"]["should_flag"]
            tp += d.flag and truth
            fp += d.flag and not truth
            fn += (not d.flag) and truth
            tn += (not d.flag) and not truth
            if d.flag != truth:
                wrong.append({"row": r["key"], "run": r["run"], "detected": d.flag, "truth": truth, "pairs": d.pairs, "temporal": d.temporal, "scoped": d.scoped})
            true_set = {tuple(sorted(p)) for p in r["label"]["conflict_pairs"]}
            temp_set = {tuple(sorted(p)) for p in r["label"]["temporal_pairs"]}
            reported = {tuple(sorted(p)) for p in d.pairs}
            pair_reported += len(reported)
            pair_true_hits += len(reported & true_set)
            if truth:
                true_pairs_total += len(true_set)
                true_pairs_found += len(reported & true_set)
            if reported and reported <= temp_set:
                temporal_only_flags += 1
            temporal_seen += bool(temp_set)
        out[version] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "false_positive_rate_on_unflagged_truth": round(fp / (fp + tn), 3) if fp + tn else None, "errors": wrong,
            "pair_identification": {"reported_pairs": pair_reported, "reported_that_are_true_conflicts": pair_true_hits, "true_pairs_in_flag_worthy_rows": true_pairs_total, "found": true_pairs_found},
            "flags_raised_only_for_temporally_explained_pairs": temporal_only_flags, "rows_with_a_temporal_pair": temporal_seen,
            "runtime_us_per_reply": {"median": round(statistics.median(timings), 1), "p95": round(sorted(timings)[int(0.95 * len(timings)) - 1], 1), "max": round(max(timings), 1)},
        }
    stress = {"n": len(STRESS), "v1": {"wrong": []}, "v2": {"wrong": []}, "v3": {"wrong": []}}
    for version in ("v1", "v2", "v3"):
        for topic, reply, omits in STRESS:
            items, q = STRESS_EVIDENCE[topic]
            d = conflicts.detect(q, reply, items, version)
            if d.flag != omits:
                stress[version]["wrong"].append({"topic": topic, "reply": reply, "should_flag": omits, "detected": d.flag})
        stress[version]["correct"] = len(STRESS) - len(stress[version]["wrong"])
    out["stress"] = stress
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="+")
    p.add_argument("--out")
    a = p.parse_args()
    result = run(a.runs)
    text = json.dumps(result, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)
