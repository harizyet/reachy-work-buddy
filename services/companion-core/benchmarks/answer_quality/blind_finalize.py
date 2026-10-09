"""Help the owner finalize the 21-answer ratings, then rerun the comparison on the final ratings.

    python blind_finalize.py sheet --dir blind_review/phase-44e --ratings blind_review/phase-44e/ratings-submitted-2026-10-10.csv --out blind_review/phase-44e/owner-confirmation.md
    python blind_finalize.py merge --dir blind_review/phase-44e --ratings <submitted.csv> --owner <owner-confirmation.csv> --out blind_review/phase-44e/ratings-final.csv

`sheet` writes, per item, the question, the evidence summary-free answer and the submitted rating with its note, plus the CSV the owner fills in (accept or override each item). It reads only the
sheet and the submitted ratings: it never opens the answer key, and it prints no condition name or score. `merge` applies the owner's overrides (an empty override accepts the submitted value) and
writes the final ratings file; `blind_compare.py` then unseals the key and compares. Nothing here edits the submitted ratings, the sheet, the key or any evaluation result."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

COLS = [f"q{i}" for i in range(1, 9)]
CHOICES = {"q1": "yes / partly / no", "q8": "yes / with checks / no"}


def read_ratings(path: Path) -> dict[str, dict[str, str]]:
    return {r["item"].strip(): r for r in csv.DictReader(path.open())}


def sheet_items(sheet: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r"## (R\d\d)\n(.*?)(?=\n## R|\Z)", sheet, re.DOTALL)}


def cmd_sheet(a) -> int:
    d, ratings = Path(a.dir), read_ratings(Path(a.ratings))
    items = sheet_items((d / "sheet.md").read_text())
    intro = ("Each item shows the question, the answer and the submitted rating of the first rater (an AI rater, per the file name) with its note. **This is an informed review, not a blind one:** the "
           "comparison report has already been written from these ratings and names which system produced several items. For each item write `accept` or give your own value for question 1 "
           "(`yes`, `partly`, `no`) and for question 8 (`yes`, `with checks`, `no`), plus a short note if you disagree. Save `owner-confirmation.csv` (columns below); then run `blind_finalize.py merge`.")
    out = ["# Finalizing the 21 ratings: confirm or override", "", intro, "", "Columns: `item,q1_owner,q8_owner,note`. Leave q1 or q8 empty to accept the submitted value.", ""]
    template = [["item", "q1_owner", "q8_owner", "note"]]
    for item in sorted(items):
        body, r = items[item], ratings[item]
        q = re.search(r"\*\*Question:\*\* (.*)", body).group(1)
        ans = body.split("**Answer:**", 1)[1].strip()
        submitted = (f"**Submitted:** correct = {r['q1']}; every claim supported = {r['q2']}; invented = {r['q3']}; conflict handled = {r['q4']}; "
                     f"injection = {r['q5']}; should abstain = {r['q6']}; citations = {r['q7']}; overall = {r['q8']}")
        out += [f"## {item}", "", f"**Question:** {q}", "", ans, "", submitted, ""]
        template.append([item, "", "", ""])
    (d / "owner-confirmation-template.csv").write_text("\n".join(",".join(row) for row in template) + "\n")
    Path(a.out).write_text("\n".join(out) + "\n")
    print(f"wrote {a.out} and owner-confirmation-template.csv ({len(items)} items)")
    return 0


def cmd_merge(a) -> int:
    ratings = read_ratings(Path(a.ratings))
    with Path(a.owner).open() as handle:
        owner = {r["item"].strip(): r for r in csv.DictReader(handle)}
    unknown = sorted(set(owner) - set(ratings))
    if unknown:
        raise SystemExit(f"unknown items in the owner file: {', '.join(unknown)}")
    valid = {"q1_owner": {"yes", "partly", "no", "accept", ""}, "q8_owner": {"yes", "with checks", "no", "accept", ""}}
    final, changed = [], []
    for item, r in sorted(ratings.items()):
        row = dict(r)
        o = owner.get(item, {})
        for src, dst in (("q1_owner", "q1"), ("q8_owner", "q8")):
            v = (o.get(src) or "").strip().lower()
            if v not in valid[src]:
                raise SystemExit(f"{item}: {src} must be one of {sorted(valid[src] - {''})}, not {v!r}")
            if v and v != "accept":
                row[dst] = f"{v} — owner override" + (f": {o.get('note', '').strip()}" if (o.get("note") or "").strip() else "")
                changed.append(item)
        final.append(row)
    with Path(a.out).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["item", *COLS])
        w.writeheader()
        w.writerows(final)
    print(f"final ratings written to {a.out}; owner overrides on: {', '.join(sorted(set(changed))) or 'none'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--dir", required=True)
    s.add_argument("--ratings", required=True)
    s.add_argument("--out", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--dir", required=True)
    m.add_argument("--ratings", required=True)
    m.add_argument("--owner", required=True)
    m.add_argument("--out", required=True)
    a = p.parse_args()
    return cmd_sheet(a) if a.cmd == "sheet" else cmd_merge(a)


if __name__ == "__main__":
    sys.exit(main())
