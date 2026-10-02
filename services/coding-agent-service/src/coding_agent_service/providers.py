"""29.2: the provider contract every coding CLI adapter implements, plus a
SimulatedProvider used for 29.1's exit criterion and tests before a real
Claude Code container exists (29.3). Do not hard-code Claude semantics here
or in service.py — a provider only ever hands back a ProviderEvent in the
shared, normalized vocabulary (shared.models.coding_agent.CodingAgentStatus),
never a provider-specific string the rest of the service has to interpret.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from shared.models.coding_agent import (
    CodingAgentSession,
    CodingAgentStatus,
    InterventionState,
    ProviderCapabilities,
    UsageSnapshot,
    awaiting_owner,
)


@dataclass
class ProviderEvent:
    """What any provider call reports: the session's new normalized status,
    a human-readable summary (29.8: "Claude has stopped and is waiting",
    never a fabricated correctness claim), and an optional provider session
    handle for resumption (29.9)."""

    status: CodingAgentStatus
    summary: str
    provider_session_id: str | None = None
    metadata: dict = field(default_factory=dict)
    intervention_state: InterventionState = InterventionState.NONE
    intervention_source: str | None = None
    intervention_detail: str | None = None


class ProviderError(Exception):
    """Raised when a provider call fails outright (not a normal FAILED/
    RATE_LIMITED session transition, which is a ProviderEvent, not an
    exception)."""


class ProviderInvocationBlockedError(ProviderError):
    """A provider refuses to start or resume real model usage as a matter
    of deliberate policy — not a transient failure, and not specific to
    one provider's CLI. ClaudeCodeProvider raises this for a real
    subscription credential (29.3's hard guardrail), but the condition
    itself ("this would spend real usage and that's blocked right now")
    is provider-neutral, so routes.py can map it to a distinct HTTP status
    (403) without importing anything Claude-specific."""


class CodingAgentProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...

    async def start_session(self, session: CodingAgentSession) -> ProviderEvent: ...

    async def resume_session(self, session: CodingAgentSession, instruction: str) -> ProviderEvent: ...

    async def send_input(self, session: CodingAgentSession, text: str) -> ProviderEvent: ...

    async def stop_session(self, session: CodingAgentSession) -> ProviderEvent: ...

    async def inspect_session(self, session: CodingAgentSession) -> ProviderEvent: ...

    async def collect_usage(self, session: CodingAgentSession) -> UsageSnapshot: ...


class SimulatedProvider:
    """A deterministic fake standing in for a real CLI adapter (29.3+).
    Task-summary conventions drive its behavior so tests can exercise every
    normalized transition without a container:

    - a summary containing "permission:" asks for permission once started;
    - a summary containing "ask:" asks for input once started;
    - any other summary completes immediately, simulating a short
      non-interactive task that needed no owner interaction.

    send_input/resume_session always resolve a pending question straight to
    COMPLETED — this fake has only one open question per session, not a
    multi-turn script.
    """

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider="simulated",
            resumable_sessions=True,
            completion_events=True,
            needs_input_events=True,
            permission_events=True,
            usage_percentages=True,
            token_usage=False,
            monetary_cost=False,
            context_usage=True,
            structured_stream=True,
        )

    async def start_session(self, session: CodingAgentSession) -> ProviderEvent:
        provider_session_id = f"sim-{uuid.uuid4()}"
        lowered = session.task_summary.lower()
        if "permission:" in lowered:
            return ProviderEvent(
                status=CodingAgentStatus.WAITING_FOR_PERMISSION,
                summary="Simulated agent is requesting permission to proceed.",
                provider_session_id=provider_session_id,
            )
        if "ask:" in lowered:
            return ProviderEvent(
                status=CodingAgentStatus.WAITING_FOR_INPUT,
                summary="Simulated agent is asking a clarifying question.",
                provider_session_id=provider_session_id,
            )
        return ProviderEvent(
            status=CodingAgentStatus.COMPLETED,
            summary="Simulated agent finished the task.",
            provider_session_id=provider_session_id,
        )

    async def resume_session(self, session: CodingAgentSession, instruction: str) -> ProviderEvent:
        if session.status != CodingAgentStatus.RATE_LIMITED and not awaiting_owner(session):
            raise ProviderError(f"Cannot resume a session in status {session.status}")
        return ProviderEvent(
            status=CodingAgentStatus.COMPLETED,
            summary=f"Simulated agent resumed with owner instruction and finished: {instruction!r}",
            provider_session_id=session.provider_session_id,
        )

    async def send_input(self, session: CodingAgentSession, text: str) -> ProviderEvent:
        return await self.resume_session(session, text)

    async def stop_session(self, session: CodingAgentSession) -> ProviderEvent:
        return ProviderEvent(
            status=CodingAgentStatus.STOPPED,
            summary="Simulated agent stopped by owner request.",
            provider_session_id=session.provider_session_id,
        )

    async def inspect_session(self, session: CodingAgentSession) -> ProviderEvent:
        return ProviderEvent(
            status=session.status,
            summary=session.last_event or "No change.",
            provider_session_id=session.provider_session_id,
        )

    async def collect_usage(self, session: CodingAgentSession) -> UsageSnapshot:
        return UsageSnapshot(session_id=session.id, provider="simulated", dimensions=[])
