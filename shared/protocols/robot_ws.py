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
