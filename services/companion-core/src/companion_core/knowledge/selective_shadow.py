"""Measure-only shadow of selective answering (Phase 44E, owner decision D3 of 2026-10-10; local development only).

Contract, in the order it is enforced:
- Off unless KNOWLEDGE_SELECTIVE_SHADOW_ENABLED=true **and** KNOWLEDGE_RETRIEVAL_ENABLED=true **and** a log path is configured **and** a database is present. Otherwise no object, no query, no file.
  It does not need KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED and never uses the live answerer.
- After the ordinary reply is final, a snapshot of plain data is offered. The offer is constant time and never raises. Nothing the shadow computes is read by the conversation path: it cannot
  add to a prompt, change or delay a reply, a model choice, a consent state, a draft, a memory, a task, an alarm or the robot, and it has no tool and no way to release a reply.
- Everything else happens in one background worker: routing classification (typed, ambiguous, untyped, ineligible), and for typed and ambiguous requests the full deterministic assessment through the
  existing `Retriever` and retrieval-time revalidation under the access context of THAT turn's channel (a spoken turn is public only), reduced to categories and discarded.
- Bounded: a short queue (the oldest job is dropped when full), one job at a time, a per-job timeout. A failure, a timeout or a busy queue only increments a counter.
- Aggregate-only telemetry: every counter name comes from a fixed vocabulary (anything else is recorded as "other"), so a prompt, reply, evidence, title, record id, session id or any other text
  cannot be written by construction. One JSON line per hour window, mode 0600, retention 30 days, deleting the file erases everything.
- No semantic comparison with the production reply. The only production fact recorded is which kind of path produced it (model, deterministic handler, action boundary, selective).
- Reversible: unset the flag and restart; nothing is migrated or written to a database.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import os
import tempfile
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from companion_core.knowledge.retrieval import Retriever
from companion_core.knowledge.selective_answer import (
    SelectiveAnswerer,
    retrieval_enabled,
)
from companion_core.knowledge.shadow_telemetry import LATENCY_EDGES, bucket

log = logging.getLogger("companion_core.knowledge_selective_shadow")

SHADOW_FLAG = "KNOWLEDGE_SELECTIVE_SHADOW_ENABLED"
SCHEMA_VERSION = 1
DEFAULT_QUEUE = 10
DEFAULT_TIMEOUT = 3.0

# The whole vocabulary. A counter outside it is recorded as "other": no text can enter the file.
VOCABULARY: dict[str, frozenset[str]] = {
    "funnel": frozenset({"attempted", "skipped_slash", "skipped_sensitive", "skipped_empty", "admitted", "dropped_busy", "discarded_at_stop", "processed_ok", "failed_error", "failed_timeout"}),
    "class": frozenset({"typed", "ambiguous", "untyped", "ineligible"}),
    "ineligible_reason": frozenset({"not_knowledge", "status_question", "attached_meeting"}),
    "untyped_reason": frozenset({"not_understood", "needs_structured_data"}),
    "anchor": frozenset({"first_person_or_team", "record_noun", "known_term"}),
    "untyped_anchor_strength": frozenset({"single", "multiple"}),  # untyped requests anchored by one kind of evidence (weak) or several (strong): input to a narrower future safeguard
    "production_path": frozenset({"model", "handler", "action_boundary", "selective"}),
    "outcome": frozenset({"answered_supported", "answered_historical", "answered_conflicted", "answered_unsupported", "answered_negative_supported", "answered_negative_unsupported",
                          "answered_order_unsupported", "answered_mixed", "failed_timeout", "failed_retrieval", "failed_not_ready", "failed_pipeline", "failed_verify", "failed_error"}),
    "citations": frozenset({"0", "1", "2", "3+"}),
    "max_sensitivity": frozenset({"none", "public", "work-private"}),
    "modality": frozenset({"text", "voice"}),
    "latency_ms": frozenset(),  # bucket labels are generated from fixed edges
    "record_dependent_untyped_by_path": frozenset({"model", "handler", "action_boundary", "selective"}),  # untyped personal questions, by what answered them: the activation-safety concern
}
ALLOWED_FIELDS = {"schema", "window_start", "groups"}


def selective_shadow_enabled() -> bool:
    return (os.environ.get(SHADOW_FLAG) or "").strip().lower() in ("1", "true", "yes", "on")


def production_path(handler: str) -> str:
    """Kind of path that produced the ordinary reply; a fixed category, not the handler's name."""
    if handler == "generic_chat":
        return "model"
    if handler.startswith("action_boundary"):
        return "action_boundary"
    if handler.startswith("knowledge.selective"):
        return "selective"
    return "handler"


