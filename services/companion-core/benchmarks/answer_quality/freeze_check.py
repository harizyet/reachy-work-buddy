"""Verify that the files dev8 was frozen against have not changed (dev8_freeze.json). Used by run.py before a dev8 evaluation and by the test suite."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> list[str]:
    freeze = json.loads((HERE / "dev8_freeze.json").read_text())
    problems = []
    for rel, expected in freeze["files"].items():
        path = REPO / rel
        if not path.exists():
            problems.append(f"{rel}: missing")
        elif sha(path) != expected:
            problems.append(f"{rel}: changed")
    return problems


if __name__ == "__main__":
    bad = verify()
    print("frozen files unchanged" if not bad else "\n".join(bad))
    raise SystemExit(1 if bad else 0)
