"""The dev14 acceptance set stays untouched until its one evaluation: frozen files unchanged, at most one logged run, results only with that log, the guard refuses without approval, and the
development tools never read dev14."""

import json
import os
import subprocess
import sys
from pathlib import Path

AQ = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality"
sys.path.insert(0, str(AQ))
from freeze_check import verify


def test_the_frozen_files_are_unchanged():
    assert verify("dev14_freeze.json") == []


def test_dev14_has_at_most_one_logged_evaluation_and_results_only_with_it():
    log = AQ / "dev14_runs.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    results = sorted(p.name for p in (AQ / "results").glob("*dev14*"))
    assert len(entries) <= 1
    assert bool(results) == bool(entries)


def test_the_runner_refuses_dev14_without_an_approved_decision_point():
    env = {"PATH": "/usr/bin:/bin", "KBENCH_CORPUS": str(AQ / "corpus_v3" / "corpus_v3.json")}
    for args in (["--split", "dev14"], ["--split", "dev14", "--decision-point", "x"]):
        done = subprocess.run([sys.executable, str(AQ / "run_g2.py"), *args, "--conditions", "b1a"], capture_output=True, text=True, check=False, env=env)
        assert done.returncode != 0 and "dev14" in (done.stderr + done.stdout)
    assert "AQ_DEV14_APPROVAL" not in os.environ


def test_development_tools_do_not_read_dev14():
    for name in ("g_design_eval.py", "g2_design_eval.py"):
        text = (AQ / name).read_text()
        assert "cases_dev14" not in text, name
    assert "dev14" not in (AQ / "g2_design_eval.py").read_text()
