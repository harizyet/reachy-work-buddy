# ADR 0012: "Call Reachy" — WebRTC Audio, Push-to-Talk, PWA Serving

- Status: Accepted
- Date: 2026-09-22

## Context

docs/plan.md's Phase 15 row: "PWA + WebRTC real-time audio; synchronize
private audio with Reachy embodiment," exit criterion "Private earbuds
conversation while Reachy visibly listens/thinks/speaks." §11 adds:
"Private WebRTC phone call -> Reachy listening/thinking/speaking animation
with no room audio." Per ADR 0001, reachy-hub owns WebRTC and web UI;
`clients/web-pwa/` was scaffolding-only (a README) before this phase.

No streaming STT/TTS exists in this codebase — `stt.py`/`tts.py` (Phase 8)
are both whole-utterance-in/whole-utterance-out, exactly like a file
upload. A real "phone call" experience with continuous voice-activity
detection driving turn boundaries would need new real-time audio
processing infrastructure in reachy-hub that doesn't exist yet.

## Decisions

**Push-to-talk, not continuous VAD.** The user chose this explicitly when
asked, given the scope difference: reusing the existing non-streaming
STT/TTS pipeline as-is (same as `/voice/turn`) versus building new
real-time VAD-driven turn detection in reachy-hub. A `"control"`
`RTCDataChannel` alongside the audio track carries `start_talk`/`end_talk`
signals from a hold-to-talk button; reachy-hub only buffers/processes
audio between those two signals. This is a real, working implementation
of "WebRTC real-time audio" — the transport and media path are genuinely
real-time — just not a hands-free/VAD-driven turn model. A future phase
could add continuous VAD without changing this decision's transport layer,
only the turn-boundary signal source.

**`aiortc` for server-side WebRTC**, the standard pure-Python
implementation (already a broadly-used, actively maintained library, not
something built from scratch). No existing dependency or partial
scaffolding existed for this — greenfield.

**Turn orchestration (`CallTurnHandler`) is separated from aiortc/SDP
plumbing (`negotiate_call`, tracks, buffering)**, mirroring
`email/workflow.py` vs. `email/sender.py`'s split in companion-core: the
former is unit-testable with fakes, the latter needs a real peer
connection to mean anything, so it's covered by a real
(non-browser) `aiortc` client test instead of a mock.

**Every WebRTC-call turn is `channel=Channel.WEB`,
`input_modality=InputModality.VOICE`.** `Channel.WEB` already existed
(session.py) and was already the natural SILENT-mode/privacy-override
fallback target in `response_policy.py` (a "quiet, non-Reachy" channel) —
this dovetails with "private audio in earbuds" without inventing a new
channel value. `InputModality.VOICE` applies the identical ADR 0011 rule
`/voice/turn` already enforces: spoken audio, regardless of which
transport carried it, can never confirm a destructive action. The
transport changing (HTTP file upload vs. WebRTC) does not change that
rule, and nothing in `webrtc.py` special-cases it — `handle_inbound_message`
is called exactly the same way every other voice-sourced turn is.

**Reply audio only ever flows over the peer connection.** Reachy has no
speaker output wired to hardware in this environment (no physical robot,
same as every prior voice-touching phase) — "no room audio" holds by
construction, not because of an extra guard that could be bypassed. Each
turn does trigger the robot's real `listening`/`thinking`/`speaking`
behaviours (already in `Behaviour`'s vocabulary since ADR 0003 — no new
behaviour names were needed) through the existing `EmbodimentClient`, so
the *physical* half of "Reachy visibly listens/thinks/speaks" is real.

**`WavPlaybackTrack` always resamples to a fixed 48kHz mono format before
framing.** Discovered live-testing, not by inspection: `aiortc`'s
`RTCRtpSender` sets up its Opus encoder/resampler from the *first* audio
frame it ever sees on a track and does not re-adapt when
`RTCRtpSender.replaceTrack` swaps in a different-format track later in the
call. The initial placeholder track (`SilentAudioTrack`, needed because
the SDP requires a sendrecv audio m-line from connection time, before any
reply exists) is 48kHz mono; `tts.py`'s espeak-ng output is typically
~22050Hz mono. Without resampling, replacing the placeholder with a raw
TTS-rate track raised `ValueError: Frame does not match AudioResampler
setup` deep inside aiortc's own encode path — a genuine infra bug a mock
transport would never have surfaced.

**`clients/web-pwa/` is served by reachy-hub itself**, not a separate
static host: `app.py` mounts the directory via FastAPI's `StaticFiles` at
`/app`, reachable through Caddy at `/hub/app/` (Caddy's `handle_path`
strips the `/hub` prefix, so the PWA's own fetch calls to
`/hub/webrtc/offer` resolve correctly from a page served under that same
prefix). `services/reachy-hub/Dockerfile` now also `COPY clients/web-pwa/`
into the image. No build step, no bundler — plain HTML/CSS/JS, with a
`manifest.json` + trivial no-op `sw.js` for PWA installability (a call
needs a live connection anyway; there's no offline story worth building).

## Consequences

- `services/reachy-hub/pyproject.toml` gained `aiortc`/`numpy` as direct
  dependencies (pulling in `av`, `cryptography`, `pylibsrtp`, `aioice`,
  etc.) — the first meaningfully large dependency addition to reachy-hub
  since `faster-whisper` (Phase 8).
- **Known, untested-in-this-environment limitation**: a browser on a
  different machine than the Docker host needs reachy-hub's WebRTC media
  (UDP/ICE) directly reachable — Caddy only proxies the signaling
  `POST /webrtc/offer` over HTTP, never the RTP audio itself, and Docker's
  default bridge networking NATs the container's ICE host candidates so a
  remote peer can't reach them. This environment has no real browser and
  no second machine to test that path with; live verification here used a
  real `aiortc` Python client instead (a genuine WebRTC peer, just not a
  browser) against the actual deployed Caddy stack, which exercises the
  identical signaling and media code paths the PWA would. Fixing the
  cross-machine case (e.g. `network_mode: host` for reachy-hub, or a fixed
  published UDP port range, or a TURN server) is deferred until there's a
  real second machine/browser to verify it against — speculative
  networking changes with nothing to test them against would just be
  guesses.
- `shared/models/embodiment.py`'s `Behaviour` enum needed no changes —
  `LISTENING`/`THINKING`/`SPEAKING`/`WAITING` already existed and were
  already wired to `EmbodimentState` transitions in
  `reachy_embodiment/behaviours.py` (ADR 0003), confirmed before writing
  any code rather than assumed.
