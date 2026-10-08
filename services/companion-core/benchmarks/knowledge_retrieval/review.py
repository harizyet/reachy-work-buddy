"""Write the case-level review of recorded results.

    python review.py --out ../../../../docs/verification/phase-44a-holdout-case-review-2026-10-08.md

Reads results/44A-baseline-<system>-holdout.json and the fixtures. It runs no retrieval and does not touch the holdout log."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kbench.fixtures import ROOT, FixtureError
from kbench.review import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout"), default="holdout")
    parser.add_argument("--systems", nargs="+", default=["b0", "b0-oracle"])
    parser.add_argument("--prefix", default="44A-baseline")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        reports = {s: json.loads((ROOT / "results" / f"{args.prefix}-{s}-{args.split}.json").read_text()) for s in args.systems}
        text = render(reports, args.split)
    except (FixtureError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
