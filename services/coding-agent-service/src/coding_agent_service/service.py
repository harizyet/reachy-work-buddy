"""29.1: orchestration tying the project/session store to a provider
registry. This is the only place that calls a CodingAgentProvider — routes.py
stays a thin HTTP translation layer, same shape as companion-core's
accounts/service.py dispatcher.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from coding_agent_service.providers import (
    CodingAgentProvider,
    ProviderError,
    ProviderEvent,
)
from coding_agent_service.store import CodingAgentStore
from shared.models.coding_agent import (
    ALLOWANCE_WINDOW_NAMES,
    TERMINAL_STATUSES,
    CodingAgentEvent,
    CodingAgentEventType,
    CodingAgentSession,
    CodingAgentStatus,
    CodingProject,
    ProviderAllowance,
    ProviderCapabilities,
    UsageSnapshot,
)

logger = logging.getLogger(__name__)

# How many recent snapshots to scan for still-open allowance windows. Each
# window re-appears in every snapshot taken while it is open, so a small
# recent slice always contains the latest reading.
_ALLOWANCE_SCAN_LIMIT = 50

# 29.13's proactive-notification vocabulary doesn't have a dedicated event
# for an owner-initiated stop or session creation; both are expected,
# non-alerting transitions, so they map onto the closest terminal/starting
# notification type rather than growing the shared enum for this service's
# internal bookkeeping alone.
_EVENT_TYPE_BY_STATUS = {
    CodingAgentStatus.STARTING: CodingAgentEventType.AGENT_STARTED,
    CodingAgentStatus.RUNNING: CodingAgentEventType.AGENT_STILL_RUNNING,
    CodingAgentStatus.WAITING_FOR_INPUT: CodingAgentEventType.AGENT_NEEDS_INPUT,
    CodingAgentStatus.WAITING_FOR_PERMISSION: CodingAgentEventType.AGENT_NEEDS_PERMISSION,
    CodingAgentStatus.RATE_LIMITED: CodingAgentEventType.AGENT_RATE_LIMITED,
    CodingAgentStatus.COMPLETED: CodingAgentEventType.AGENT_COMPLETED,
    CodingAgentStatus.FAILED: CodingAgentEventType.AGENT_FAILED,
    CodingAgentStatus.STOPPED: CodingAgentEventType.AGENT_COMPLETED,
    CodingAgentStatus.LOST: CodingAgentEventType.AGENT_FAILED,
}


class UnknownProjectError(Exception):
    pass


class UnknownSessionError(Exception):
    pass


class UnknownProviderError(Exception):
    pass


class SessionNotResumableError(Exception):
    pass


class CodingAgentSupervisor:
    """29.1's exit criterion: "A simulated provider can create and
    transition a durable coding session" — this class is what does both,
    against whichever store/provider registry it is constructed with."""

    def __init__(self, store: CodingAgentStore, providers: dict[str, CodingAgentProvider]) -> None:
        self._store = store
        self._providers = providers

    def _provider_for(self, provider_name: str) -> CodingAgentProvider:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise UnknownProviderError(provider_name)
        return provider

    def provider_capabilities(self, provider_name: str) -> ProviderCapabilities:
        return self._provider_for(provider_name).capabilities()

    async def add_project(self, project: CodingProject) -> CodingProject:
        return await self._store.add_project(project)

    async def list_projects(self) -> list[CodingProject]:
        return await self._store.list_projects()

    async def get_project(self, project_id: str) -> CodingProject:
        project = await self._store.get_project(project_id)
        if project is None:
            raise UnknownProjectError(project_id)
        return project

    async def start_session(
        self,
        *,
        project_id: str,
        task_summary: str,
        owner_user_id: str,
        branch: str | None = None,
    ) -> CodingAgentSession:
        project = await self.get_project(project_id)
        provider = self._provider_for(project.provider)
        session = CodingAgentSession(
            project_id=project.id,
            provider=project.provider,
            status=CodingAgentStatus.STARTING,
            task_summary=task_summary,
            branch=branch or project.default_branch,
            owner_user_id=owner_user_id,
        )
        await self._store.add_session(session)
        await self._record_event(session, CodingAgentEventType.AGENT_STARTED, f"Starting task: {task_summary}")
        try:
            event = await provider.start_session(session)
        except Exception as exc:
            # A durable record must not be left STARTING forever by a start
            # that never began; restart recovery would later misreport it
            # as a lost running session.
            await self.apply_provider_event(
                session, ProviderEvent(status=CodingAgentStatus.FAILED, summary=f"Start failed: {exc}"[:2000])
            )
            raise
        return await self.apply_provider_event(session, event)

    async def get_session(self, session_id: str) -> CodingAgentSession:
        session = await self._store.get_session(session_id)
        if session is None:
            raise UnknownSessionError(session_id)
        return session

    async def list_sessions(self) -> list[CodingAgentSession]:
        return await self._store.list_sessions()

    async def list_events(self, session_id: str) -> list[CodingAgentEvent]:
        await self.get_session(session_id)
        return await self._store.list_events(session_id)

    async def resume_session(self, session_id: str, instruction: str) -> CodingAgentSession:
        """29.9/29.16: the owner's input relay path. Refuses a session that
        isn't actually waiting for anything — resuming a RUNNING or
        terminal session would silently fabricate owner intent the agent
        never asked for (29.16: "must preserve exact owner intent")."""

        session = await self.get_session(session_id)
        if session.status in TERMINAL_STATUSES or session.status in (
            CodingAgentStatus.CREATED,
            CodingAgentStatus.STARTING,
            CodingAgentStatus.RUNNING,
        ):
            raise SessionNotResumableError(f"Session {session_id} is not waiting for input (status={session.status})")
        provider = self._provider_for(session.provider)
        event = await provider.resume_session(session, instruction)
        return await self.apply_provider_event(session, event)

    async def send_input(self, session_id: str, text: str) -> CodingAgentSession:
        return await self.resume_session(session_id, text)

    async def stop_session(self, session_id: str) -> CodingAgentSession:
        session = await self.get_session(session_id)
        if session.status in TERMINAL_STATUSES:
            return session
        provider = self._provider_for(session.provider)
        event = await provider.stop_session(session)
        return await self.apply_provider_event(session, event)

    async def inspect_session(self, session_id: str) -> CodingAgentSession:
        session = await self.get_session(session_id)
        if session.status in TERMINAL_STATUSES:
            return session
        provider = self._provider_for(session.provider)
        event = await provider.inspect_session(session)
        return await self.apply_provider_event(session, event)

    async def recover_session(self, session: CodingAgentSession, adopted_container_id: str | None = None) -> bool:
        """29.27: re-derive one non-terminal session's state from its
        provider after a restart. `adopted_container_id` is a container
        rediscovered by label for a session whose record never got to store
        one. A provider that cannot find the session's runtime state
        reports LOST — never COMPLETED, since absence says nothing about
        why the work stopped. Returns whether the record changed."""
        provider = self._provider_for(session.provider)
        if adopted_container_id is not None:
            session.container_id = adopted_container_id
        try:
            event = await provider.inspect_session(session)
        except ProviderError as exc:
            event = ProviderEvent(
                status=CodingAgentStatus.LOST,
                summary=f"Nothing running was found for this session after a restart ({exc}); its outcome is unknown",
                provider_session_id=session.provider_session_id,
            )
        if event.status == session.status and adopted_container_id is None:
            return False
        event.metadata = {**event.metadata, "recovered_after_restart": True}
        await self.apply_provider_event(session, event)
        return True

    async def collect_usage(self, session_id: str) -> UsageSnapshot:
        session = await self.get_session(session_id)
        provider = self._provider_for(session.provider)
        return await self._remember_usage(await provider.collect_usage(session))

    async def provider_allowance(self, provider_name: str) -> ProviderAllowance:
        """29.26: account allowance windows still open, newest reading per
        window, drawn from persisted usage snapshots of any session."""
        self._provider_for(provider_name)
        now = datetime.now(UTC)
        windows = {}
        for snapshot in await self._store.recent_usage_snapshots(provider_name, _ALLOWANCE_SCAN_LIMIT):
            for dimension in snapshot.dimensions:
                if dimension.name not in ALLOWANCE_WINDOW_NAMES or dimension.name in windows:
                    continue
                if dimension.resets_at is not None and dimension.resets_at > now:
                    windows[dimension.name] = dimension
        return ProviderAllowance(provider=provider_name, windows=list(windows.values()))

    async def _remember_usage(self, snapshot: UsageSnapshot) -> UsageSnapshot:
        """Usage is read from the provider's container logs, which vanish
        with the container. Persist what was measured; when a provider can
        no longer measure anything, serve the last persisted reading
        instead of reporting nothing."""
        previous = await self._store.latest_usage_snapshot(snapshot.session_id)
        if not snapshot.dimensions:
            return previous or snapshot
        if previous is None or previous.dimensions != snapshot.dimensions:
            await self._store.add_usage_snapshot(snapshot)
        return snapshot

    async def apply_provider_event(self, session: CodingAgentSession, event: ProviderEvent) -> CodingAgentSession:
        session.status = event.status
        session.last_activity_at = datetime.now(UTC)
        session.last_event = event.summary
        if event.provider_session_id is not None:
            session.provider_session_id = event.provider_session_id
        # 29.3: a provider that actually runs a container (unlike
        # SimulatedProvider) reports it back via metadata rather than a
        # dedicated ProviderEvent field — this is the one place that reads
        # it, so inspect_session/stop_session can find the container again
        # on a later call without the provider having to re-derive it.
        container_id = event.metadata.get("container_id")
        if container_id is not None:
            session.container_id = container_id
        if event.status in TERMINAL_STATUSES and session.completed_at is None:
            session.completed_at = session.last_activity_at
        if event.status == CodingAgentStatus.FAILED:
            session.error_detail = event.summary
        await self._store.update_session(session)
        if event.status in TERMINAL_STATUSES:
            await self._capture_final_usage(session)
        event_type = _EVENT_TYPE_BY_STATUS.get(event.status, CodingAgentEventType.AGENT_STILL_RUNNING)
        await self._record_event(session, event_type, event.summary, event.metadata)
        return session

    async def _capture_final_usage(self, session: CodingAgentSession) -> None:
        # Usage is informational; failing to read it must never block a
        # status transition the owner is waiting on.
        try:
            provider = self._provider_for(session.provider)
            await self._remember_usage(await provider.collect_usage(session))
        except Exception:
            logger.warning("Could not capture final usage for session %s", session.id, exc_info=True)

    async def _record_event(
        self,
        session: CodingAgentSession,
        event_type: CodingAgentEventType,
        summary: str,
        metadata: dict | None = None,
    ) -> None:
        await self._store.add_event(
            CodingAgentEvent(
                session_id=session.id,
                type=event_type,
                summary=summary,
                provider_metadata=metadata or {},
            )
        )
