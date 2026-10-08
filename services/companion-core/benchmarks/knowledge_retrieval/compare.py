"""Paired case-level comparison of recorded reports.

    python compare.py results/44D-first-look-b1a-holdout.json results/44D-first-look-b1b-holdout.json [more reports] [--out FILE]

The first report is the reference `a`; every other report is compared with it as `b - a` (and, for three or more, every pair among the
others as well). Reads recorded reports only; it runs no retrieval and does not touch the holdout log."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kbench.paired import paired


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    loaded = [json.loads(Path(p).read_text()) for p in args.reports]
    out = [paired(a, b) for a, b in itertools.combinations(loaded, 2)]
    text = json.dumps(out, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
