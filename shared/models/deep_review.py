"""A deep review: a task that runs on the larger local model while Reachy's fast model is unloaded (ADR 0031, Phase 42C)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DeepReviewStatus = Literal["switching", "reviewing", "restoring", "done", "failed"]


class DeepReviewJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_id: str
    meeting_title: str
    task: str = "corrections"  # corrections, summary or minutes
    status: DeepReviewStatus = "switching"
    stage: str = "Starting"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # True from the moment the fast model is unloaded until it is serving again: Reachy's local replies are
    # unavailable (chat falls back to the cloud model when the owner's routing allows it).
    reachy_unavailable: bool = False
    # True once the fast model is back and answering. A finished job with this False needs the owner.
    reachy_online: bool = False
    eta_seconds: int = 330
    # The suggestions (same shape as POST .../corrections/suggest), available as soon as the review finishes, which
    # is before the fast model has finished reloading.
    result: dict[str, Any] | None = None
    error: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed")


class DeepReviewInfo(BaseModel):
    configured: bool  # a model manager address and token are set
    available: bool  # the manager is reachable, on the fast tier, and no review is running
    reason: str | None = None
    eta_seconds: int = 330
