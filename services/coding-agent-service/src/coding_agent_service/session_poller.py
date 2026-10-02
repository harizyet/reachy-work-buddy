"""Background inspection of in-flight sessions while the service stays up.
Restart recovery (reconcile.py) covers a restart; this covers the long run
between restarts, so a session that finishes becomes COMPLETED (and so
notifiable) without anyone calling /refresh.

Conservative by design: a failed inspection (Docker unreachable, one bad
session) leaves the record as it was and is retried next tick. Only the
provider's own verdict changes a status.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from coding_agent_service.service import CodingAgentSupervisor
from coding_agent_service.store import CodingAgentStore
from shared.models.coding_agent import CodingAgentStatus

logger = logging.getLogger(__name__)

# Statuses where the provider's process is still expected to be working and
# so may have finished since the last look. WAITING_* sessions are idle on
# the owner, not on the container.
POLLED_STATUSES = frozenset(
    {
        CodingAgentStatus.STARTING,
        CodingAgentStatus.RUNNING,
        CodingAgentStatus.RATE_LIMITED,
    }
)


async def poll_once(
    supervisor: CodingAgentSupervisor, store: CodingAgentStore
) -> list[str]:
    """Inspect every in-flight session once; returns ids whose status changed."""
    changed = []
    for session in await store.list_sessions():
        if session.status not in POLLED_STATUSES:
            continue
        # A session still being started by a request has no container yet.
        if session.container_id is None:
            continue
        try:
            if await supervisor.poll_session(session):
                changed.append(session.id)
        except Exception:
            logger.warning(
                "Could not poll session %s; left as recorded", session.id, exc_info=True
            )
    return changed


async def run_poll_loop(
    supervisor: CodingAgentSupervisor,
    store: CodingAgentStore,
    interval_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    while True:
        try:
            await poll_once(supervisor, store)
        except Exception:
            logger.warning("Session poll failed; retrying next interval", exc_info=True)
        await sleep(interval_seconds)
