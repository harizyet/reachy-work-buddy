# deploy/reachy

Deployment for `reachy-embodiment` running on Reachy Mini Wireless itself
(local SDK execution against the Reachy daemon).

Not yet implemented — scaffolding only (Phase 0). Implementation starts in Phase 2/3.

## Phase 22: `reachy-mini-daemon` on the Jetson Nano

`install-reachy-venv.sh` and `reachy-mini-daemon.service` (added 2026-09-22)
set up and supervise the real `reachy-mini-daemon` process on a JetPack 4 /
Ubuntu 18.04 Jetson Nano, independent of this repo's own `uv`/Python 3.13
environment — see
[docs/verification/phase-22-inventory-2026-09-22.md](../../docs/verification/phase-22-inventory-2026-09-22.md)
for why: the `reachy_mini` Python SDK is itself just an HTTP/websocket
client to this daemon (which owns the actual serial/camera/audio hardware
access), so the daemon can run standalone under its own Python 3.10
environment while `reachy-embodiment`'s eventual `RobotBackend`
implementation talks to it over `localhost` HTTP, matching this repo's
services-talk-HTTP-only convention.

**`install-reachy-venv.sh` was transcribed from a working Nano's bash
history, not re-run end to end from a clean image** — see the caveats in
its header comment, including one unresolved fragile step (a PyGObject
version pin whose original failure reason wasn't captured). Validate on a
clean SD card before trusting it unattended, and expect to redo the
GStreamer source build steps to take a long time on Nano-class hardware.

This is unrelated to and does not resolve `reachy-embodiment`'s own
dependency blocker (torch/onnxruntime need `manylinux_2_28`+, this board's
glibc is 2.27) — see the inventory report's "Open questions" for that.
