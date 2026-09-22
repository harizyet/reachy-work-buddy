# ADR 0004: Reachy Must Remain Expressive Without the Homelab

- Status: Accepted
- Date: 2026-09-21


## Phase 22 topology amendment (2026-09-22)

Physical inventory of the deployed Reachy Mini + original Jetson Nano
([docs/verification/phase-22-inventory-2026-09-22.md](../verification/phase-22-inventory-2026-09-22.md))
found camera, audio, and motor-controller all USB-attached directly to the
Nano, with no separate "Reachy onboard computer" anywhere in evidence —
consistent with Reachy Mini's design having no independent onboard Linux
compute. **For this deployment, the original "optional Jetson, inference
accelerator only" framing below does not hold**: the Jetson (or whichever
machine is USB-wired to the robot) is not optional, it is the only
possible host for `reachy-embodiment`, because there is nowhere else to
run it against real hardware.

This revises the guarantee, not the architecture:

- The **homelab-outage** guarantee is unaffected and remains the primary
  contract this ADR exists for: `reachy-embodiment` on the Jetson keeps
  running its local presence/fallback state machine, independent of
  `companion-core`/`reachy-hub` reachability, exactly as decided below.
- The **Jetson-outage** guarantee ("Jetson offline → no effect on core
  robot availability") is **revised to no longer apply** for a Reachy
  Mini deployment where the Jetson is the sole robot-attached machine: if
  that Jetson is offline, the robot is inert — there is no second machine
  for embodiment to fail over to. This was previously written assuming a
  Jetson that only accelerated inference for a robot with independent
  onboard compute; physical inventory shows that machine doesn't exist
  here. Restoring genuine Jetson-outage survivability would require
  provisioning a second, independently-robot-wired compute host — out of
  scope for Phase 22 unless the deployment topology changes.
- [docs/phase-22-23.md](../phase-22-23.md)'s architecture table's "Reachy
  onboard computer, if present" row should be read as confirmed-absent
  for this specific physical setup; do not build or promise features that
  assume a second robot-side host exists.

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