@dataclass(frozen=True)
class SelectiveShadowTurn:
    """Snapshot taken after the reply is final. Plain data only; the text is used to classify and is never stored."""

    session_id: str
    text: str
    modality: str  # "text" or "voice"
    privacy: str  # the production label of the turn
    production_handler: str
    attached_meeting: bool


class SelectiveShadowTelemetry:
    def __init__(self, path: str, *, retention_days: int = 30, flush_seconds: float = 300.0, clock=lambda: datetime.now(UTC)) -> None:
        self.path = Path(path)
        self.retention_days = min(max(int(retention_days), 1), 365)
        self.flush_seconds = flush_seconds
        self._clock = clock
        self._window: datetime | None = None
        self._buf: dict[str, Counter] = collections.defaultdict(Counter)
        self._last_flush = time.monotonic()
        self._last_prune = float("-inf")
        self.total: dict[str, Counter] = collections.defaultdict(Counter)

    def count(self, group: str, name: str, n: int = 1) -> None:
        if group not in VOCABULARY:
            return
        if group != "latency_ms" and name not in VOCABULARY[group]:
            name = "other"
        window = self._clock().replace(minute=0, second=0, microsecond=0)
        if self._window is not None and window != self._window:
            self.flush()
        self._window = window
        self._buf[group][name] += n
        self.total[group][name] += n
        if time.monotonic() - self._last_flush >= self.flush_seconds:
            self.flush()

    def latency(self, ms: float) -> None:
        self.count("latency_ms", bucket(ms, LATENCY_EDGES))

    def flush(self) -> None:
        """Merge the counts since the last flush into the single row of the current hour (created if absent) and rewrite the file atomically. Repeated flushes and restarts therefore leave exactly
        one row per hour, so the file's structure carries no finer timing than the hour. A failed write keeps the counts for the next flush instead of losing them."""
        buf, window = self._buf, self._window
        self._last_flush = time.monotonic()
        if window is None or not any(buf.values()):
            return
        groups = {g: dict(sorted(c.items())) for g, c in sorted(buf.items()) if c}
        row = {"schema": SCHEMA_VERSION, "window_start": window.strftime("%Y-%m-%dT%H:00Z"), "groups": groups}
        assert set(row) <= ALLOWED_FIELDS
        self._buf = collections.defaultdict(Counter)
        try:
            self._rewrite(add=row)
        except OSError:
            for group, counts in groups.items():
                self._buf[group].update(counts)  # retried at the next flush
            self.total["funnel"]["telemetry_write_failed"] += 1

    def _rewrite(self, add: dict | None = None) -> int:
        """Read the file, drop rows past retention and unparsable lines, merge `add` into the row of its hour, write the result through a 0600 temporary file and an atomic replace. Returns the number
        of rows removed. Nothing is written when there is nothing to add and nothing to change."""
        cutoff = (self._clock() - timedelta(days=self.retention_days)).strftime("%Y-%m-%dT%H:00Z")
        rows: dict[str, dict] = {}
        removed = lines_read = 0

        def merge(start: str, groups: dict) -> None:
            merged = rows.setdefault(start, {"schema": SCHEMA_VERSION, "window_start": start, "groups": {}})["groups"]
            for group, counts in groups.items():
                cell = merged.setdefault(group, {})
                for name, n in counts.items():
                    cell[name] = cell.get(name, 0) + int(n)

        if self.path.exists():
            for line in self.path.read_text().splitlines():
                lines_read += 1
                try:
                    row = json.loads(line)
                    start, groups = row["window_start"], row["groups"]
                    if not isinstance(start, str) or not isinstance(groups, dict):
                        raise TypeError
                except (ValueError, KeyError, TypeError):
                    removed += 1
                    continue
                if start < cutoff:
                    removed += 1
                    continue
                merge(start, groups)  # also folds a legacy file that had several rows per hour into one
        if add is not None:
            merge(add["window_start"], add["groups"])
        if add is None and not removed and lines_read == len(rows):
            return 0
        text = "".join(json.dumps({**v, "groups": {g: dict(sorted(c.items())) for g, c in sorted(v["groups"].items())}}, sort_keys=True) + "\n" for _k, v in sorted(rows.items()))
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".kss-")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        return removed

    def prune(self, *, force: bool = False) -> int:
        """Retention: remove rows older than the retention period (at start-up, forced, and at most once a day otherwise). Also merges any legacy duplicate rows of an hour."""
        if not force and time.monotonic() - self._last_prune < 86400:
            return 0
        self._last_prune = time.monotonic()
        try:
            return self._rewrite()
        except OSError:
            self.total["funnel"]["telemetry_write_failed"] += 1
            return 0

    @staticmethod
    def read_totals(path: str) -> dict[str, dict[str, int]]:
        totals: dict[str, Counter] = collections.defaultdict(Counter)
        for line in Path(path).read_text().splitlines():
            for group, counts in json.loads(line)["groups"].items():
                totals[group].update(counts)
        return {g: dict(c) for g, c in totals.items()}


