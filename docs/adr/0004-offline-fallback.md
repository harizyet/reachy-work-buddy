# ADR 0004: Reachy Must Remain Expressive Without the Homelab

- Status: Accepted
- Date: 2026-09-21


## Phase 22 connectivity amendment (planned)

[ADR 0019](0019-robot-initiated-hub-connectivity.md) adopts robot-initiated
WSS control and a separate outbound media path. Core-to-hub HTTP, semantic
commands, hub-owned browser WebRTC and independent local fallback remain.
The original HTTP implementation described below remains current until
Phase 22 is implemented.

## Context

`companion-core` and `reachy-hub` run in the homelab and are reachable over
the network. Network partitions, homelab maintenance, or an optional Jetson
being offline must not turn Reachy into a dead object.

## Decision

`reachy-embodiment` runs a local presence/fallback state machine
(`IDLE / LISTENING / THINKING / SPEAKING / REMOTE / SLEEP / DISCONNECTED`)
independent of `companion-core` reachability:

```
Homelab connected → context-aware behaviour from Companion Core
Homelab offline   → local idle personality + safe manual control
Jetson offline     → no effect on core robot availability
```

`reachy-embodiment` detects loss of connectivity to `reachy-hub` (heartbeat
timeout) and transitions to `DISCONNECTED`, which drives local idle
behaviours (idle_breathing, subtle_scan, antenna_twitch) without requiring
any homelab round trip. The optional Jetson is an inference accelerator
only — its absence must not change `reachy-embodiment` availability or
degrade below the `DISCONNECTED` state.

## Consequences

- `reachy-embodiment` must ship with a self-contained idle behaviour set
  that does not depend on `companion-core` or Jetson being present.
- The presence loop (continuous ~30 Hz update, adapted from Jarvis) runs
  inside `reachy-embodiment`, not in `companion-core`, so it survives
  homelab outages.
- Reconnection is detected via heartbeat and transitions state back to
  homelab-driven behaviour without manual intervention.
