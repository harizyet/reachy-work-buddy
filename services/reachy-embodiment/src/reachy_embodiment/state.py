from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from shared.models.embodiment import Behaviour, EmbodimentState


class ServiceState(BaseModel):
    embodiment_state: EmbodimentState = EmbodimentState.IDLE
    last_behaviour: Behaviour | None = None
    last_behaviour_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    connected: bool = False
    sim: bool = True
    # Phase 16/ADR 0013: set by POST /remote, read by POST /audio/play to
    # decide what state to revert to afterwards (REMOTE vs IDLE).
    remote_active: bool = False
