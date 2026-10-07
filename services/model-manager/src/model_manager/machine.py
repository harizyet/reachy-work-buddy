"""The model manager state machine (Phase 42B, ADR 0031).

READY_T1 -> SWITCHING_TO_T2 -> READY_T2 -> RESTORING_T1 -> READY_T1, plus FAILED. Deliberately boring: it owns model
lifecycle, configuration and recovery, and nothing about routing policy, escalation or scheduling. Its invariants:

* one transition at a time; a second request for the same target joins it, a conflicting one is refused;
* T2 is never declared ready because a container started, only after /health and a real completion succeed;
* any failure on the way to or while in T2 ends in an attempt to restore T1, and a failed restore ends in FAILED
  after a bounded number of attempts, never an endless loop;
* a deep lease expires on its own and restores T1, so a vanished caller cannot strand the GPU on the deep model;
* state is learned from the host (`reconcile`), never from a remembered file."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from model_manager.config import ManagerConfig
from model_manager.runtime import ReadyTimeout, Runtime
from shared.models.model_manager import (
    ManagerState,
    ManagerStatus,
    ModelTier,
    TransitionRecord,
)

log = logging.getLogger(__name__)
HISTORY_LIMIT = 500


class Busy(Exception):
    """A transition to a different target is already running."""


class NotAllowed(Exception):
    """The request cannot be honoured in the current state (for example a deep switch while FAILED)."""


class TierSwitchFailed(Exception):
    def __init__(self, message: str, *, restored: bool) -> None:
        super().__init__(message)
        self.restored = restored


class RestoreFailed(Exception):
    """The fast tier could not be brought back. The manager is FAILED and needs the owner."""


class JobFailed(Exception):
    """The deep job raised. The fast tier has already been restored (or RestoreFailed was raised instead)."""


@dataclass
class _Lease:
    task: asyncio.Task[None]
    expires_at: datetime


class ModelManager:
    def __init__(
        self, runtime: Runtime, config: ManagerConfig, *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._rt, self._cfg, self._now, self._sleep = runtime, config, now, sleep
        self._state: ManagerState | None = None
        self._since = now()
        self._last_error: str | None = None
        self._inflight: asyncio.Future[Any] | None = None
        self._inflight_target: ModelTier | None = None
        self._lease: _Lease | None = None
        self._history: list[TransitionRecord] = []
        self._next_id = 1
        self._t2_entered: datetime | None = None
        self.counters = {
            "swaps_to_t2": 0, "t2_start_failures": 0, "restores": 0, "restore_failures": 0, "lease_expiries": 0,
            "jobs_completed": 0, "jobs_failed": 0, "time_in_t2_s": 0.0,
            "t2_start_retries": 0, "t2_crashes": 0, "fallbacks_to_t1": 0,
        }
        self._watch_task: asyncio.Task[None] | None = None

    # ---- observation -------------------------------------------------------------------------------------

    def status(self) -> ManagerStatus:
        if self._state is None:
            raise NotAllowed("the manager has not reconciled with the host yet")
        tier = {ManagerState.READY_T1: ModelTier.T1, ManagerState.READY_T2: ModelTier.T2}.get(self._state)
        return ManagerStatus(
            state=self._state, tier=tier, served_model_name=self._cfg.served_model_name,
            model=self._cfg.tier(tier).model if tier else None, since=self._since,
            lease_expires_at=self._lease.expires_at if self._lease else None, last_error=self._last_error,
            transition_in_progress=bool(self._inflight and not self._inflight.done()),
        )

    def transitions(self, limit: int = 50) -> list[TransitionRecord]:
        return self._history[-limit:][::-1]

    @property
    def endpoint(self) -> str:
        return self._cfg.endpoint

    # ---- public operations ---------------------------------------------------------------------------------

    async def start(self) -> ManagerStatus:
        """Learn the real state from the host and repair it if it is not a clean tier 1."""
        return await self.reconcile()

    async def reconcile(self) -> ManagerStatus:
        async def flow() -> None:
            t1, t2 = await self._rt.is_running(ModelTier.T1), await self._rt.is_running(ModelTier.T2)
            if t2 and not t1 and await self._rt.is_ready(ModelTier.T2):
                self._enter(ManagerState.READY_T2)
                self._record("reconcile", None, ManagerState.READY_T2, ModelTier.T2, self._now(), None)
                self._arm_lease(self._cfg.default_lease_s)
                self._start_watch()
            elif t1 and not t2 and await self._rt.is_ready(ModelTier.T1):
                self._enter(ManagerState.READY_T1)
                self._record("reconcile", None, ManagerState.READY_T1, ModelTier.T1, self._now(), None)
            elif not await self._restore("reconcile"):
                raise RestoreFailed(self._last_error or "restore failed")

        await self._exclusive(ModelTier.T1, flow)
        return self.status()

    def _require_reconciled(self) -> None:
        if self._state is None:  # no request may race the startup reconcile that learns the host's real state
            raise NotAllowed("the manager is still reconciling with the host")

    async def activate(self, tier: ModelTier, lease_seconds: float | None = None) -> ManagerStatus:
        self._require_reconciled()
        if tier == ModelTier.T1:
            return await self.restore()
        if self._state == ManagerState.READY_T2:  # idempotent: only extends the lease
            self._arm_lease(self._clamp_lease(lease_seconds))
            return self.status()
        if self._state == ManagerState.FAILED:
            raise NotAllowed("the fast tier is not running; restore it first")
        await self._exclusive(ModelTier.T2, lambda: self._switch_to_t2(self._clamp_lease(lease_seconds)))
        return self.status()

    async def restore(self) -> ManagerStatus:
        self._require_reconciled()
        if self._state == ManagerState.READY_T1 and not self._busy():
            return self.status()  # idempotent

        async def flow() -> None:
            if not await self._restore("requested"):
                raise RestoreFailed(self._last_error or "restore failed")

        await self._exclusive(ModelTier.T1, flow)
        return self.status()

    async def run_job(self, job: Callable[[str], Awaitable[Any]], lease_seconds: float | None = None) -> Any:
        """Switch to tier 2, run `job(endpoint)`, and always restore tier 1, whatever the job does."""
        await self.activate(ModelTier.T2, lease_seconds)  # a failed switch has already restored tier 1
        failure: BaseException | None = None
        result: Any = None
        try:
            result = await job(self._cfg.endpoint)
        except asyncio.CancelledError:
            await asyncio.shield(self._settle_and_restore())  # a cancelled job must not strand the deep tier either
            raise
        except Exception as exc:  # noqa: BLE001 - any job failure must still restore tier 1
            failure = exc
            self.counters["jobs_failed"] += 1
        else:
            self.counters["jobs_completed"] += 1
        await self._settle()  # the watchdog may be mid-recovery after a crash: wait for it rather than get Busy
        await self.restore()  # raises RestoreFailed if tier 1 cannot come back
        if failure is not None:
            raise JobFailed(str(failure)) from failure
        return result

    async def _settle(self) -> None:
        if self._busy():
            await asyncio.gather(asyncio.shield(self._inflight), return_exceptions=True)  # type: ignore[arg-type]

    async def _settle_and_restore(self) -> None:
        await self._settle()
        await self.restore()

    async def close(self) -> None:
        """Manager shutdown: never leave the host on the deep model."""
        if self._state in (ManagerState.READY_T2, ManagerState.SWITCHING_TO_T2):
            try:
                await self.restore()
            except (Busy, RestoreFailed, NotAllowed):
                log.exception("could not restore the fast tier while shutting down")
        self._cancel_lease()
        self._stop_watch()

    # ---- internals ---------------------------------------------------------------------------------------

    def _busy(self) -> bool:
        return bool(self._inflight and not self._inflight.done())

    async def _exclusive(self, target: ModelTier, flow: Callable[[], Awaitable[None]]) -> None:
        if self._busy():
            if self._inflight_target == target:
                await asyncio.shield(self._inflight)  # type: ignore[arg-type]
                return
            raise Busy("another transition is in progress")
        self._inflight_target = target
        self._inflight = asyncio.ensure_future(flow())
        # Callers get the outcome through the shielded await; this only stops a handled failure being logged twice.
        self._inflight.add_done_callback(lambda f: f.cancelled() or f.exception())
        # Shielded: a caller that disconnects must not cancel a swap halfway and strand the GPU.
        await asyncio.shield(self._inflight)

    def _enter(self, state: ManagerState) -> None:
        if self._state == ManagerState.READY_T2 and state != ManagerState.READY_T2 and self._t2_entered:
            self.counters["time_in_t2_s"] += (self._now() - self._t2_entered).total_seconds()
            self._t2_entered = None
        if state == ManagerState.READY_T2 and self._state != ManagerState.READY_T2:
            self._t2_entered = self._now()
        if state != ManagerState.READY_T2:
            self._cancel_lease()
            if state != ManagerState.SWITCHING_TO_T2:  # a recovery switch must not cancel the watchdog that runs it
                self._stop_watch()
        if state != self._state:
            self._since = self._now()
        self._state = state

    def _record(
        self, kind: str, from_state: ManagerState | None, to_state: ManagerState, tier: ModelTier,
        started: datetime, error: str | None,
    ) -> None:
        ended = self._now()
        record = TransitionRecord(
            id=self._next_id, kind=kind, from_state=from_state, to_state=to_state, tier=tier,
            model=self._cfg.tier(tier).model, started_at=started, ended_at=ended,
            duration_s=round((ended - started).total_seconds(), 3), outcome="failed" if error else "ok", error=error,
        )
        self._next_id += 1
        self._history = [*self._history, record][-HISTORY_LIMIT:]
        if self._cfg.transitions_log:
            try:
                with Path(self._cfg.transitions_log).open("a") as stream:
                    stream.write(json.dumps(record.model_dump(mode="json")) + "\n")
            except OSError:
                log.warning("could not append to the transitions log")

    async def _step(
        self, kind: str, working: ManagerState, done: ManagerState, tier: ModelTier,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        origin, started = self._state, self._now()
        self._enter(working)
        try:
            await action()
        except Exception as exc:
            self._last_error = str(exc)[:300]
            self._record(kind, origin, working, tier, started, self._last_error)
            raise
        self._enter(done)
        self._last_error = None
        self._record(kind, origin, done, tier, started, None)

    async def _switch_to_t2(self, lease_s: float, *, recovering: bool = False) -> None:
        async def action() -> None:
            await self._rt.stop_tier(ModelTier.T1)
            await self._rt.start_tier(ModelTier.T2)
            await self._rt.wait_ready(ModelTier.T2, self._cfg.t2_ready_timeout_s)

        failure: Exception | None = None
        for attempt in range(1 + self._cfg.t2_start_retries):
            if attempt:
                self.counters["t2_start_retries"] += 1
                await self._sleep(self._cfg.t2_retry_delay_s)
            try:
                await self._step(
                    "recover_t2" if recovering else "activate_t2", ManagerState.SWITCHING_TO_T2,
                    ManagerState.READY_T2, ModelTier.T2, action,
                )
            except Exception as exc:  # noqa: BLE001 - every start failure is retried, then falls back to tier 1
                failure = exc
                self.counters["t2_start_failures"] += 1
                if isinstance(exc, ReadyTimeout):
                    break  # slow, not crashed: another attempt would only cost another timeout
                continue
            self.counters["swaps_to_t2"] += 0 if recovering else 1
            self._arm_lease(lease_s)
            self._start_watch()
            return
        note = f"deep tier failed ({str(failure)[:160]}); serving from the fast tier until it is activated again"
        restored = await self._restore("t2 start failed", note=note)
        raise TierSwitchFailed(str(failure), restored=restored) from failure

    async def _restore(self, reason: str, *, note: str | None = None) -> bool:
        """Bring tier 1 back. Bounded: one attempt plus `restore_retries`, then FAILED. Returns success. `note` stays
        visible as last_error (a degraded-but-serving marker) until the next successful switch."""

        async def action() -> None:
            await self._rt.stop_tier(ModelTier.T2)
            if not await self._rt.is_running(ModelTier.T1):  # a tier 1 that is already starting is left alone
                await self._rt.start_tier(ModelTier.T1)
            await self._rt.wait_ready(ModelTier.T1, self._cfg.t1_ready_timeout_s)

        last = ""
        for _ in range(1 + self._cfg.restore_retries):
            try:
                await self._step("restore_t1", ManagerState.RESTORING_T1, ManagerState.READY_T1, ModelTier.T1, action)
            except Exception as exc:  # noqa: BLE001
                last = str(exc)[:300]
                continue
            self.counters["restores"] += 1
            if note:
                self.counters["fallbacks_to_t1"] += 1
                self._last_error = note
            return True
        self.counters["restore_failures"] += 1
        started = self._now()
        self._enter(ManagerState.FAILED)
        self._last_error = f"could not restore the fast tier ({reason}): {last}"
        self._record("enter_failed", ManagerState.RESTORING_T1, ManagerState.FAILED, ModelTier.T1, started, self._last_error)
        log.error(self._last_error)
        return False

    # ---- watchdog ----------------------------------------------------------------------------------------

    def _start_watch(self) -> None:
        self._stop_watch()
        self._watch_task = asyncio.ensure_future(self._watch())

    def _stop_watch(self) -> None:
        if self._watch_task and self._watch_task is not asyncio.current_task():
            self._watch_task.cancel()
        self._watch_task = None

    async def _watch(self) -> None:
        """While the deep tier is loaded, notice a crash or hang and recover without the owner: restart it once, and
        if it still fails the fast tier is loaded so local service comes back. It never re-enters the deep tier by
        itself afterwards."""
        bad = 0
        while True:
            await self._sleep(self._cfg.watch_interval_s)
            if self._state != ManagerState.READY_T2 or self._busy():
                bad = 0
                if self._state != ManagerState.READY_T2 and not self._busy():
                    return
                continue
            if not await self._rt.is_running(ModelTier.T2):
                bad = self._cfg.watch_unhealthy_checks  # a dead container needs no second opinion
            elif not await self._rt.is_ready(ModelTier.T2):
                bad += 1
            else:
                bad = 0
            if bad < self._cfg.watch_unhealthy_checks:
                continue
            bad = 0
            self.counters["t2_crashes"] += 1
            log.warning("deep tier crashed or hung; trying to recover it")
            try:
                await self._exclusive(ModelTier.T2, lambda: self._recover_t2())
            except (TierSwitchFailed, RestoreFailed, Busy):
                log.exception("deep tier recovery ended on the fast tier or failed")
            if self._state != ManagerState.READY_T2:
                return

    async def _recover_t2(self) -> None:
        """The loaded deep tier died: the same bounded start-with-retry, then the fast-tier fallback."""
        lease = self._lease.expires_at if self._lease else None
        remaining = max((lease - self._now()).total_seconds(), 60.0) if lease else self._cfg.default_lease_s
        await self._switch_to_t2(remaining, recovering=True)

    # ---- lease -------------------------------------------------------------------------------------------

    def _clamp_lease(self, seconds: float | None) -> float:
        return min(max(seconds if seconds is not None else self._cfg.default_lease_s, 1.0), self._cfg.max_lease_s)

    def _arm_lease(self, seconds: float) -> None:
        self._cancel_lease()
        expires = self._now() + timedelta(seconds=seconds)
        self._lease = _Lease(asyncio.ensure_future(self._expire_after(seconds)), expires)

    def _cancel_lease(self) -> None:
        if self._lease and self._lease.task is not asyncio.current_task():
            self._lease.task.cancel()
        self._lease = None

    async def _expire_after(self, seconds: float) -> None:
        await self._sleep(seconds)
        if self._state != ManagerState.READY_T2 or self._busy():
            return
        self.counters["lease_expiries"] += 1
        log.warning("deep tier lease expired; restoring the fast tier")
        try:
            await self.restore()
        except (Busy, RestoreFailed, NotAllowed):
            log.exception("lease expiry could not restore the fast tier")
