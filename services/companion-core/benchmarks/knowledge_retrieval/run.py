"""Score a retrieval adapter against the frozen fixtures.

    python run.py --adapter b0 --split dev
    python run.py --adapter b0-oracle --split holdout --decision-point 44A-baseline

`dev` may be run as often as needed. `holdout` needs a decision point and is logged in holdout_runs.jsonl. The report is JSON:
fixture hashes, per-category metrics with Wilson intervals, per-case hits, leakage, action-boundary probes, and a results digest
that two runs over the same fixtures must reproduce. Nothing here calls a model."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kbench import holdout
from kbench.adapters import ADAPTERS
from kbench.fixtures import (
    FixtureError,
    fixture_hashes,
    validate_fixtures,
)
from kbench.report import TRACKS, evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adapter", choices=sorted(ADAPTERS), default="b0")
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument(
        "--embedder", choices=("hashing", "minilm"), default="hashing",
        help="hashing: the deterministic synthetic track (default). minilm: the production-embedding track; "
        "loads the real model and is reported separately, never combined with the synthetic scores",
    )
    parser.add_argument("--decision-point", help="required for the holdout, for example 44A-baseline")
    parser.add_argument("--allow-repeat", action="store_true", help="score a holdout decision point again; recorded as a repeat")
    parser.add_argument("--out", help="write the JSON report here (default: stdout)")
    parser.add_argument("--no-probes", action="store_true", help="skip the action-boundary probes")
    parser.add_argument("--validate-only", action="store_true", help="check the fixtures and exit")
    args = parser.parse_args(argv)

    problems = validate_fixtures()
    if problems:
        print("fixture problems:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if args.validate_only:
        print(json.dumps({"fixtures": "valid", **fixture_hashes()}, indent=2))
        return 0
    adapter = ADAPTERS[args.adapter]()
    try:
        if args.split == "holdout":
            holdout.check_allowed(
                args.decision_point, adapter.name, fixture_hashes()["combined"], allow_repeat=args.allow_repeat,
                track=TRACKS[args.embedder],
            )
        report = asyncio.run(evaluate(adapter, args.split, embedder=args.embedder, probes=not args.no_probes))
    except FixtureError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.split == "holdout":
        holdout.record(report, args.decision_point, repeat=args.allow_repeat)
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
