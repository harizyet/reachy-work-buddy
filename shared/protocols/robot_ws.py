"""WSS route + protocol version for the ADR 0019 robot<->hub control
connection. Route constant only — message schemas live in
shared/models/robot_ws.py, the hub-side endpoint in
services/reachy-hub/src/reachy_hub/robot_ws.py, and the robot-side client
in services/reachy-embodiment/src/reachy_embodiment/robot_ws_client.py.
See docs/adr/0019-robot-initiated-hub-connectivity.md.
"""

from __future__ import annotations

ROBOTS_CONNECT = "/robots/connect"

# Bumped whenever a breaking change is made to the message schemas below.
# A robot and hub that disagree on this reject the connection at
# registration time (ADR 0019: "negotiate protocol version").
PROTOCOL_VERSION = 1

# Phase 24c (ADR 0023): robot-initiated upload of one bounded utterance,
# authenticated with the robot's own credential. Not under /robots/ so it
# can't be mistaken for an owner remote-control route.
ROBOT_VOICE_TURN = "/robot-media/voice-turn"
# Phase 24e: ask the hub to answer the turn it is holding (ADR 0023).
ROBOT_VOICE_TURN_FINALIZE = "/robot-media/voice-turn/finalize"
# Phase 24e item 5: one camera frame taken while a reply plays, checked by
# the hub for a held open palm (ADR 0023 open-palm stop addendum).
ROBOT_PALM_FRAME = "/robot-media/palm-frame"
