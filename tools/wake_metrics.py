"""Phase 30.2: wake metrics from embodiment container logs.

Reads `docker logs -t reachy-embodiment` output (file or stdin) and prints
the Phase 30 metrics for one scored exposure period. Read-only: no robot,
hub or database access.

Each "wake detection (score S): ..." line starts a candidate; the next
outcome line ("admitted", "rejected by the hub", "discarded on the robot",
"upload failed") closes it. Owner-supplied genuine attempt times (UTC
HH:MM:SS, one per --genuine) mark which candidates were intended; every
other candidate is false. Without --genuine, all candidates count as false
and the genuine rates are not reported.

    docker logs -t reachy-embodiment 2>&1 | python tools/wake_metrics.py \
        --genuine 12:01:10 --genuine 12:02:30 --hours 0.6
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z\s+(.*)$")
DETECT = re.compile(r"wake detection \(score ([\d.]+)\): (alert raise|silent capture)")
OUTCOMES = {
    "wake candidate admitted": "admitted",
    "wake candidate rejected by the hub": "rejected",
    "wake candidate discarded on the robot": "discarded",
    "wake candidate upload failed": "failed",
    "wake candidate refused": "refused",
}
MATCH_WINDOW = timedelta(seconds=15)


@dataclass
class Candidate:
    at: datetime
    score: float
    raised: bool
    outcome: str = "unknown"
    genuine: bool = False


def parse(lines: list[str]) -> list[Candidate]:
    found: list[Candidate] = []
    current: Candidate | None = None
    for raw in lines:
        m = LINE.match(raw.strip())
        if not m:
            continue
        at = datetime.fromisoformat(f"{m[1]}T{m[2]}")
        text = m[3]
        d = DETECT.search(text)
        if d:
            current = Candidate(at, float(d[1]), d[2] == "alert raise")
            found.append(current)
            continue
        for needle, outcome in OUTCOMES.items():
            if needle in text and current and current.outcome == "unknown":
                current.outcome = outcome
    return found


def mark_genuine(candidates: list[Candidate], attempts: list[datetime]) -> int:
    """Marks the first unmatched detection within the window of each attempt;
    returns the attempts that produced no detection at all."""
    missed = 0
    for attempt in attempts:
        hit = next(
            (
                c
                for c in candidates
                if not c.genuine
                and attempt - timedelta(seconds=2) <= c.at <= attempt + MATCH_WINDOW
            ),
            None,
        )
        if hit:
            hit.genuine = True
        else:
            missed += 1
    return missed


def summarize(
    candidates: list[Candidate], hours: float, attempts: int | None, missed: int
) -> list[str]:
    false = [c for c in candidates if not c.genuine]
    genuine = [c for c in candidates if c.genuine]
    raises = [c for c in candidates if c.raised]
    false_raises = [c for c in false if c.raised]
    false_admitted = [c for c in false if c.outcome == "admitted"]
    visible = len(false_raises) + len(false_admitted)
    rows = [
        ("exposure hours", f"{hours:.2f}"),
        ("wake candidates/hour", f"{len(candidates) / hours:.1f} ({len(candidates)})"),
        ("alert raises/hour", f"{len(raises) / hours:.1f} ({len(raises)})"),
        (
            "visible_false_activations_per_hour",
            f"{visible / hours:.1f} ({len(false_raises)} raises + {len(false_admitted)} admitted)",
        ),
        (
            "false conversations admitted/hour",
            f"{len(false_admitted) / hours:.1f} ({len(false_admitted)})",
        ),
    ]
    if attempts is not None:
        accepted = sum(c.outcome == "admitted" for c in genuine)
        immediate = sum(c.raised for c in genuine)
        rows.append(
            (
                "genuine wake acceptance",
                f"{accepted}/{attempts} ({missed} never detected)",
            )
        )
        rows.append(("genuine immediate-alert rate", f"{immediate}/{attempts}"))
    else:
        rows.append(("genuine rates", "not reported: no --genuine attempts given"))
    return [f"{k}: {v}" for k, v in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", nargs="?", help="docker logs -t output; default stdin")
    parser.add_argument(
        "--hours", type=float, required=True, help="scored exposure hours"
    )
    parser.add_argument(
        "--genuine",
        action="append",
        default=[],
        metavar="HH:MM:SS",
        help="UTC time of an intended 'Hey Reachy' (repeatable)",
    )
    parser.add_argument(
        "--date", help="UTC date for --genuine times; default: first log line's"
    )
    args = parser.parse_args()
    if args.hours <= 0:
        raise SystemExit("--hours must be positive")
    if args.log:
        with open(args.log) as f:
            lines = f.read().splitlines()
    else:
        lines = sys.stdin.read().splitlines()
    candidates = parse(lines)
    attempts: list[datetime] = []
    if args.genuine:
        first = next(
            (LINE.match(x.strip()) for x in lines if LINE.match(x.strip())), None
        )
        date = args.date or (first[1] if first else None)
        if not date:
            raise SystemExit("no timestamped log lines and no --date")
        attempts = [datetime.fromisoformat(f"{date}T{t}") for t in args.genuine]
    missed = mark_genuine(candidates, attempts)
    print(
        "\n".join(
            summarize(
                candidates, args.hours, len(attempts) if attempts else None, missed
            )
        )
    )
    for c in candidates:
        label = "genuine" if c.genuine else "false"
        print(
            f"  {c.at:%H:%M:%S} score {c.score:.2f} raise={c.raised} {c.outcome} [{label}]"
        )


if __name__ == "__main__":
    main()
