"""Phase 29 (docs/phase-29.md) wire contract between companion-core and
coding-agent-service. Lives in shared/models, not the service package,
because companion-core's HTTP client needs the same shapes — unlike
meetings (companion-core only, see its models.py docstring), this is a
cross-service contract from day one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CodingAgentStatus(StrEnum):
    """29.5: normalized session status. Never inferred from "container
    process alive" alone — a provider/store transition always names one of
    these explicitly."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    RATE_LIMITED = "rate_limited"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    LOST = "lost"


# 29.5/29.27: states a session can still be driven from. COMPLETED, FAILED,
# STOPPED and LOST are terminal — reconciliation and input relay never move
# a session out of one of these on their own.
TERMINAL_STATUSES = frozenset(
    {
        CodingAgentStatus.COMPLETED,
        CodingAgentStatus.FAILED,
        CodingAgentStatus.STOPPED,
        CodingAgentStatus.LOST,
    }
)


class CodingAgentEventType(StrEnum):
    """29.13: normalized proactive-notification events, distinct from the
    session status enum — one status can be reached by more than one event
    (e.g. STOPPED by an owner stop or a provider SessionEnd)."""

    AGENT_STARTED = "agent_started"
    AGENT_STILL_RUNNING = "agent_still_running"
    AGENT_NEEDS_INPUT = "agent_needs_input"
    AGENT_NEEDS_PERMISSION = "agent_needs_permission"
    AGENT_USAGE_WARNING = "agent_usage_warning"
    AGENT_RATE_LIMITED = "agent_rate_limited"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"


class CodingProject(BaseModel):
    """29.4: the explicit registry a coding agent is allowed to touch. A
    project's repository_path is resolved by this record, never accepted
    as a free-form path from an LLM or a session request."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(min_length=1, max_length=200)
    repository_path: str = Field(min_length=1, max_length=4096)
    default_branch: str = Field(default="main", max_length=200)
    provider: str = Field(min_length=1, max_length=100)
    container_profile: str = Field(default="development-network", max_length=100)
    allowed_network_profile: str = Field(default="restricted-network", max_length=100)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CodingAgentSession(BaseModel):
    """29.5: durable session record. provider_session_id is the handle the
    adapter hands back to the real CLI's own resume mechanism (29.9) — it
    is never reused across providers or projects."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    provider: str = Field(min_length=1, max_length=100)
    provider_session_id: str | None = None
    container_id: str | None = None
    status: CodingAgentStatus = CodingAgentStatus.CREATED
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_activity_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    task_summary: str = Field(min_length=1, max_length=4000)
    branch: str | None = None
    owner_user_id: str
    last_event: str | None = None
    error_detail: str | None = None


class CodingAgentEvent(BaseModel):
    """29.21: a normalized event, not a raw log line. `sensitivity` lets a
    future retention policy drop/short-TTL anything that might carry
    command output rather than a summary (29.21: "avoid storing
    credentials, environment variables or full shell output
    indefinitely")."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    type: CodingAgentEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: str = Field(min_length=1, max_length=2000)
    provider_metadata: dict = Field(default_factory=dict)
    sensitivity: str = Field(default="normal", max_length=50)


class ProviderCapabilities(BaseModel):
    """29.2: what one provider adapter can actually report. Every field is
    a plain bool so coding-agent-service and its callers can gate behavior
    (e.g. never show a usage percentage a provider doesn't support) without
    guessing from the provider name."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    resumable_sessions: bool = False
    completion_events: bool = False
    needs_input_events: bool = False
    permission_events: bool = False
    usage_percentages: bool = False
    token_usage: bool = False
    monetary_cost: bool = False
    context_usage: bool = False
    structured_stream: bool = False


class UsageDimension(BaseModel):
    """29.26: one measured quota dimension. `unit` disambiguates a percent
    from a token count or a cost so a client never has to guess from the
    bare name."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    value: float
    unit: str = Field(min_length=1, max_length=20)
    resets_at: datetime | None = None


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    repository_path: str = Field(min_length=1, max_length=4096)
    default_branch: str = Field(default="main", max_length=200)
    provider: str = Field(min_length=1, max_length=100)
    container_profile: str = Field(default="development-network", max_length=100)
    allowed_network_profile: str = Field(default="restricted-network", max_length=100)


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    task_summary: str = Field(min_length=1, max_length=4000)
    owner_user_id: str
    branch: str | None = None


class ResumeSessionRequest(BaseModel):
    """29.16: carries the owner's exact instruction verbatim — never
    derived from repository content or the agent's own transcript."""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=4000)


class SendInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class CredentialKind(StrEnum):
    """29.19: the two shapes a provider credential takes. Never a password —
    this is a machine credential for a CLI, not an owner login."""

    API_KEY = "api_key"
    OAUTH_TOKEN = "oauth_token"


class ProviderCredentialRecord(BaseModel):
    """29.19/29.22: what the operator UI is allowed to see about a stored
    provider credential — never the secret value itself, only enough to
    confirm one is configured and let the owner recognize which one."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    kind: CredentialKind
    last_four: str = Field(max_length=4)
    updated_at: datetime


class SetCredentialRequest(BaseModel):
    """29.19: the owner-entered secret value, carried once over an
    authenticated connection and never echoed back. `repr=False` keeps it
    out of any accidental model repr/log."""

    model_config = ConfigDict(extra="forbid")

    kind: CredentialKind
    value: str = Field(min_length=1, max_length=8192, repr=False)


class UsageSnapshot(BaseModel):
    """29.26: usage is not a universal contract — a provider only reports
    the dimensions it can actually measure; an absent dimension is unknown,
    never assumed zero."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    provider: str
    dimensions: list[UsageDimension] = Field(default_factory=list)
    measured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
