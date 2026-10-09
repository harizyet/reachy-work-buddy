"""Runner for the section-level experiment: `run.py` with the `+sec`/`+secd` conditions available. Same arguments as run.py. dev10 (acceptance) is guarded like dev8: one evaluation, after approval,
against the frozen files in dev10_freeze.json."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run as base_run
from aq import conditions_sec

base_run.Conditions = conditions_sec.SecConditions

if __name__ == "__main__":
    raise SystemExit(base_run.main())
