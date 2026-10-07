"""Phase 42B acceptance: the failure paths, with injected faults, not just the happy path."""

import asyncio

import pytest
from model_manager.machine import (
    Busy,
    JobFailed,
    NotAllowed,
    RestoreFailed,
    TierSwitchFailed,
)

from shared.models.model_manager import ManagerState, ModelTier

pytestmark = pytest.mark.anyio
T1, T2 = ModelTier.T1, ModelTier.T2


async def test_reconcile_on_a_clean_host_is_ready_t1(make_manager) -> None:
    manager = make_manager()
    status = await manager.start()
    assert status.state == ManagerState.READY_T1 and status.tier == T1
    assert status.served_model_name == "reachy-local" and status.model == "Qwen/Qwen2.5-7B-Instruct-AWQ"


async def test_activate_t2_then_restore_happy_path(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    status = await manager.activate(T2)
    assert status.state == ManagerState.READY_T2 and status.model == "Qwen/Qwen3-14B-AWQ"
    assert status.served_model_name == "reachy-local"  # the API identity never changes with the tier
    assert status.lease_expires_at is not None
    assert runtime.running == {T1: False, T2: True}
    status = await manager.restore()
    assert status.state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}
    assert [(r.kind, r.outcome) for r in reversed(manager.transitions())][-2:] == [("activate_t2", "ok"), ("restore_t1", "ok")]


async def test_activate_t2_while_on_t2_is_idempotent_and_only_extends_the_lease(make_manager, runtime, clock) -> None:
    manager = make_manager()
    await manager.start()
    first = await manager.activate(T2, lease_seconds=100)
    calls_before = list(runtime.calls)
    await clock.advance(50)
    second = await manager.activate(T2, lease_seconds=100)
    assert runtime.calls == calls_before  # nothing was stopped or started again
    assert second.lease_expires_at > first.lease_expires_at
    assert manager.counters["swaps_to_t2"] == 1


