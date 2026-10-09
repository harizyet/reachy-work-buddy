"""The dev10 acceptance set stays untouched until its one evaluation: frozen files unchanged, at most one logged run, results only with that log, the guard refuses without approval, and the
development tools never read dev10."""

import json
import subprocess
import sys
from pathlib import Path

AQ = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality"
sys.path.insert(0, str(AQ))
from freeze_check import verify


def test_the_frozen_files_are_unchanged():
    assert verify("dev10_freeze.json") == []


def test_dev10_has_at_most_one_logged_evaluation_and_results_only_with_it():
    log = AQ / "dev10_runs.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    results = sorted(p.name for p in (AQ / "results").glob("*dev10*"))
    assert len(entries) <= 1
    assert bool(results) == bool(entries)


def test_the_runner_refuses_dev10_without_an_approved_decision_point():
    for args in (["--split", "dev10"], ["--split", "dev10", "--decision-point", "x"]):
        done = subprocess.run([sys.executable, str(AQ / "run_sec.py"), *args, "--conditions", "b1a+routed"], capture_output=True, text=True, check=False, env={"PATH": "/usr/bin:/bin"})
        assert done.returncode != 0 and "dev10" in (done.stderr + done.stdout)


def test_development_tools_do_not_read_dev10():
    for name in ("sec_design_eval.py", "sec_overhead.py", "sufficiency_eval.py", "postcheck_eval.py", "summarize_sufficiency.py"):
        text = (AQ / name).read_text()
        assert '"dev10"' not in text and "cases_dev10" not in text, name
