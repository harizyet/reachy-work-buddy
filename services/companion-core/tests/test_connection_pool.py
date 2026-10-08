"""The connection budget (docs/verification/phase-44b-connection-budget-2026-10-08.md): every store sizes its pool through
shared.database.connection_pool, so the stack's PostgreSQL connections stay bounded and tunable."""

import pathlib

from shared.database import connection_pool

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_default_pool_is_small_and_unopened(monkeypatch) -> None:
    monkeypatch.delenv("DB_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)
    pool = connection_pool("postgresql://u:p@localhost/db")
    assert (pool.min_size, pool.max_size) == (1, 3) and pool._opened is False  # nothing connects until the store opens it


def test_environment_tunes_the_default_and_a_caller_can_override(monkeypatch) -> None:
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "5")
    assert (connection_pool("postgresql://x/y").min_size, connection_pool("postgresql://x/y").max_size) == (2, 5)
    assert connection_pool("postgresql://x/y", max_size=2).max_size == 2
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "1")  # a maximum below the minimum never produces an invalid pool
    assert connection_pool("postgresql://x/y").max_size == 2


def test_no_service_builds_its_own_pool() -> None:
    offenders = []
    for path in (ROOT / "services").rglob("*.py"):
        parts = path.parts
        if "tests" in parts or "benchmarks" in parts or ".venv" in parts:
            continue
        if "AsyncConnectionPool(" in path.read_text() and "def connection_pool" not in path.read_text():
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"size pools through shared.database.connection_pool: {offenders}"
