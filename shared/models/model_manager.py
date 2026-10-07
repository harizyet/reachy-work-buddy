"""Model manager state shared with whatever later asks Reachy's local model tier to change (ADR 0031)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ModelTier(StrEnum):
    T1 = "t1"  # fast local: always-on interactive default
    T2 = "t2"  # deep local: loaded temporarily for batch or deferred work


class ManagerState(StrEnum):
    READY_T1 = "ready_t1"
    SWITCHING_TO_T2 = "switching_to_t2"
    READY_T2 = "ready_t2"
    RESTORING_T1 = "restoring_t1"
    FAILED = "failed"


class ManagerStatus(BaseModel):
    state: ManagerState
    tier: ModelTier | None  # the tier currently serving, None while switching or failed
    served_model_name: str  # the stable API-visible name; never changes with the tier
    model: str | None  # the underlying model id of the serving tier
    since: datetime
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    transition_in_progress: bool = False


class TransitionRecord(BaseModel):
    id: int
    kind: str  # activate_t2, restore_t1, reconcile, lease_expiry
    from_state: ManagerState | None
    to_state: ManagerState
    tier: ModelTier
    model: str
    started_at: datetime
    ended_at: datetime
    duration_s: float
    outcome: str  # ok or failed
    error: str | None = None
