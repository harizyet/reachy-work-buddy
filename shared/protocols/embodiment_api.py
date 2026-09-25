"""HTTP contract for reachy-embodiment. See docs/adr/0003 and docs/adr/0004.

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
# Phase 16 (remote telepresence, ADR 0013): the other two ADR 0003
# endpoints this contract always reserved but never implemented, plus a
# new REMOTE marker (not in the original ADR 0003 list) for
# reachy-hub to signal a telepresence session's start/end.
CAMERA_FRAME = "/camera/frame"
REMOTE = "/remote"
# reachy-hub pings this periodically so reachy-embodiment's presence loop can
# detect a homelab outage and fall back to local idle behaviour. See ADR 0004.
HEARTBEAT = "/heartbeat"
# Phase 22b: owner-requested remote "turn off/standby" and resume, wrapping
# the real daemon's own POST /api/daemon/stop and /api/daemon/start. See
# docs/verification/phase-22b-first-motion-2026-09-23.md.
DAEMON_STANDBY = "/daemon/standby"
DAEMON_RESUME = "/daemon/resume"

MOTION_SETTINGS = "/settings/motion"
