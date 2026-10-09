"""The dev8 acceptance set stays untouched: the frozen files still hash as recorded, nothing has been evaluated on dev8 yet (or exactly one run is logged), no dev8 result exists unless that log does,
the one-shot guard refuses without an approval, and the development tools never read dev8."""

import json
import subprocess
import sys
from pathlib import Path

AQ = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality"
sys.path.insert(0, str(AQ))
from freeze_check import verify


def test_the_frozen_files_are_unchanged():
    assert verify() == []


def test_dev8_has_at_most_one_logged_evaluation_and_results_only_with_it():
    log = AQ / "dev8_runs.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    results = sorted(p.name for p in (AQ / "results").glob("*dev8*"))
    assert len(entries) <= 1
    assert bool(results) == bool(entries)


def test_the_runner_refuses_dev8_without_an_approved_decision_point(tmp_path):
    for args, env_extra in ((["--split", "dev8"], {}), (["--split", "dev8", "--decision-point", "x"], {})):
        done = subprocess.run([sys.executable, str(AQ / "run.py"), *args, "--conditions", "b1a+routed"], capture_output=True, text=True, check=False, env={"PATH": "/usr/bin:/bin", **env_extra})
        assert done.returncode != 0 and "dev8" in (done.stderr + done.stdout)


def test_development_tools_do_not_read_dev8():
    for name in ("sufficiency_eval.py", "postcheck_eval.py", "summarize_sufficiency.py"):
        text = (AQ / name).read_text()
        assert '"dev8"' not in text and "cases_dev8" not in text, name
