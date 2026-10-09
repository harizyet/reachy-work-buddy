"""Evaluate the deterministic evidence checks (aq/checks.py) on (1) the 21 reviewed answers, with the reviewer's own judgments as labels, and (2) the new dev5 replies, labelled by the
case scorer (a forbidden assertion or fabrication). Nothing is tuned on the consumed holdout: the 21 answers are only the labels' source, the checks were written from the failure types.

    python checks_eval.py [--dev5 results/dev5-1500-a.json ...] --out results/checks-eval.json"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aq import checks
from aq.scoring_v2 import entry_texts

BLOCK = re.compile(r'<evidence id="(E\d+)" info="(.*?)">\n(.*?)\n</evidence>', re.DOTALL)


def infos_of(text: str) -> dict[str, str]:
    return {eid: info for eid, info, _ in BLOCK.findall(text)}


KEY = Path.home() / ".local/share/reachy-blind-review/phase-44e/KEY-do-not-open-until-rated.json"
RATINGS = HERE / "blind_review/phase-44e/ratings-submitted-2026-10-10.csv"
FIRST_LOOK = HERE / "results/holdout-44E-first-look.json"


def norm(x: str) -> str:
    return x.split(":")[0].split("—")[0].strip().lower()


def stats(rows, flagged, label) -> dict:
    tp = sum(1 for r in rows if flagged(r) and label(r))
    fp = sum(1 for r in rows if flagged(r) and not label(r))
    fn = sum(1 for r in rows if not flagged(r) and label(r))
    tn = sum(1 for r in rows if not flagged(r) and not label(r))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(tp / (tp + fp), 2) if tp + fp else None, "recall": round(tp / (tp + fn), 2) if tp + fn else None}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dev5", nargs="*", default=[])
    p.add_argument("--out")
    a = p.parse_args()
    key = json.loads(KEY.read_text())["items"]
    ratings = {r["item"]: r for r in csv.DictReader(RATINGS.open())}
    first = {(r["id"], r["condition"]): r for r in json.loads(FIRST_LOOK.read_text())["rows"]}
    human = []
    for rid, k in sorted(key.items()):
        row = first[(k["case"], k["condition"])]
        items = entry_texts(row["context"]["text"])
        question = next(c["question"] for c in json.loads((HERE / "cases_holdout.json").read_text())["cases"] if c["id"] == k["case"])
        human.append({"item": rid, "reply": row["reply"], "items": items, "flags": checks.run_all(row["reply"], items, question=question, infos=infos_of(row["context"]["text"])), "invented": norm(ratings[rid]["q3"]) == "yes",
                      "repeats": norm(ratings[rid]["q5"]) == "repeats only"})
    out: dict = {"human_set": {"n": len(human), "invented_by_reviewer": sum(r["invented"] for r in human), "repeats_by_reviewer": sum(r["repeats"] for r in human), "per_check": {}, "union": {}}}
    for name in [*checks.CHECKS, "subject_property", "source_label"]:
        target = "repeats" if name == "contamination" else "invented"
        out["human_set"]["per_check"][name] = {**stats(human, lambda r, n=name: bool(r["flags"][n]), lambda r, t=target: r[t]), "flagged_items": [r["item"] for r in human if r["flags"][name]]}
    out["human_set"]["union"] = stats(human, lambda r: any(r["flags"][n] for n in ("value_in_cited_item", "recency_claim", "actor_swapped", "subject_property", "source_label")), lambda r: r["invented"])
    out["human_set"]["union"]["flagged_items"] = [r["item"] for r in human if any(r["flags"][n] for n in ("value_in_cited_item", "recency_claim", "actor_swapped", "subject_property", "source_label"))]
    out["human_set"]["not_found"] = [r["item"] for r in human if r["invented"] and not any(r["flags"][n] for n in ("value_in_cited_item", "recency_claim", "actor_swapped", "subject_property", "source_label"))]
    if a.dev5:
        cases = {c["id"]: c for c in json.loads((HERE / "cases_dev5.json").read_text())["cases"]}
        pool, timings = [], []
        for path in a.dev5:
            for row in json.loads(Path(path).read_text())["rows"]:
                if not row["context"].get("text") or row["id"] not in cases:
                    continue
                items = entry_texts(row["context"]["text"])
                t0 = time.perf_counter()
                flags = checks.run_all(row["reply"], items, question=cases[row["id"]]["question"], infos=infos_of(row["context"]["text"]))
                timings.append((time.perf_counter() - t0) * 1e6)
                sc = row["score"]
                pool.append({"id": row["id"], "condition": row["condition"], "flags": flags, "bad": bool(sc["forbidden_asserted"]) or bool(sc.get("fabricated") and cases[row["id"]]["abstain"]) or sc["ungrounded_facts"] > 0,
                             "injected": bool(sc["injection"] and sc["injection"]["planted_text_echoed_in_reply"])})
        out["dev5"] = {"replies": len(pool), "unsupported_by_scorer": sum(r["bad"] for r in pool),
                       "per_check": {n: stats(pool, lambda r, n=n: bool(r["flags"][n]), lambda r: r["bad"]) for n in ("value_in_cited_item", "recency_claim", "actor_swapped", "subject_property", "source_label")},
                       "contamination_vs_echo": stats(pool, lambda r: bool(r["flags"]["contamination"]), lambda r: r["injected"]), "runtime_us_per_reply_median": round(sorted(timings)[len(timings) // 2], 1)}
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
