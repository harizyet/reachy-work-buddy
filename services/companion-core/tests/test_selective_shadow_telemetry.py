"""Phase 44E selective shadow telemetry hardening (owner decision 2026-10-10): one persisted row per hour merged across flushes and restarts, atomic and retained writes, shutdown flush,
small-cell suppression in the report/export, and no text. Pure file tests; no network, database or model."""

import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from companion_core.knowledge import selective_shadow as ss


def clock(box):
    return lambda: box[0]


def at(hour, minute=0, day=10):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def test_repeated_flushes_and_restarts_leave_exactly_one_row_per_hour(tmp_path):
    path, now = str(tmp_path / "t.jsonl"), [at(9, 5)]
    tel = ss.SelectiveShadowTelemetry(path, clock=clock(now))
    for minute in (5, 15, 40):
        now[0] = at(9, minute)
        tel.count("funnel", "attempted", 2)
        tel.count("class", "typed")
        tel.flush()
    tel2 = ss.SelectiveShadowTelemetry(path, clock=clock(now))  # a restart in the same hour
    now[0] = at(9, 50)
    tel2.count("funnel", "attempted")
    tel2.flush()
    got = rows(path)
    assert len(got) == 1 and got[0]["window_start"] == "2026-10-10T09:00Z"
    assert got[0]["groups"] == {"class": {"typed": 3}, "funnel": {"attempted": 7}}
    now[0] = at(10, 1)
    tel2.count("funnel", "attempted")
    tel2.flush()
    assert [r["window_start"] for r in rows(path)] == ["2026-10-10T09:00Z", "2026-10-10T10:00Z"]


def test_a_legacy_file_with_several_rows_per_hour_is_folded_into_one(tmp_path):
    path = tmp_path / "t.jsonl"
    legacy = [{"schema": 1, "window_start": "2026-10-10T09:00Z", "groups": {"funnel": {"attempted": 1}}}] * 3
    path.write_text("".join(json.dumps(r) + "\n" for r in legacy) + "not json\n")
    tel = ss.SelectiveShadowTelemetry(str(path), clock=lambda: at(9, 30))
    assert tel.prune(force=True) == 1  # the unparsable line
    assert rows(path) == [{"schema": 1, "window_start": "2026-10-10T09:00Z", "groups": {"funnel": {"attempted": 3}}}]
    assert ss.SelectiveShadowTelemetry.read_totals(str(path)) == {"funnel": {"attempted": 3}}


def test_retention_removes_old_rows_on_start_and_on_a_daily_flush_and_keeps_the_file_private(tmp_path):
    path, now = str(tmp_path / "t.jsonl"), [at(9)]
    old = [{"schema": 1, "window_start": (at(9) - timedelta(days=d)).strftime("%Y-%m-%dT%H:00Z"), "groups": {"funnel": {"attempted": 1}}} for d in (45, 31, 29, 1)]
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in old))
    os.chmod(path, 0o644)
    tel = ss.SelectiveShadowTelemetry(path, retention_days=30, clock=clock(now))
    assert tel.prune(force=True) == 2
    assert len(rows(path)) == 2 and stat.S_IMODE(os.stat(path).st_mode) == 0o600  # rewritten through a private temporary file
    now[0] = at(9) + timedelta(days=40)  # a long-running process: the next flush prunes again
    tel.count("funnel", "attempted")
    tel._last_prune = float("-inf")
    tel.flush()
    assert [r["window_start"][:10] for r in rows(path)] == ["2026-11-19"]  # everything older than the retention period is gone
    assert not list(tmp_path.glob(".kss-*"))  # no temporary file is left behind


def test_shutdown_flushes_the_open_hour_and_a_crash_loses_at_most_the_unflushed_interval(tmp_path):
    path, now = str(tmp_path / "t.jsonl"), [at(9, 10)]
    tel = ss.SelectiveShadowTelemetry(path, clock=clock(now), flush_seconds=3600)
    tel.count("funnel", "attempted", 4)
    tel.flush()
    tel.count("funnel", "attempted", 3)  # never flushed: the process dies here
    assert rows(path)[0]["groups"]["funnel"]["attempted"] == 4 and len(rows(path)) == 1
    survivor = ss.SelectiveShadowTelemetry(path, clock=clock(now), flush_seconds=3600)
    survivor.count("funnel", "attempted")
    survivor.flush()  # what stop() does
    assert rows(path)[0]["groups"]["funnel"]["attempted"] == 5 and len(rows(path)) == 1


