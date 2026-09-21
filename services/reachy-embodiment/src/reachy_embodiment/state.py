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
