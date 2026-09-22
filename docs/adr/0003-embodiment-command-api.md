# ADR 0003: Semantic Embodiment Command API

- Status: Accepted
- Date: 2026-09-21


## Phase 22 connectivity amendment (planned)

[ADR 0019](0019-robot-initiated-hub-connectivity.md) adopts robot-initiated
WSS control and a separate outbound media path. Core-to-hub HTTP, semantic
commands, hub-owned browser WebRTC and independent local fallback remain.
The original HTTP implementation described below remains current until
Phase 22 is implemented.

## Context

`companion-core` needs to make Reachy express behaviours (listening,
thinking, greeting, "sent to your phone", etc.) without knowing anything
about servos, recorded-move datasets, or the Reachy daemon's REST/WebSocket
API. Coupling reasoning output to raw motor targets would violate the
cognition/embodiment boundary (ADR 0001) and make `reachy-embodiment`
un-swappable.

## Decision

`reachy-embodiment` exposes a small semantic HTTP API:

```
GET  /health
GET  /state
GET  /behaviours
POST /behaviour/{name}
POST /gaze
POST /pose
POST /audio/play
```

Callers send an `EmbodimentCommand` (see `shared/models/embodiment.py`):
`behaviour_name`, `priority`, `parameters`, `interruptible`,
`correlation_id`. `reachy-embodiment` resolves `behaviour_name` against its
own behaviour catalogue (backed by Reachy recorded-move datasets initially)
and drives the Reachy daemon itself. No caller outside `reachy-embodiment`
ever issues raw joint/pose commands to the daemon.

The initial behaviour vocabulary (see `shared/models/embodiment.py`):
listening, thinking, speaking, acknowledgement, understood, uncertain,
greeting, goodbye, waiting, task_complete, cannot_comply, sent_to_phone,
incoming_message, meeting_soon, important_notice, do_not_disturb,
idle_breathing, subtle_scan, antenna_twitch, sleep, wake.

## Consequences

- `reachy-embodiment` can be reimplemented (different robot, different
  motion backend) without touching `companion-core`.
- New behaviours are added by extending the catalogue in
  `reachy-embodiment`, not by changing `companion-core`'s output format.
- `correlation_id` ties an `EmbodimentCommand` back to the `AgentResponse`
  that requested it, for audit/debugging.
