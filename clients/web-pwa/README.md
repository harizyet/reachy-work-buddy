# web-pwa

"Call Reachy" (Phase 15) — real-time WebRTC audio to `reachy-hub`.

Push-to-talk: hold the button, speak, release. The browser sends audio
only while the button is held (`localTrack.enabled` toggled) and signals
start/end over a `"control"` `RTCDataChannel`; `reachy-hub`'s
`POST /webrtc/offer` (`services/reachy-hub/src/reachy_hub/webrtc.py`) runs
the same STT -> agent -> TTS pipeline `POST /voice/turn` (Phase 8) uses,
triggers the target robot's real `listening`/`thinking`/`speaking`
behaviours in step with it, and plays the reply back over the same peer
connection — never through Reachy's speaker.

No build step: plain HTML/JS/CSS, no bundler, no framework. Served
directly by `reachy-hub` (`app.py` mounts this directory at `/app` via
`StaticFiles`) — reachable through Caddy at `/hub/app/`. `manifest.json` +
`sw.js` (a no-op passthrough — a call needs a live connection anyway, no
offline story to build) are what make it installable as a PWA.

Known limitation (see `webrtc.py`'s module docstring): a browser on a
different machine than the Docker host needs reachy-hub's WebRTC media
(UDP/ICE) reachable directly — Caddy only proxies the signaling
`POST /webrtc/offer`, not the RTP audio itself, and Docker's default
bridge networking NATs the container's ICE host candidates. Untested with
a real cross-machine browser in this environment; live verification used
a real (non-browser) `aiortc` Python client instead — see
`deploy/homelab/README.md`.
