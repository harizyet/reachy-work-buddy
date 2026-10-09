"""One-shot guards for the scorer-v3 formal validation. The state moves forward only: frozen -> generated -> labels_frozen -> scored. A stage cannot be repeated or skipped, and a finished run cannot be re-run."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "acceptance" / "STATE.json"
ORDER = ["frozen", "generated", "labels_frozen", "scored"]


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"stage": None, "history": []}


def require(stage_now: str) -> dict:
    s = load()
    if s["stage"] != stage_now:
        raise SystemExit(f"one-shot guard: this step needs the state {stage_now!r}, the state is {s['stage']!r}")
    return s


def advance(new_stage: str, **info) -> None:
    s = load()
    expected = ORDER[ORDER.index(new_stage) - 1] if ORDER.index(new_stage) else None
    if s["stage"] != expected:
        raise SystemExit(f"one-shot guard: cannot move to {new_stage!r} from {s['stage']!r}")
    s["stage"] = new_stage
    s["history"].append({"stage": new_stage, "at": datetime.now(UTC).isoformat(), **info})
    STATE.write_text(json.dumps(s, indent=1))


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == "__main__":
    print(json.dumps(load(), indent=1))
    sys.exit(0)