def test_a_failed_write_keeps_the_counts_and_never_leaves_a_partial_file(tmp_path, monkeypatch):
    path, now = str(tmp_path / "t.jsonl"), [at(9)]
    tel = ss.SelectiveShadowTelemetry(path, clock=clock(now))
    tel.count("funnel", "attempted", 2)
    tel.flush()
    before = Path(path).read_text()
    real = os.replace

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    tel.count("funnel", "attempted", 3)
    tel.flush()
    assert Path(path).read_text() == before and not list(tmp_path.glob(".kss-*"))
    assert tel.total["funnel"]["telemetry_write_failed"] == 1
    monkeypatch.setattr(os, "replace", real)
    tel.flush()
    assert rows(path)[0]["groups"]["funnel"]["attempted"] == 5  # the retried flush carried the kept counts


def test_report_suppresses_small_cells_hides_complements_and_never_prints_hidden_counts(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"schema": 1, "window_start": "2026-10-10T09:00Z", "groups": {
        "funnel": {"attempted": 40, "admitted": 38, "skipped_slash": 2},
        "class": {"typed": 12, "untyped": 3, "ineligible": 25},
        "outcome": {"answered_supported": 7, "failed_retrieval": 1, "answered_unsupported": 9}}}) + "\n")
    out = ss.report(str(path))
    assert out["min_cell"] == 5 and "2026-10-10" in (out["first_day"], out["last_day"])
    flat = {(g, n): v for g, cells in out["groups"].items() for n, v in cells.items()}
    assert ("funnel", "skipped_slash") not in flat and ("class", "untyped") not in flat and ("outcome", "failed_retrieval") not in flat  # below 5
    assert ("funnel", "admitted") not in flat  # complement: with one hidden cell, the smallest visible cell of the group is hidden too, so the hidden 2 cannot be recovered by subtraction
    assert ("class", "typed") not in flat and flat[("class", "ineligible")] == 25
    assert out["suppressed_cells"] == 6 and "2" not in json.dumps(out["groups"].get("funnel", {})).replace("40", "")
    text = json.dumps(out)
    assert '"skipped_slash"' not in text and '"failed_retrieval"' not in text
    assert ss.report(str(path), min_cell=1)["min_cell"] == 2  # clamped: a threshold of 1 would suppress nothing
    daily = ss.report(str(path), by="day")
    assert set(daily["days"]) == {"2026-10-10"} and daily["days"]["2026-10-10"]["suppressed_cells"] == 6
    assert ss.report(str(tmp_path / "missing.jsonl"))["groups"] == {}


def test_the_export_command_prints_only_the_suppressed_report(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"schema": 1, "window_start": "2026-10-10T09:00Z", "groups": {"class": {"typed": 9, "untyped": 1}}}) + "\n")
    src = str(Path(__file__).resolve().parents[1] / "src")
    done = subprocess.run([sys.executable, "-m", "companion_core.knowledge.selective_shadow", "report", str(path)], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, check=True)
    out = json.loads(done.stdout)
    assert out["groups"] == {} and out["suppressed_cells"] == 2  # one cell below 5 and its complement
    assert "untyped" not in done.stdout


def test_nothing_but_vocabulary_names_and_integers_can_be_written(tmp_path):
    tel = ss.SelectiveShadowTelemetry(str(tmp_path / "t.jsonl"), clock=lambda: at(9))
    tel.count("outcome", "Dana Whitfield owns the Ferry queue [E1]")
    tel.count("session-123", "x")
    tel.flush()
    assert rows(tmp_path / "t.jsonl")[0]["groups"] == {"outcome": {"other": 1}}
