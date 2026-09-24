# Phase 22b: camera acceptance and LOCAL-backend refactor (2026-09-24)

Coordinated across a homelab-side Claude Code session and a session
connected to the Jetson Nano via SSH, owner physically present throughout.

## Daemon found in an error state

Before any camera work, `curl localhost:8000/api/daemon/status` on the Nano
showed `state=error`, `error="No motors detected. Check if the power supply
is connected and turned on!"`. `systemctl is-active reachy-mini-daemon`
reported `active` despite this — the unit's own health does not reflect the
daemon's internal state, worth remembering for future triage. The journal
showed all 9 motors failing bus enumeration at boot; most likely motor
power was off at that boot. Because the daemon never fully started, its
media server (and therefore the camera) never started either, independent
of any embodiment-side code.

The owner checked motor power and ran `sudo systemctl restart
reachy-mini-daemon` themselves at the Nano terminal (daemon restart needs
owner presence/confirmation in the session actually running it — a
relayed approval from another session was correctly refused). After
restart: all 9 motors found and configured, wake-up motion completed,
`state=running`, `simulation_enabled=false`, `motor_control_mode=enabled`,
control loop at ~49 Hz with `nb_error=0`. One unexplained oddity:
`backend_status.ready` stayed `False` and `last_alive` stayed `None`
across every poll — not investigated further this session.
`/tmp/reachymini_camera_socket` appeared once the media server started.

## Camera acceptance (existing release/acquire code path)

With the daemon healthy, the owner approved a real `GET /camera/frame`
capture against the (at-the-time) release/acquire + OpenCV implementation:

- Two captures 3s apart, no deliberate scene change: both HTTP 200,
  ~260 KB JPEGs, 1920x1080, real room image (no simulator marker/text).
- The two files differed (`cmp`); no pixel-diff was computed (PIL not on
  the host venv), so this is not the acceptance matrix's full "fresh scene
  change corresponds to command" bar — it confirms a real capture, not a
  deliberate change/command correspondence.
- Cost: ~2.5–4s per capture. Daemon journal showed a full
  `/media/release` → `/media/acquire` cycle per call, tearing down and
  restarting the daemon's entire media pipeline (camera, audio, WebRTC
  signalling) on every single-frame request. The daemon recovered cleanly
  each time (`media_released=False` after, socket recreated, WebRTC
  producer re-registered), but this cost and disruption motivated moving
  to the SDK's recommended same-host path instead of continuing to use
  this escape hatch for routine capture.

## Refactor to reachy_mini's LOCAL media backend

Per Pollen's docs (`docs/reachy_mini/SDK/media-architecture`,
`.../SDK/python-sdk`), `media_backend="local"` reads frames from the
daemon's local GStreamer IPC socket without touching its camera/audio/
WebRTC ownership; `media_backend="no_media"` (the release/acquire+OpenCV
approach previously used) is documented as the escape hatch for callers
with no daemon on the same host, not the recommended same-host path.

Changed `ReachyDaemonBackend.capture_frame` (`services/reachy-embodiment/
src/reachy_embodiment/robot.py`) to keep one `ReachyMini(media_backend=
"local")` instance alive for the process lifetime and call
`.media.get_frame()` per request, converting the returned numpy BGR array
to JPEG via the same `cv2.imencode` already in use. Added the `reachy_mini`
dependency, PyGObject build dependencies in the Dockerfile, and a
`/tmp/reachymini_camera_socket` bind mount in `scripts/start-reachy.sh`
(only applied when the socket already exists, i.e. daemon healthy, and
only takes effect on container recreation, not `docker start`).

**What was actually verified** (dev machine, not the Nano):
- `PyGObject<=3.46.0,>=3.42.2` builds from source and imports cleanly
  against `python:3.13-slim` (Debian trixie) with the added apt packages.
- `gstreamer1.0-plugins-bad` at 1.26.2 on that same base image ships the
  `unixfdsrc` element the LOCAL backend needs (host GStreamer on the Nano
  was separately found at 1.24.13 with the same element — see the earlier
  Nano-side finding this session).
- `import reachy_mini` / `from reachy_mini import ReachyMini` succeed in
  the repo's shared dev venv (`uv sync --all-packages`).
- Full behavioural coverage via a fake `ReachyMini`/`media_client_factory`
  (`services/reachy-embodiment/tests/test_reachy_daemon_backend.py`):
  reads a frame, reuses one instance across calls (no per-call teardown),
  raises `RobotBackendError` on encode failure.

**What was NOT verified** (still open):
- The `reachy-embodiment` Docker image has not been rebuilt with these
  changes, nor run against the real daemon/socket on the Nano.
- No live frame has been captured through the LOCAL backend on real
  hardware — only the superseded release/acquire path was exercised live.
- `reachy_mini`'s native components
  (`reachy-mini-motor-controller`, `reachy-mini-rust-kinematics`) resolved
  fine for this dev machine's x86_64 Linux; aarch64/Jetson wheel
  availability for the container's Python 3.13 has not been checked.

## Fixes from Nano-side review before first live build

The Nano-connected session caught two issues while pulling this change,
before running anything, and reported them back rather than editing the
repo itself:

- **Version skew**: `uv.lock` had resolved an unpinned `reachy_mini>=1.8.4`
  to 1.11.0, while the Nano's installed daemon is 1.8.4 — the SDK client
  and daemon are two ends of one wire protocol over the local IPC socket,
  so an unpinned newer client risked a format the daemon doesn't speak.
  Pinned to `reachy_mini==1.8.4` to match; re-bump deliberately alongside
  the daemon, not independently.
- **Unhandled `None`**: 1.8.4's `get_frame()` returns `None` if the camera
  isn't initialized yet — most likely on the very first request after
  process start — and the code passed that straight to `cv2.imencode`,
  which raises `cv2.error` (an unhandled 500) rather than this class's
  usual `RobotBackendError` contract. Fixed to check for `None` and raise
  `RobotBackendError` explicitly; covered by a new unit test.

The same session also confirmed, from 1.8.4's own source, that
`ReachyMini(...)`'s daemon-check only scans processes and never
starts/stops the daemon — constructing it for media access alone causes
no motion, independent of any code here.

Camera remains **not production-accepted**: real capture succeeded once
via the old code path; the new recommended-path code exists and is
unit-tested but, as of this fix, still unverified against real hardware
end to end (image rebuild/live capture through LOCAL was in progress on
the Nano at the time of writing, gated on the owner confirming the
running production container's temporary `docker rm -f`).