DEFAULT_MIN_CELL = 5


def report(path: str, *, min_cell: int = DEFAULT_MIN_CELL, by: str = "period") -> dict:
    """The only export an operator should read. Sums the hourly rows over the whole file (`by="period"`) or per UTC day (`by="day"`), and **suppresses every cell below `min_cell`** (clamped to at
    least 2): a small count identifies one event. Suppression is complementary inside a group: when exactly one cell of a group is hidden, the smallest visible cell of that group is hidden too, so a
    single hidden value cannot be recovered by subtracting from the other cells of a self-reconciling group (the funnel). Hidden counts are never printed, only how many cells were hidden. Rows are
    hourly at best; no hour is ever reported."""
    k = max(int(min_cell), 2)
    buckets: dict[str, dict[str, Counter]] = collections.defaultdict(lambda: collections.defaultdict(Counter))
    first = last = None
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            row = json.loads(line)
            day = row["window_start"][:10]
            first, last = min(first or day, day), max(last or day, day)
            key = day if by == "day" else "period"
            for group, counts in row["groups"].items():
                buckets[key][group].update(counts)

    def hide(groups: dict[str, Counter]) -> tuple[dict, int]:
        visible: dict[str, dict[str, int]] = {}
        hidden = 0
        for group, counts in sorted(groups.items()):
            cells = {name: n for name, n in counts.items() if n >= k}
            gone = [name for name, n in counts.items() if n < k]
            if len(gone) == 1 and cells:
                smallest = min(cells, key=lambda name: (cells[name], name))
                del cells[smallest]
                gone.append(smallest)
            hidden += len(gone)
            if cells:
                visible[group] = dict(sorted(cells.items()))
        return visible, hidden

    out: dict = {"min_cell": k, "first_day": first, "last_day": last}
    if by == "day":
        out["days"] = {}
        for day, groups in sorted(buckets.items()):
            visible, hidden = hide(groups)
            out["days"][day] = {"groups": visible, "suppressed_cells": hidden}
    else:
        visible, hidden = hide(buckets.get("period", {}))
        out.update({"groups": visible, "suppressed_cells": hidden})
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Suppressed report of the selective shadow telemetry file (counts below --min-cell are never printed).")
    parser.add_argument("command", choices=["report"])
    parser.add_argument("path")
    parser.add_argument("--min-cell", type=int, default=DEFAULT_MIN_CELL)
    parser.add_argument("--by", choices=["period", "day"], default="period")
    args = parser.parse_args(argv)
    print(json.dumps(report(args.path, min_cell=args.min_cell, by=args.by), indent=1, sort_keys=True))
    return 0


def reconcile(funnel: dict[str, int], pending: int = 0) -> int:
    """Admitted jobs that ended nowhere: zero when every admitted job is processed, failed, dropped, discarded or still pending."""
    ended = sum(funnel.get(k, 0) for k in ("dropped_busy", "discarded_at_stop", "processed_ok", "failed_error", "failed_timeout"))
    return funnel.get("admitted", 0) - ended - pending


