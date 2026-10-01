"""29.27 (pulled forward to prove 29.2's container runner survives a
restart): reconcile the session store against what the container runtime
actually reports right now, rather than trusting whatever status an
in-memory session object last recorded. A missing or exited container
becomes LOST, never COMPLETED — 29.8 only lets an actual provider event
claim completion; an absent container by itself carries no information
about why it stopped.
"""

from __future__ import annotations

from coding_agent_service.runtime import ContainerRuntime, ContainerStatus
from coding_agent_service.store import CodingAgentStore
from shared.models.coding_agent import TERMINAL_STATUSES, CodingAgentStatus


async def reconcile_sessions(store: CodingAgentStore, runtime: ContainerRuntime) -> list[str]:
    """Returns the ids of sessions whose status changed as a result."""
    changed_ids = []
    for session in await store.list_sessions():
        if session.status in TERMINAL_STATUSES or not session.container_id:
            continue
        status = await runtime.status(session.container_id)
        if status == ContainerStatus.RUNNING:
            continue
        session.status = CodingAgentStatus.LOST
        session.error_detail = f"Container {session.container_id} is no longer running (reconciled as {status.value})"
        await store.update_session(session)
        changed_ids.append(session.id)
    return changed_ids
