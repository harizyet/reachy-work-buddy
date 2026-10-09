"""Regression tests for tools/knowledge_indexing_trial.py (the supervised-trial monitor), from the 2026-10-09 trial: a planned core restart tripped the health gate, and the
4 Hz watcher left idle database sessions behind. No Docker, no database: the gates are a pure state machine and the shell calls are replaced."""

import importlib.util
import time
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("ks_trial", Path(__file__).resolve().parents[3] / "tools" / "knowledge_indexing_trial.py")
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)

OK = (90, "200")
DOWN = (14, "error")


def sample(**kw):
    base = {"pg": 10, "cl_waiting": 0, "maxwait": 0, "core": OK, "hub": OK, "vllm": OK, "load1": 2.0, "available_mb": 8000, "outbox_failed": "0"}
    return {**base, **kw}


def test_two_unreachable_core_samples_abort_without_a_planned_restart():
    g = trial.Gates()
    assert g.check(sample(core=DOWN)) == ""  # one bad sample is tolerated
    assert "health failing" in g.check(sample(core=DOWN)) and "core" in g.check(sample(core=DOWN))


def test_a_planned_restart_lets_core_be_unreachable_without_aborting():
    g = trial.Gates()
    for _ in range(5):  # a restart that takes many samples
        assert g.check(sample(core=DOWN), core_grace=True) == ""
    assert g.check(sample()) == ""  # and back to normal afterwards


def test_the_grace_covers_core_only_hub_vllm_and_every_other_gate_still_apply():
    g = trial.Gates()
    g.check(sample(core=DOWN, hub=DOWN), core_grace=True)
    assert "hub" in g.check(sample(core=DOWN, hub=DOWN), core_grace=True)  # a hub failure during the grace aborts
    v = trial.Gates()
    assert v.check(sample(vllm=DOWN), core_grace=True) == "" and "vllm" in v.check(sample(vllm=DOWN), core_grace=True)  # vLLM down twice aborts even during the grace
    for bad, text in ((sample(pg=85), "PostgreSQL connections"), (sample(load1=15.0), "load"), (sample(available_mb=2000), "memory"), (sample(outbox_failed="1"), "outbox row failed"),
                      (sample(maxwait=2), "maxwait")):
        assert text in trial.Gates().check(bad, core_grace=True)
    g2 = trial.Gates()
    results = [g2.check(sample(cl_waiting=1), core_grace=True) for _ in range(3)]
    assert results[:2] == ["", ""] and "waiting" in results[2]


def test_a_stop_file_aborts_and_slow_health_counts_like_a_failure(tmp_path):
    stop = tmp_path / "STOP"
    g = trial.Gates(stop_file=stop)
    assert g.check(sample()) == ""
    stop.write_text("")
    assert g.check(sample()) == "stop file"
    slow = trial.Gates()
    slow.check(sample(hub=(3500, "200")))
    assert "hub" in slow.check(sample(hub=(3500, "200")))


def test_the_restart_marker_expires_and_is_clamped(tmp_path):
    marker = tmp_path / "RESTART"
    assert not trial.grace_active(marker)
    trial.planned_restart(30, marker)
    assert trial.grace_active(marker) and not trial.grace_active(marker, now=time.time() + 31)
    trial.planned_restart(10_000, marker)
    assert not trial.grace_active(marker, now=time.time() + 121)  # never longer than two minutes
    marker.write_text("not a number")
    assert not trial.grace_active(marker)


def test_the_watch_always_closes_its_database_session_even_on_error(tmp_path, monkeypatch):
    closed, popen_calls = [], []

    class FakeProc:
        def __init__(self, *a, **k):
            popen_calls.append(a)
            self.stdin = type("S", (), {"write": lambda self, x: None, "flush": lambda self: None})()
            self.terminated = False

        def terminate(self):
            self.terminated = True

    monkeypatch.setattr(trial.subprocess, "Popen", lambda *a, **k: FakeProc(*a, **k))
    monkeypatch.setattr(trial, "psql", lambda sql: closed.append(sql) or "")
    monkeypatch.setattr(trial.time, "sleep", lambda s: None)
    assert trial.watch(1, tmp_path / "w.tsv") == 0
    assert len(closed) == 1 and trial.WATCH_APP in closed[0] and "pg_terminate_backend" in closed[0]
    assert "PGAPPNAME=" + trial.WATCH_APP in popen_calls[0][0]  # the session is named, so it can be found and closed

    def interrupted(s):
        raise KeyboardInterrupt

    monkeypatch.setattr(trial.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        trial.watch(1, tmp_path / "w2.tsv")
    assert len(closed) == 2  # closed on the way out of an interrupt too


def test_every_database_statement_the_tool_runs_is_a_select_and_it_never_edits_a_flag():
    """The only statement that is not a plain read is terminating its own named watcher session (a select of pg_terminate_backend)."""
    import ast

    tree = ast.parse(Path(trial.__file__).read_text())
    statements = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "psql" and node.args:
            arg = node.args[0]
            statements.append("".join(p.value for p in (arg.values if isinstance(arg, ast.JoinedStr) else [arg]) if isinstance(p, ast.Constant) and isinstance(p.value, str)))
    assert len(statements) >= 8 and all(st.lstrip().lower().startswith("select") for st in statements)
    called = {getattr(n.func, "attr", getattr(n.func, "id", "")) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "up" not in called and not any(isinstance(n, ast.Constant) and n.value == "up" for n in ast.walk(tree))  # it never recreates a service: the operator runs the compose commands
