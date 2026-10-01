"""29.27: after a restart, reconcile the durable session records against what
Docker and each provider actually report right now, instead of trusting the
status last written. For every non-terminal session: find its container
(the stored id, or else the `reachy.session_id` label for a crash between
`docker run` and the database write), then let the provider inspect it. An
absent or unreadable runtime becomes LOST, never COMPLETED.

If Docker itself cannot be queried, nothing is changed: LOST is terminal, and
"could not ask" is not evidence that the work ended.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from coding_agent_service.runtime import ContainerRuntime, ContainerRuntimeError
from coding_agent_service.service import CodingAgentSupervisor, UnknownProviderError
from coding_agent_service.store import CodingAgentStore
from shared.models.coding_agent import TERMINAL_STATUSES

logger = logging.getLogger(__name__)


@dataclass
class RecoveryReport:
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    # Sessions left as recorded because they could not be inspected.
    unresolved: list[str] = field(default_factory=list)
    # Containers carrying a reachy.session_id label that no stored session
    # claims; reported, never adopted or removed.
    orphan_container_ids: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


async def recover_sessions(
    supervisor: CodingAgentSupervisor, store: CodingAgentStore, runtime: ContainerRuntime
) -> RecoveryReport:
    report = RecoveryReport()
    try:
        labeled = await runtime.list_labeled()
    except ContainerRuntimeError as exc:
        report.skipped_reason = f"container runtime unavailable: {exc}"
        logger.warning("Session recovery skipped; %s", report.skipped_reason)
        return report

    sessions = await store.list_sessions()
    known_ids = {session.id for session in sessions}
    report.orphan_container_ids = [
        container_id
        for container_id, labels in labeled.items()
        if labels.get("reachy.session_id") not in known_ids
    ]
    if report.orphan_container_ids:
        logger.warning("Containers labeled for unknown sessions: %s", report.orphan_container_ids)

    for session in sessions:
        if session.status in TERMINAL_STATUSES:
            continue
        adopted = None
        if session.container_id is None:
            # `docker ps` lists newest first, so the first match is the latest run.
            adopted = next(
                (cid for cid, labels in labeled.items() if labels.get("reachy.session_id") == session.id), None
            )
        try:
            changed = await supervisor.recover_session(session, adopted)
        except UnknownProviderError:
            logger.warning("Session %s uses unregistered provider %r; left as recorded", session.id, session.provider)
            report.unresolved.append(session.id)
            continue
        except Exception:
            # One unreadable session must not stop the others' recovery.
            logger.warning("Could not recover session %s; left as recorded", session.id, exc_info=True)
            report.unresolved.append(session.id)
            continue
        (report.changed if changed else report.unchanged).append(session.id)
    return report
