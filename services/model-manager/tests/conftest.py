"""Fakes shared by the model manager tests: a scriptable runtime and a controllable clock."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from model_manager.config import ManagerConfig
from model_manager.machine import ModelManager
from model_manager.runtime import RuntimeFailure

from shared.models.model_manager import ModelTier

T1, T2 = ModelTier.T1, ModelTier.T2


class FakeClock:
    """`now()` and an `sleep()` that only returns when the test advances time."""

    def __init__(self) -> None:
        self.t = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        self._waiters: list[tuple[datetime, asyncio.Future]] = []

    def now(self) -> datetime:
        return self.t

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        future = asyncio.get_running_loop().create_future()
        self._waiters.append((self.t + timedelta(seconds=seconds), future))
        await future

    async def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)
        for entry in [w for w in self._waiters if w[0] <= self.t]:
            self._waiters.remove(entry)
            if not entry[1].done():
                entry[1].set_result(None)
        for _ in range(20):  # let woken tasks run to completion
            await asyncio.sleep(0)


class FakeRuntime:
    """Pretends to be Docker. `inject(op, tier)` makes the next matching call raise; `gate(tier)` holds wait_ready."""

    def __init__(self) -> None:
        self.running = {T1: True, T2: False}
        self.ready = {T1: True, T2: True}
        self.ready_script: list[bool] = []  # if set, successive is_ready(T2) answers are taken from here first
        self.calls: list[tuple[str, ModelTier]] = []
        self._faults: dict[tuple[str, ModelTier], tuple[int | None, type[RuntimeFailure]]] = {}
        self._gates: dict[ModelTier, asyncio.Event] = {}

    def inject(
        self, op: str, tier: ModelTier, times: int | None = 1, error: type[RuntimeFailure] = RuntimeFailure
    ) -> None:
        self._faults[(op, tier)] = (times, error)  # times=None means every time

    def clear_faults(self) -> None:
        self._faults.clear()

    def gate(self, tier: ModelTier) -> asyncio.Event:
        return self._gates.setdefault(tier, asyncio.Event())

    def count(self, op: str, tier: ModelTier) -> int:
        return sum(1 for c in self.calls if c == (op, tier))

    def _maybe_fail(self, op: str, tier: ModelTier) -> None:
        remaining, error = self._faults.get((op, tier), (0, RuntimeFailure))
        if remaining is None or remaining > 0:
            if remaining is not None:
                self._faults[(op, tier)] = (remaining - 1, error)
            raise error(f"injected {op} failure for {tier.value}")

    async def stop_tier(self, tier: ModelTier) -> None:
        self.calls.append(("stop", tier))
        self._maybe_fail("stop", tier)
        self.running[tier] = False

    async def start_tier(self, tier: ModelTier) -> None:
        self.calls.append(("start", tier))
        self._maybe_fail("start", tier)
        self.running[tier] = True

    async def wait_ready(self, tier: ModelTier, timeout_s: float) -> None:
        self.calls.append(("wait", tier))
        self._maybe_fail("wait", tier)
        if tier in self._gates:
            await self._gates[tier].wait()
        for _ in range(50):  # like the real runtime, poll while the model is still loading
            if self.running[tier] and self.ready[tier]:
                return
            await asyncio.sleep(0)
        raise RuntimeFailure(f"{tier.value} is not ready")

    async def is_running(self, tier: ModelTier) -> bool:
        return self.running[tier]

    async def is_ready(self, tier: ModelTier) -> bool:
        if tier == T2 and self.ready_script:
            return self.running[tier] and self.ready_script.pop(0)
        return self.running[tier] and self.ready[tier]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def make_manager(runtime: FakeRuntime, clock: FakeClock):
    def build(**config) -> ModelManager:
        # Defaults keep the older tests single-shot; the retry and watchdog tests opt in explicitly.
        config.setdefault("t2_start_retries", 0)
        config.setdefault("t2_retry_delay_s", 0.0)
        return ModelManager(runtime, ManagerConfig(**config), now=clock.now, sleep=clock.sleep)

    return build
