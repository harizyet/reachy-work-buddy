# ADR 0019: Robot-initiated hub connectivity

- Status: Accepted for Phase 22; not implemented
- Date: 2026-09-22

## Context

The current hub registry routes through a robot `base_url`, with HTTP
commands, hub-originated heartbeats, JPEG polling and audio uploads. Phase
22 must support moving the robot between networks without configuring its
address in the homelab or requiring inbound robot ports.

Tailscale addresses normally remain stable across physical network changes;
this decision does not assume otherwise. Device names provide a convenient
stable hub destination. See [Tailscale connectivity](https://tailscale.com/docs/how-to/connect-to-devices)
and [MagicDNS](https://tailscale.com/docs/features/magicdns). DNS and network
membership do not replace application authentication or TLS configuration.

## Decision

The robot-side embodiment process initiates an authenticated persistent WSS
control connection to reachy-hub. The hub routes semantic commands over the
active connection for a logical `robot_id`; normal production operation does
not require a robot `base_url`. The robot knows the hub's configured HTTPS/WSS
origin, its own identity and its provisioned credential.

```text
companion-core --HTTP semantic requests--> reachy-hub
                                              ^
                                              | outbound WSS initiated below
                                      reachy-embodiment
                                              |
                                        Reachy daemon
```

The planned direct route is `/robots/connect`, exposed by Caddy as
`/hub/robots/connect`; define it in shared route constants. Use a validated
TLS certificate and a stable hub hostname reachable over LAN/VPN/Tailscale.
Provision a scoped per-robot bearer token for Phase 22; mTLS is a future
option. Send credentials in handshake headers, never URLs or log output.
Bind the authenticated credential to one provisioned robot ID; claims in a
registration message cannot select another identity. Browser owner cookies
and the existing broad remote-control token are not robot credentials.
Include secure provisioning, revocation (including active sockets) and rotation.
The hub can retain token verifiers rather than plaintext tokens; robot-side
credential files require restricted permissions. This need not wait for
Phase 23's core-owned provider SecretStore.

### Registry, protocol and lifecycle

- Keep provisioned identity/credential metadata separate from live state.
  Registry views expose identity, capabilities, transport, online/offline and
  last-seen time. Active sockets and pending requests are process-local and
  never restored as online after hub restart. Phase 22 uses one hub worker;
  multiple workers require an explicit connection-routing design first.
- Authenticate, negotiate protocol version, then register capabilities and
  current state. Distinguish connection health from hardware readiness: an
  online agent with a disconnected daemon is not a ready robot.
- Define bounded shared message schemas for registration, heartbeat/ack,
  state/capability updates, semantic commands, accepted/completed results,
  cancellation and sanitized errors. Each command has a correlation ID,
  connection generation and expiry. Acknowledged receipt is not completion.
  Preserve ADR 0003 semantic payloads and embodiment's final safety checks.
- Allow one authoritative connection per identity. An authenticated new
  connection atomically replaces and fences the previous generation; discard
  old results and prevent the old connection executing newly queued work.
  Hardware ownership remains independently serialized on the robot host.
- Detect broken and half-open connections with application heartbeat/ack and
  monotonic deadlines in both directions. Start with the existing 2-second
  heartbeat / 5-second watchdog relationship and validate under real jitter.
  Transport status is separate from embodiment states; do not invent a
  `CONNECTED` embodiment state to replace the existing vocabulary.
- Reconnect in the background with exponential backoff (1, 2, 4, 8 seconds,
  capped at 30 seconds), jitter and bounded connect/handshake timeouts. Reset
  after successful authenticated registration; rate-limit persistent auth
  failures. Presence starts without the hub and never waits on reconnect.
- On connection loss, mark offline and fail pending commands with an honest
  unavailable/unknown-outcome result. Do not automatically replay motion or
  speech after reconnect; a lost reply does not mean an action never happened.
  Bound queues, message sizes and concurrent requests; reject expired work,
  deduplicate within a connection, and prioritize heartbeats/cancellation.
  Do not claim exactly-once hardware execution across crashes.

Retain explicit HTTP simulation/development transport through the same hub
adapter interface. Tailscale HTTP and local HTTP are deployment variants of
that adapter, not distinct identities. Never silently fall back from failed
WSS authentication to HTTP. Production disables address registration and
unneeded inbound embodiment access. Preserve existing dev callers during
the transition without requiring new persistent schema before Phase 23;
initial robot provisioning can use restricted configuration files.

### Control and media separation

The control socket carries media negotiation/control, never camera frames,
WAV payloads or continuous microphone audio. Phase 22 retains hub ownership
of browser WebRTC sessions (ADRs 0012/0013); direct robot-to-browser WebRTC
is not introduced implicitly by this decision.

For the existing bounded media semantics, implement a separate robot-initiated
HTTPS media path to hub: requested JPEG frames and bounded microphone turns
upload to authenticated hub endpoints; robot speaker playback fetches bounded
audio from the same configured hub origin. WSS carries only opaque transfer
IDs and control/result messages. Bind transfers to robot, connection generation,
purpose and expiry; limit size/rate/concurrency, expire buffers, and never
fetch arbitrary command-supplied URLs. Session authorization/privacy rules
still govern capture and playback; a robot token alone cannot authorize a
user telepresence session. Keep media resource limits from starving control.

This preserves the current low-rate camera/PTT/WAV behaviour while removing
inbound robot HTTP dependencies. It is not a new continuous video/audio
streaming claim. Higher-throughput WebRTC robot media requires separate
design and measured ICE/TURN connectivity. Verify actual camera, microphone
and speaker paths with inbound robot ports blocked before declaring the
outbound architecture complete.

## Architecture amendments and consequences

This amends ADRs 0001/0003 only for the hub-to-embodiment wire transport:
core still uses HTTP to hub; hardware ownership and semantic commands stay
unchanged. Embodiment owns its device control connection, not user-channel
routing. ADR 0004's independent local fallback is preserved. The embodiment
host, not necessarily the Nano, owns the connection; this does not resolve
the separate physical-host question or make Nano mandatory for local motion.

Amend Phase 22 launchers to establish outbound identity/capability registration
instead of publishing a robot address. The GUI reports live transport and
hardware health, last seen and sanitized disconnect reason. Existing runtime
remains HTTP until Phase 22 is implemented; no migration occurred in this ADR.

## Required verification

Test protocol/auth/version rejection, credential rotation/revocation, duplicate
connections and generation fencing, bounded queues, expired/duplicate commands,
lost results and no replay. Test half-open links, hub/robot reboot, DNS/TLS
failure and real LAN/Wi-Fi changes with automatic reconnect and local fallback.
Exercise old HTTP development tests and new WSS in-process tests, then real
Caddy/TLS and physical hardware. With inbound robot ports blocked, prove
behaviours, state, camera, voice and speaker playback; saturate the separate
media path and verify watchdog responsiveness. Record evidence in the Phase
22 report. None of these checks has been performed for this planning change.
