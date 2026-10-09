"""Unseal the blind-review key and compare the owner's ratings with the automatic scores. Refuses to run until every item has all eight answers.

    python blind_compare.py --dir blind_review/phase-44e --ratings ratings.csv [--out comparison.md]

The key file is checked against the committed seal (KEY.sha256) first, so a changed key is detected. The comparison is a finding about the scorer, never a
reason to alter the consumed first-look scores. Ratings columns q1..q8 follow the questions in sheet.md."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

NORMAL = {"yes": "yes", "y": "yes", "partly": "partly", "no": "no", "n": "no"}


def load_ratings(path: Path, items: list[str]) -> dict[str, dict[str, str]]:
    rows = {r["item"].strip(): r for r in csv.DictReader(path.open())}
    missing = [i for i in items if i not in rows or any(not (rows[i].get(f"q{n}") or "").strip() for n in range(1, 9))]
    if missing:
        raise SystemExit(f"ratings incomplete for {', '.join(missing)}: the key stays sealed until all items are rated")
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", required=True)
    p.add_argument("--ratings", required=True)
    p.add_argument("--out")
    args = p.parse_args()
    d = Path(args.dir)
    sheet_items = sorted(line[3:].strip() for line in (d / "sheet.md").read_text().splitlines() if line.startswith("## R"))
    ratings = load_ratings(Path(args.ratings), sheet_items)
    key_path = d / "KEY-do-not-open-until-rated.json"
    if hashlib.sha256(key_path.read_bytes()).hexdigest() != (d / "KEY.sha256").read_text().strip():
        raise SystemExit("the key does not match its seal: it was changed after the package was made")
    key = json.loads(key_path.read_text())["items"]
    lines = ["| Item | Case | Condition | Why selected | Scorer | You: correct | Q2 supported | Q3 invented | Agree on correctness |", "|---|---|---|---|---|---|---|---|---|"]
    agree = 0
    for item in sheet_items:
        k, r = key[item], ratings[item]
        human = NORMAL.get(r["q1"].strip().lower(), r["q1"].strip().lower())
        auto = {"full": "yes", "partial": "partly", "wrong": "no"}[k["automatic_correctness"]]
        ok = human == auto
        agree += ok
        lines.append(f"| {item} | {k['case']} | {k['condition']} | {k['why_selected']} | {auto} | {human} | {r['q2']} | {r['q3']} | {'yes' if ok else '**no**'} |")
    out = ["# Blind review comparison", "", f"Agreement on correctness: {agree} of {len(sheet_items)}. Disagreements are findings about the scorer; the first-look scores are not changed.", ""] + lines
    text = "\n".join(out) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
