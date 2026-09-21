"""HTTP contract for reachy-embodiment. See docs/adr/0003.

Route constants only — the actual FastAPI app lives in
services/reachy-embodiment (Phase 2) and imports these so the hub and
embodiment service can never drift on path spelling.
"""

from __future__ import annotations

HEALTH = "/health"
STATE = "/state"
BEHAVIOURS = "/behaviours"
BEHAVIOUR = "/behaviour/{name}"
GAZE = "/gaze"
POSE = "/pose"
AUDIO_PLAY = "/audio/play"
