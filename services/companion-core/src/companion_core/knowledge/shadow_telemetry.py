"""Aggregate-only telemetry for the knowledge shadow (schema version 1).

One JSON line per flush per hour window, holding counts and bucketed histograms and nothing else: no query text or hash, no evidence, no titles, no record
identifiers, no session or user identifiers, no per-turn rows. Minute-level timestamps are not kept: the window is the hour. A consumer sums the rows.

Funnel, each stage counted separately and reconcilable (see `reconcile`):
  attempted          every generic-chat turn offered to the shadow
  skipped_*          not eligible: slash command, sensitive-labelled turn, empty text
  not_qualifying     eligible but not a knowledge question (knowledge/qualify.py)
  admitted           qualifying and queued
  dropped_busy       admitted, then evicted from a full queue before it ran
  discarded_at_stop  admitted, still queued when the process stopped
  processed_ok       the job ran to completion (including a `phase43` pass-through and an empty result)
  failed_error       the job raised
  failed_timeout     the job exceeded its time limit
`evaluated_qualifying` is the number the 14-day, 50-query criterion counts: processed_ok jobs that actually ran status routing or retrieval.

Retention: rows older than `retention_days` (default 30, clamped to 1..365) are removed at start and once a day; the file is 0600; deleting it erases everything."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = 1
LATENCY_EDGES = (5, 10, 25, 50, 100, 250, 1000)
TOKEN_EDGES = (0, 250, 500, 1000, 1500)
ITEM_EDGES = (0, 2, 5, 10)
FUNNEL = ("attempted", "skipped_slash", "skipped_sensitive", "skipped_empty", "not_qualifying", "admitted", "dropped_busy", "discarded_at_stop",
          "processed_ok", "failed_error", "failed_timeout")
ALLOWED_FIELDS = {"schema", "window_start", "counts", "evaluated_qualifying", "by_path", "by_modality", "by_intent", "max_sensitivity", "empty_results",
                  "revalidation_dropped", "builder_dropped", "latency_ms", "evidence_tokens", "items_in_context"}


def bucket(value: float, edges: tuple[int, ...]) -> str:
    previous = 0
    for edge in edges:
        if value <= edge:
            return f"<={edge}" if previous == 0 else f"{previous}-{edge}"
        previous = edge
    return f">{edges[-1]}"


def reconcile(counts: dict[str, int], pending: int = 0) -> dict[str, int]:
    """Differences that should be zero: every attempt is accounted for, and every admitted job ends in exactly one place (or is still pending)."""
    skipped = sum(counts.get(k, 0) for k in ("skipped_slash", "skipped_sensitive", "skipped_empty"))
    ended = sum(counts.get(k, 0) for k in ("dropped_busy", "discarded_at_stop", "processed_ok", "failed_error", "failed_timeout"))
    return {"attempted_unaccounted": counts.get("attempted", 0) - skipped - counts.get("not_qualifying", 0) - counts.get("admitted", 0),
            "admitted_unaccounted": counts.get("admitted", 0) - ended - pending}


class ShadowTelemetry:
    def __init__(self, path: str, *, retention_days: int = 30, flush_seconds: float = 300.0, clock=lambda: datetime.now(UTC)) -> None:
        self.path = Path(path)
        self.retention_days = min(max(int(retention_days), 1), 365)
        self.flush_seconds = flush_seconds
        self._clock = clock
        self._window: datetime | None = None
        self._buf: dict = self._fresh()
        self._last_flush = time.monotonic()
        self._last_prune = float("-inf")
        self.total = Counter()  # since this process started, for tests and the shutdown log line

    @staticmethod
    def _fresh() -> dict:
        return {"counts": Counter(), "evaluated_qualifying": 0, "by_path": Counter(), "by_modality": Counter(), "by_intent": Counter(), "max_sensitivity": Counter(),
                "empty_results": 0, "revalidation_dropped": Counter(), "builder_dropped": Counter(), "latency_ms": Counter(), "evidence_tokens": Counter(),
                "items_in_context": Counter()}

    def _roll(self) -> None:
        window = self._clock().replace(minute=0, second=0, microsecond=0)
        if self._window is not None and window != self._window:
            self.flush()
        self._window = window

    def count(self, stage: str, n: int = 1) -> None:
        self._roll()
        self._buf["counts"][stage] += n
        self.total[stage] += n
        self._maybe_flush()

    def job(self, *, path: str, modality: str, intent: str | None, latency_ms: float, measured: dict | None) -> None:
        """A job that ran to completion. `measured` holds the numbers of a status or retrieval pass; a pass-through has none."""
        self._roll()
        b = self._buf
        b["counts"]["processed_ok"] += 1
        self.total["processed_ok"] += 1
        b["by_path"][path] += 1
        b["by_modality"][modality] += 1
        b["latency_ms"][bucket(latency_ms, LATENCY_EDGES)] += 1
        if intent:
            b["by_intent"][intent] += 1
        if measured is not None:
            b["evaluated_qualifying"] += 1
            self.total["evaluated_qualifying"] += 1
            b["max_sensitivity"][measured["max_sensitivity"]] += 1
            b["evidence_tokens"][bucket(measured["evidence_tokens"], TOKEN_EDGES)] += 1
            b["items_in_context"][bucket(measured["items_in_context"], ITEM_EDGES)] += 1
            b["empty_results"] += 1 if measured["items_returned"] == 0 else 0
            for reason, n in measured["revalidation_dropped"].items():
                b["revalidation_dropped"][reason] += n
            for reason, n in measured["builder_dropped"].items():
                b["builder_dropped"][reason] += n
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_seconds:
            self.flush()

    def flush(self) -> None:
        buf, window = self._buf, self._window
        if window is None or not (buf["counts"] or buf["evaluated_qualifying"]):
            self._last_flush = time.monotonic()
            return
        row = {"schema": SCHEMA_VERSION, "window_start": window.strftime("%Y-%m-%dT%H:00Z"), "counts": dict(sorted(buf["counts"].items())),
               "evaluated_qualifying": buf["evaluated_qualifying"]}
        for key in ("by_path", "by_modality", "by_intent", "max_sensitivity", "revalidation_dropped", "builder_dropped", "latency_ms", "evidence_tokens", "items_in_context"):
            row[key] = dict(sorted(buf[key].items()))
        row["empty_results"] = buf["empty_results"]
        assert set(row) <= ALLOWED_FIELDS
        self._buf = self._fresh()
        self._last_flush = time.monotonic()
        try:
            self.prune()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except OSError:
            self.total["telemetry_write_failed"] += 1

    def prune(self, *, force: bool = False) -> int:
        """Drop rows older than the retention period (at most once a day unless forced). Returns the number removed."""
        if not force and time.monotonic() - self._last_prune < 86400:
            return 0
        self._last_prune = time.monotonic()
        if not self.path.exists():
            return 0
        cutoff = (self._clock() - timedelta(days=self.retention_days)).strftime("%Y-%m-%dT%H:00Z")
        kept, removed = [], 0
        for line in self.path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                removed += 1
                continue
            if row.get("window_start", "") >= cutoff:
                kept.append(line)
            else:
                removed += 1
        if removed:
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ks-")
            with os.fdopen(fd, "w") as handle:
                handle.write("".join(line + "\n" for line in kept))
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        return removed

    @staticmethod
    def read_totals(path: str) -> dict:
        """Sum a telemetry file: what an operator would read to count qualifying evaluations."""
        totals: Counter = Counter()
        evaluated = 0
        for line in Path(path).read_text().splitlines():
            row = json.loads(line)
            totals.update(row["counts"])
            evaluated += row["evaluated_qualifying"]
        return {"counts": dict(totals), "evaluated_qualifying": evaluated}