async def test_restore_on_t1_is_idempotent(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    calls = list(runtime.calls)
    await manager.restore()
    await manager.activate(T1)
    assert runtime.calls == calls


async def test_only_one_transition_at_a_time(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    runtime.gate(T2)  # hold the deep tier "loading"
    first = asyncio.ensure_future(manager.activate(T2))
    second = asyncio.ensure_future(manager.activate(T2))  # same target: joins, does not start a second swap
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert manager.status().state == ManagerState.SWITCHING_TO_T2 and manager.status().transition_in_progress
    with pytest.raises(Busy):  # a conflicting request is refused rather than queued
        await manager.restore()
    runtime.gate(T2).set()
    assert (await first).state == (await second).state == ManagerState.READY_T2
    assert runtime.count("start", T2) == 1 and runtime.count("stop", T1) == 1


async def test_t2_is_not_ready_just_because_the_container_started(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    runtime.gate(T2)
    task = asyncio.ensure_future(manager.activate(T2))
    for _ in range(5):
        await asyncio.sleep(0)
    assert runtime.running[T2] is True  # started...
    assert manager.status().state == ManagerState.SWITCHING_TO_T2  # ...but not declared ready
    runtime.gate(T2).set()
    assert (await task).state == ManagerState.READY_T2


async def test_a_t2_startup_failure_restores_t1_automatically(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    runtime.inject("wait", T2)  # the deep model never becomes ready
    with pytest.raises(TierSwitchFailed) as raised:
        await manager.activate(T2)
    assert raised.value.restored is True
    status = manager.status()
    assert status.state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}
    kinds = [(r.kind, r.outcome) for r in reversed(manager.transitions())]
    assert kinds[-2:] == [("activate_t2", "failed"), ("restore_t1", "ok")]
    assert manager.counters["t2_start_failures"] == 1


@pytest.mark.parametrize("op", ["stop", "start", "wait"])
async def test_a_failure_at_every_step_of_the_switch_still_ends_on_t1(make_manager, runtime, op) -> None:
    manager = make_manager()
    await manager.start()
    runtime.inject(op, T1 if op == "stop" else T2)
    with pytest.raises(TierSwitchFailed):
        await manager.activate(T2)
    assert manager.status().state == ManagerState.READY_T1 and runtime.running[T1] is True


async def test_a_deep_job_failure_still_restores_t1(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()

    async def broken(endpoint: str) -> None:
        raise ValueError("job blew up")

    with pytest.raises(JobFailed, match="job blew up"):
        await manager.run_job(broken)
    assert manager.status().state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}
    assert manager.counters["jobs_failed"] == 1


async def test_a_cancelled_deep_job_still_restores_t1(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    started = asyncio.Event()

    async def hangs(endpoint: str) -> None:
        started.set()
        await asyncio.sleep(3600)

    task = asyncio.ensure_future(manager.run_job(hangs))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.status().state == ManagerState.READY_T1 and runtime.running[T1] is True


async def test_a_successful_job_returns_its_result_and_restores(make_manager) -> None:
    manager = make_manager()
    await manager.start()

    async def work(endpoint: str) -> str:
        assert manager.status().state == ManagerState.READY_T2
        return f"done via {endpoint}"

    assert await manager.run_job(work) == "done via http://127.0.0.1:8003"
    assert manager.status().state == ManagerState.READY_T1 and manager.counters["jobs_completed"] == 1


async def test_a_failed_restore_is_bounded_and_ends_in_failed(make_manager, runtime) -> None:
    manager = make_manager(restore_retries=1)
    await manager.start()
    await manager.activate(T2)
    runtime.inject("wait", T1, times=None)  # the fast tier never comes back
    with pytest.raises(RestoreFailed):
        await manager.restore()
    assert manager.status().state == ManagerState.FAILED
    assert "could not restore the fast tier" in manager.status().last_error
    assert runtime.count("wait", T1) == 2  # one attempt plus one retry, never an endless loop
    assert manager.counters["restore_failures"] == 1


async def test_t2_failure_plus_restore_failure_is_failed_not_a_loop(make_manager, runtime) -> None:
    manager = make_manager(restore_retries=2)
    await manager.start()
    runtime.inject("wait", T2)
    runtime.inject("start", T1, times=None)
    runtime.running[T1] = True  # stop_tier(T1) will clear it; start then keeps failing
    with pytest.raises(TierSwitchFailed) as raised:
        await manager.activate(T2)
    assert raised.value.restored is False
    assert manager.status().state == ManagerState.FAILED
    assert runtime.count("start", T1) == 3  # 1 + 2 retries, then it stopped trying


async def test_failed_refuses_a_deep_switch_until_restored_manually(make_manager, runtime) -> None:
    manager = make_manager(restore_retries=0)
    await manager.start()
    await manager.activate(T2)
    runtime.inject("start", T1, times=None)
    with pytest.raises(RestoreFailed):
        await manager.restore()
    with pytest.raises(NotAllowed):
        await manager.activate(T2)
    runtime.clear_faults()  # the owner fixed the problem
    status = await manager.restore()  # an explicit retry is allowed from FAILED
    assert status.state == ManagerState.READY_T1 and status.last_error is None


async def test_the_lease_expiry_restores_t1_when_the_caller_vanishes(make_manager, runtime, clock) -> None:
    manager = make_manager()
    await manager.start()
    await manager.activate(T2, lease_seconds=300)
    await clock.advance(299)
    assert manager.status().state == ManagerState.READY_T2
    await clock.advance(2)
    assert manager.status().state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}
    assert manager.counters["lease_expiries"] == 1


async def test_lease_is_clamped_to_the_maximum(make_manager) -> None:
    manager = make_manager(max_lease_s=600.0)
    await manager.start()
    status = await manager.activate(T2, lease_seconds=99999)
    assert (status.lease_expires_at - status.since).total_seconds() <= 600


async def test_a_caller_that_disconnects_does_not_abort_a_swap(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    runtime.gate(T2)
    caller = asyncio.ensure_future(manager.activate(T2))
    for _ in range(3):
        await asyncio.sleep(0)
    caller.cancel()  # e.g. an HTTP client gave up
    with pytest.raises(asyncio.CancelledError):
        await caller
    runtime.gate(T2).set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert manager.status().state == ManagerState.READY_T2  # the swap completed rather than stranding the GPU


# ---- reconciliation: reality, not a remembered state --------------------------------------------------------

async def test_reconcile_adopts_a_running_healthy_t2_with_a_default_lease(make_manager, runtime) -> None:
    runtime.running = {T1: False, T2: True}
    manager = make_manager()
    status = await manager.start()
    assert status.state == ManagerState.READY_T2 and status.lease_expires_at is not None


async def test_reconcile_with_nothing_running_starts_t1(make_manager, runtime) -> None:
    runtime.running = {T1: False, T2: False}
    status = await make_manager().start()
    assert status.state == ManagerState.READY_T1 and runtime.running[T1] is True


async def test_reconcile_with_both_running_stops_the_deep_tier(make_manager, runtime) -> None:
    runtime.running = {T1: True, T2: True}
    status = await make_manager().start()
    assert status.state == ManagerState.READY_T1 and runtime.running[T2] is False


async def test_reconcile_with_an_unready_deep_tier_goes_back_to_t1(make_manager, runtime) -> None:
    runtime.running = {T1: False, T2: True}
    runtime.ready[T2] = False
    status = await make_manager().start()
    assert status.state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}


async def test_reconcile_that_cannot_start_t1_is_failed(make_manager, runtime) -> None:
    runtime.running = {T1: False, T2: False}
    runtime.inject("start", T1, times=None)
    manager = make_manager(restore_retries=0)
    with pytest.raises(RestoreFailed):
        await manager.start()
    assert manager.status().state == ManagerState.FAILED


async def test_a_running_but_still_loading_t1_is_waited_for_not_restarted(make_manager, runtime) -> None:
    runtime.running = {T1: True, T2: False}
    runtime.ready[T1] = False  # container up, model still loading
    manager = make_manager()
    task = asyncio.ensure_future(manager.start())
    for _ in range(3):
        await asyncio.sleep(0)
    runtime.ready[T1] = True
    assert (await task).state == ManagerState.READY_T1
    assert runtime.count("start", T1) == 0 and runtime.count("stop", T1) == 0


# ---- records ------------------------------------------------------------------------------------------------

async def test_every_transition_records_model_times_duration_outcome_and_error(make_manager, runtime, clock) -> None:
    manager = make_manager()
    await manager.start()
    runtime.inject("wait", T2)
    with pytest.raises(TierSwitchFailed):
        await manager.activate(T2)
    for record in manager.transitions():
        assert record.model and record.started_at <= record.ended_at and record.duration_s >= 0
        assert record.outcome in {"ok", "failed"} and (record.error is not None) == (record.outcome == "failed")
    failed = next(r for r in manager.transitions() if r.outcome == "failed")
    assert failed.kind == "activate_t2" and failed.model == "Qwen/Qwen3-14B-AWQ" and "injected wait failure" in failed.error


async def test_the_transitions_log_is_append_only_history_never_state(make_manager, tmp_path) -> None:
    log = tmp_path / "transitions.jsonl"
    manager = make_manager(transitions_log=str(log))
    await manager.start()
    await manager.activate(T2)
    await manager.restore()
    lines = [line for line in log.read_text().splitlines() if line]
    assert len(lines) >= 3 and all('"outcome"' in line for line in lines)
    fresh = make_manager(transitions_log=str(log))  # a new manager ignores the old log and reads the host
    assert (await fresh.start()).state == ManagerState.READY_T1


async def test_time_in_t2_and_swap_counters_accumulate(make_manager, clock) -> None:
    manager = make_manager()
    await manager.start()
    await manager.activate(T2, lease_seconds=3600)
    await clock.advance(120)
    await manager.restore()
    assert manager.counters["swaps_to_t2"] == 1 and manager.counters["restores"] >= 1
    assert manager.counters["time_in_t2_s"] == pytest.approx(120, abs=1)


async def test_close_restores_t1_so_a_manager_shutdown_never_strands_the_deep_model(make_manager, runtime) -> None:
    manager = make_manager()
    await manager.start()
    await manager.activate(T2)
    await manager.close()
    assert runtime.running == {T1: True, T2: False}


# ---- automated recovery: retry, then fall back to the fast tier, then wait for the owner -------------------------

from model_manager.runtime import ReadyTimeout


async def test_a_failed_deep_start_is_retried_once_and_the_retry_can_succeed(make_manager, runtime) -> None:
    manager = make_manager(t2_start_retries=1)
    await manager.start()
    runtime.inject("start", T2, times=1)  # the first launch fails, the second works
    status = await manager.activate(T2)
    assert status.state == ManagerState.READY_T2 and status.last_error is None
    assert manager.counters["t2_start_retries"] == 1 and manager.counters["fallbacks_to_t1"] == 0
    assert runtime.count("start", T1) == 0  # the fast tier was never needed
    outcomes = [(r.kind, r.outcome) for r in reversed(manager.transitions())]
    assert outcomes[-2:] == [("activate_t2", "failed"), ("activate_t2", "ok")]


async def test_when_the_retry_also_fails_the_fast_tier_is_loaded_and_stays_until_asked_again(
    make_manager, runtime, clock
) -> None:
    manager = make_manager(t2_start_retries=1)
    await manager.start()
    runtime.inject("wait", T2, times=None)
    with pytest.raises(TierSwitchFailed) as raised:
        await manager.activate(T2)
    assert raised.value.restored is True
    status = manager.status()
    assert status.state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}
    assert "deep tier failed" in status.last_error and "serving from the fast tier" in status.last_error
    assert manager.counters["fallbacks_to_t1"] == 1 and runtime.count("wait", T2) == 2  # one try plus one retry
    calls = len(runtime.calls)
    await clock.advance(3600)  # nothing re-enters the deep tier on its own
    assert manager.status().state == ManagerState.READY_T1 and len(runtime.calls) == calls
    runtime.clear_faults()
    assert (await manager.activate(T2)).state == ManagerState.READY_T2  # a manual request works and clears the note
    assert manager.status().last_error is None


async def test_a_slow_deep_model_is_not_retried_because_it_would_only_time_out_again(make_manager, runtime) -> None:
    manager = make_manager(t2_start_retries=3)
    await manager.start()
    runtime.inject("wait", T2, times=None, error=ReadyTimeout)
    with pytest.raises(TierSwitchFailed):
        await manager.activate(T2)
    assert runtime.count("wait", T2) == 1 and manager.status().state == ManagerState.READY_T1


async def test_a_crash_while_the_deep_tier_is_loaded_is_noticed_and_retried(make_manager, runtime, clock) -> None:
    manager = make_manager(t2_start_retries=1)
    await manager.start()
    await manager.activate(T2, lease_seconds=3600)
    runtime.running[T2] = False  # the container died
    await clock.advance(15)  # one watchdog tick
    status = manager.status()
    assert status.state == ManagerState.READY_T2 and runtime.running[T2] is True
    assert manager.counters["t2_crashes"] == 1 and manager.counters["swaps_to_t2"] == 1
    assert any(r.kind == "recover_t2" and r.outcome == "ok" for r in manager.transitions())
    assert status.lease_expires_at is not None  # the caller's lease still bounds how long it stays


async def test_a_crash_that_cannot_be_recovered_falls_back_to_the_fast_tier_without_the_owner(
    make_manager, runtime, clock
) -> None:
    manager = make_manager(t2_start_retries=1)
    await manager.start()
    await manager.activate(T2)
    runtime.running[T2] = False
    runtime.inject("start", T2, times=None)  # it will not come back
    await clock.advance(15)
    status = manager.status()
    assert status.state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}
    assert "serving from the fast tier" in status.last_error
    assert manager.counters["t2_crashes"] == 1 and manager.counters["fallbacks_to_t1"] == 1
    calls = len(runtime.calls)
    await clock.advance(600)  # and the watchdog has stopped: no further attempts
    assert len(runtime.calls) == calls and manager.status().state == ManagerState.READY_T1


async def test_a_hung_deep_tier_needs_consecutive_failed_checks_not_one_slow_answer(make_manager, runtime, clock) -> None:
    manager = make_manager(t2_start_retries=1, watch_unhealthy_checks=3)
    await manager.start()
    await manager.activate(T2)
    runtime.ready_script = [False, False, True]  # two slow answers, then healthy again
    for _ in range(3):
        await clock.advance(15)
    assert manager.counters["t2_crashes"] == 0 and manager.status().state == ManagerState.READY_T2
    runtime.ready[T2] = False  # now it stays wedged
    for _ in range(3):
        await clock.advance(15)
    assert manager.counters["t2_crashes"] == 1  # acted on the third consecutive failure


async def test_a_job_running_when_the_deep_tier_dies_fails_cleanly_and_lands_on_the_fast_tier(
    make_manager, runtime, clock
) -> None:
    manager = make_manager(t2_start_retries=1)
    await manager.start()
    started, crashed = asyncio.Event(), asyncio.Event()

    async def job(endpoint: str) -> str:
        started.set()
        await crashed.wait()
        raise ConnectionError("the deep model went away")

    task = asyncio.ensure_future(manager.run_job(job))
    await started.wait()
    runtime.running[T2] = False
    runtime.inject("start", T2, times=None)
    await clock.advance(15)  # the watchdog recovers, fails, and falls back to the fast tier
    assert manager.status().state == ManagerState.READY_T1
    crashed.set()
    with pytest.raises(JobFailed, match="went away"):  # no Busy error, no stranded deep tier
        await task
    assert manager.status().state == ManagerState.READY_T1 and runtime.running == {T1: True, T2: False}


async def test_the_watchdog_stops_when_the_deep_tier_is_released(make_manager, runtime, clock) -> None:
    manager = make_manager(t2_start_retries=1)
    await manager.start()
    await manager.activate(T2)
    await manager.restore()
    runtime.running[T2] = False  # irrelevant now
    calls = len(runtime.calls)
    await clock.advance(120)
    assert len(runtime.calls) == calls and manager.counters["t2_crashes"] == 0


async def test_a_reconciled_deep_tier_is_watched_too(make_manager, runtime, clock) -> None:
    runtime.running = {T1: False, T2: True}
    manager = make_manager(t2_start_retries=0)
    await manager.start()  # adopted after a manager restart
    runtime.running[T2] = False
    runtime.inject("start", T2, times=None)
    await clock.advance(15)
    assert manager.status().state == ManagerState.READY_T1 and manager.counters["t2_crashes"] == 1