@dataclass
class SelectiveShadow:
    answerer: SelectiveAnswerer  # a private instance: its counters and live path are never used
    telemetry: SelectiveShadowTelemetry
    queue_size: int = DEFAULT_QUEUE
    timeout_seconds: float = DEFAULT_TIMEOUT
    _pending: collections.deque = field(default_factory=collections.deque)
    _worker: asyncio.Task | None = None
    _stopped: bool = False

    # -- lifecycle ----------------------------------------------------------------------------------------------------------------------
    async def start(self) -> None:
        self.telemetry.prune(force=True)
        await self.answerer.start()

    async def stop(self) -> None:
        self._stopped = True
        worker = self._worker
        if worker is not None and not worker.done():
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(worker), self.timeout_seconds + 1)
            if not worker.done():
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await worker
        if self._pending:
            self.telemetry.count("funnel", "discarded_at_stop", len(self._pending))
            self._pending.clear()
        await self.answerer.stop()
        self.telemetry.flush()

    # -- request path: constant time, never raises ---------------------------------------------------------------------------------------
    def submit(self, turn: SelectiveShadowTurn) -> None:
        tel = self.telemetry
        tel.count("funnel", "attempted")
        if self._stopped:
            tel.count("funnel", "skipped_empty")
            return
        if turn.production_handler == "slash_command" or turn.text.lstrip().startswith("/"):
            tel.count("funnel", "skipped_slash")
            return
        if turn.privacy == "sensitive":
            tel.count("funnel", "skipped_sensitive")
            return
        if not turn.text.strip():
            tel.count("funnel", "skipped_empty")
            return
        tel.count("funnel", "admitted")
        if len(self._pending) >= self.queue_size:
            self._pending.popleft()  # production never waits behind shadow work
            tel.count("funnel", "dropped_busy")
        self._pending.append(turn)
        if self._worker is None or self._worker.done():
            try:
                self._worker = asyncio.get_running_loop().create_task(self._drain())
            except RuntimeError:
                tel.count("funnel", "discarded_at_stop", len(self._pending))
                self._pending.clear()

    # -- background ----------------------------------------------------------------------------------------------------------------------
    async def _drain(self) -> None:
        tel = self.telemetry
        while self._pending and not self._stopped:
            turn = self._pending.popleft()
            started = time.perf_counter()
            try:
                self.answerer.refresh_if_due()
                await asyncio.wait_for(self._measure(turn), self.timeout_seconds + 1)
            except TimeoutError:
                tel.count("funnel", "failed_timeout")
                continue
            except asyncio.CancelledError:
                tel.count("funnel", "discarded_at_stop")
                raise
            except Exception:  # noqa: BLE001 - the shadow path must never surface an error
                tel.count("funnel", "failed_error")
                log.warning("selective shadow job failed")
                continue
            tel.count("funnel", "processed_ok")
            tel.latency((time.perf_counter() - started) * 1000)

    async def drain(self) -> None:  # tests
        worker = self._worker
        if worker is not None:
            await asyncio.gather(worker, return_exceptions=True)

    async def _measure(self, turn: SelectiveShadowTurn) -> None:
        tel = self.telemetry
        path = production_path(turn.production_handler)
        tel.count("modality", turn.modality if turn.modality in ("text", "voice") else "other")
        c = self.answerer.classify(turn.text, attached_meeting=turn.attached_meeting)
        tel.count("class", c.klass)
        tel.count("production_path", path)
        if c.klass == "ineligible":
            tel.count("ineligible_reason", c.reason or "other")
            return
        for anchor in c.anchors:
            tel.count("anchor", anchor)
        if c.klass == "untyped":
            tel.count("untyped_reason", c.reason or "other")
            tel.count("record_dependent_untyped_by_path", path)
            tel.count("untyped_anchor_strength", "multiple" if len(c.anchors) >= 2 else "single")
            return
        a = await self.answerer.assess(turn.text, turn.modality, timeout=self.timeout_seconds)
        tel.count("outcome", a.outcome)
        tel.count("citations", str(a.citations) if a.citations < 3 else "3+")
        tel.count("max_sensitivity", a.max_sensitivity)

    def summary(self) -> dict:
        return {g: dict(c) for g, c in self.telemetry.total.items()}


def from_env(*, retriever: Retriever, index_count: Callable[[], Awaitable[int]], vocabulary=None) -> SelectiveShadow | None:
    """None unless the shadow flag, the retrieval flag and a log path are all present. Bounds come from the environment but are clamped."""
    if not selective_shadow_enabled():
        return None
    if not retrieval_enabled():
        log.warning("%s is set but KNOWLEDGE_RETRIEVAL_ENABLED is not: the selective shadow stays off", SHADOW_FLAG)
        return None
    path = os.environ.get("KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH")
    if not path:
        log.warning("%s is set but KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH is not: the selective shadow stays off", SHADOW_FLAG)
        return None
    timeout = min(max(float(os.environ.get("KNOWLEDGE_SELECTIVE_SHADOW_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT))), 0.2), 5.0)
    return SelectiveShadow(
        answerer=SelectiveAnswerer(retriever=retriever, index_count=index_count, vocabulary=vocabulary, timeout_seconds=timeout),
        telemetry=SelectiveShadowTelemetry(path, retention_days=int(os.environ.get("KNOWLEDGE_SELECTIVE_SHADOW_RETENTION_DAYS", "30"))),
        queue_size=min(max(int(os.environ.get("KNOWLEDGE_SELECTIVE_SHADOW_QUEUE", str(DEFAULT_QUEUE))), 1), 20), timeout_seconds=timeout)


__all__ = ["ALLOWED_FIELDS", "DEFAULT_MIN_CELL", "SHADOW_FLAG", "VOCABULARY", "SelectiveShadow", "SelectiveShadowTelemetry", "SelectiveShadowTurn", "from_env", "main", "production_path", "reconcile", "report", "selective_shadow_enabled"]


if __name__ == "__main__":  # python -m companion_core.knowledge.selective_shadow report <path>
    raise SystemExit(main())
