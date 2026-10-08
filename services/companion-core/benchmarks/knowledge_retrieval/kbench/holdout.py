"""The frozen holdout is scored once per decision point (docs/phase-44.md section 7.1). Each scoring is appended to a log that is
committed with the fixtures, so repeated looks are visible; a repeat for the same decision point, adapter and fixture version
is refused unless explicitly allowed, and then it is recorded as a repeat."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kbench.fixtures import ROOT, FixtureError

DEFAULT_LOG = ROOT / "holdout_runs.jsonl"


def read_log(path: Path = DEFAULT_LOG) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


SYNTHETIC = "synthetic-deterministic"


def check_allowed(
    decision_point: str | None, adapter: str, fixture_hash: str, *, allow_repeat: bool, track: str = SYNTHETIC, path: Path = DEFAULT_LOG
) -> None:
    if not decision_point:
        raise FixtureError("scoring the holdout needs --decision-point NAME (for example 44A-baseline)")
    earlier = [
        e for e in read_log(path)
        # entries written before tracks existed belong to the synthetic track
        if (e["decision_point"], e["adapter"], e["fixture_hash"], e.get("track", SYNTHETIC)) == (decision_point, adapter, fixture_hash, track)
    ]
    if earlier and not allow_repeat:
        raise FixtureError(
            f"the holdout was already scored for decision point {decision_point!r} with {adapter} on these fixtures "
            f"on the {track} track ({earlier[0]['at']}); a decision point gets one look. Use a new decision point, or --allow-repeat to record a repeat."
        )


def record(report: dict[str, Any], decision_point: str, *, repeat: bool, path: Path = DEFAULT_LOG) -> None:
    entry = {
        "decision_point": decision_point, "adapter": report["adapter"]["name"], "fixture_hash": report["fixtures"]["combined"],
        "track": report["track"], "results_digest": report["results_digest"], "harness_version": report["harness_version"],
        "git_commit": report["environment"]["git_commit"], "repeat": repeat, "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    with path.open("a") as log:
        log.write(json.dumps(entry, sort_keys=True) + "\n")
