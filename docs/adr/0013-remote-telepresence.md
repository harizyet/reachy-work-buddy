# ADR 0013: Remote Telepresence — Auth, Camera Transport, Direct Speak

- Status: Accepted
- Date: 2026-09-22

## Context

docs/plan.md's Phase 16 row: "Camera/status/manual behaviours/
speak-through-robot via secure remote UI," exit criterion "Overseas user
can control basic Reachy functions without Companion Core." Per ADR 0001,
reachy-hub owns "authentication" as one of its concerns, but nothing has
ever implemented it — every endpoint added through Phase 15 was reachable
by anyone who could reach the Caddy port. `deploy/homelab/Caddyfile`'s own
header comment already flagged this: "this does NOT implement
authentication... Auth/TLS for real remote access is Phase 16... Do not
expose this port to the public Internet as configured here." This phase is
what makes that comment true.

"Without Companion Core" is the other load-bearing part of the exit
criterion: every prior voice/text path (`/messages`, `/voice/turn`,
`/webrtc/offer`) reasons through `companion-core` via
`handle_inbound_message`. Telepresence needs a path that keeps working
when companion-core is down — camera viewing and speaking a typed sentence
through the robot are not reasoning, they don't need an LLM in the loop.

No physical Reachy or camera exists in this environment (same standing
limitation as every prior embodiment-touching phase — see ADR 0012).

## Decisions

**Auth: a single shared bearer token (`REMOTE_UI_TOKEN`), fail-closed.**
Single-user V0.1 scope (per AGENTS.md's repo-wide convention) doesn't
justify building real session/user auth infrastructure — a shared secret
checked with `secrets.compare_digest` against the `Authorization: Bearer
<token>` header is proportionate. It fails *closed*: if `REMOTE_UI_TOKEN`
is unset, every gated route returns 503 rather than silently allowing
unauthenticated access — the opposite default from every other optional
integration in this codebase (Telegram, cloud TTS), deliberately, because
those degrade a convenience feature by being absent while this gates
actual robot control exposed on a port explicitly documented as
public-reachable. Gated routes: `GET/POST /robots/{robot_id}/...`
(state, behaviours, behaviour trigger — pre-existing, ungated since Phase
4), plus the two new routes below. `/messages`, `/voice/turn`,
`/webrtc/offer` (the companion-core-routed "Call Reachy" flow) are
deliberately left as they were — changing their auth model is a separate
concern from this phase's remote-control surface and out of scope here.
TLS termination is also out of scope: Caddy still serves plaintext on
:8080; real remote ("overseas") use needs a VPN/tunnel (e.g. Tailscale) or
TLS added at the Caddy layer, neither of which has anything to verify
against in this environment.

**Speak-through-robot bypasses companion-core entirely.** New
`POST /robots/{robot_id}/speak` takes `{text}`, calls the existing
`tts.py` (`EspeakTTS`, already used by `/voice/turn` and `/webrtc/offer`)
directly, and POSTs the resulting WAV to reachy-embodiment's new
`POST /audio/play` (ADR 0003 contract endpoint, deliberately unimplemented
until now — see AGENTS.md's Style section). No `companion_core_client`
call anywhere in this path, which is what actually satisfies "without
Companion Core" rather than just asserting it.

**Camera is polled JPEG over a `sendonly` WebRTC video track, not a real
video stream.** reachy-embodiment gains `GET /camera/frame` (the other
previously-deferred ADR 0003 endpoint, `capture_frame`), returning a
single JPEG. reachy-hub's new `POST /webrtc/telepresence/offer`
(`webrtc.py`'s `negotiate_telepresence`) wires a `CameraPollTrack` that
polls that endpoint at a fixed low rate (5fps) and wraps each JPEG as an
`av.VideoFrame` — the same MJPEG-over-HTTP pattern real IP cameras
commonly use at the transport level, plugged into a genuine WebRTC
media track rather than a raw `<img>` polling loop, so the same peer
connection could later carry a real video stream without a client-side
rewrite. This is a real, working transport, exactly like ADR 0012's
`SilentAudioTrack`/`WavPlaybackTrack` precedent — just not real video
content, because there is no physical camera here.
`SimulatedRobotBackend.capture_frame` draws a synthetic frame (Pillow) with
a marker that visibly moves between polls, so live verification can prove
frames are actually live, not a cached static image.

**`EmbodimentState.REMOTE`, unused since it was added in Phase 3/ADR
0004, is what this phase was for.** New `POST /remote {active: bool}` on
reachy-embodiment sets `ServiceState.remote_active` and transitions
`embodiment_state` to `REMOTE`/`IDLE`; reachy-hub's telepresence
negotiation calls it on connect and on peer-connection close/failure. It
was already excluded from the presence loop's idle-animation override
(`presence.py`'s `_HOMELAB_DRIVEN_STATES`), so this phase only had to
start setting it, not add the guard.

**`POST /audio/play`'s SPEAKING state is set and reverted synchronously
within the same request**, not scheduled against the WAV's real playback
duration. `SimulatedRobotBackend.play_audio` doesn't block for real
time (no physical speaker to wait on), so there's nothing for a
background revert task to synchronize against here — same reasoning ADR
0012 used for why "no room audio" holds by construction rather than by an
extra guard. Reverts to `REMOTE` if a telepresence session is active,
else `IDLE`.

**Separate negotiation function, separate route, not a video track bolted
onto `negotiate_call`.** `/webrtc/offer` (Phase 15) is push-to-talk audio
plus companion-core reasoning; `/webrtc/telepresence/offer` is a
recvonly-from-the-robot's-perspective video-only feed with no reasoning
involved. Sharing one endpoint for two purposes would need offer-shape
sniffing for no benefit — reachy-hub already runs two independent
`RTCPeerConnection`s per browser tab today for "Call Reachy" plus
telepresence, which is fine; they're unrelated features a user opens
separately.

## Consequences

- `services/reachy-hub/pyproject.toml` and
  `services/reachy-embodiment/pyproject.toml` both gain `pillow` — chosen
  over hand-rolling JPEG encode/decode against `av`'s lower-level image
  API, and over adding `av`/`aiortc` to reachy-embodiment (which has no
  other reason to depend on WebRTC machinery at all).
- Every pre-existing `/robots/{robot_id}/...` test needed an
  `Authorization` header added once these routes became gated — a real,
  visible cost of retrofitting auth onto routes that shipped without it
  since Phase 4, not just a Phase 16-local change.
- The telepresence page itself (`clients/web-pwa/telepresence.html`) is
  still served unauthenticated by `StaticFiles` — anyone who can reach
  Caddy can load the page shell, but every API call it makes fails without
  the token. Gating the static mount itself would need a bespoke
  auth-checked route in place of `StaticFiles`, which felt like more
  machinery than this V0.1 scope's actual threat model (a personal
  assistant, not a multi-tenant product) justifies; noted here rather than
  silently accepted.
- `docker-compose.yml` and `.env.example` gain `REMOTE_UI_TOKEN` (optional
  — unset means the whole remote-control surface 503s, matching the
  fail-closed default above). `deploy/homelab/Caddyfile`'s header comment
  is updated to reflect that auth now exists (TLS still doesn't).
