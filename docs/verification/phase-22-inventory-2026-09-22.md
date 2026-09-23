# Phase 22 inventory and compatibility report — 2026-09-22

Historical inventory and measurements. Later backend/launcher work and live
Nano startup supersede this report's original “next steps”; see the
[bring-up record](phase-22-bring-up.md) and current
[deployment guide](../deployment.md#robot-host-and-jetson-nano). In particular,
the live daemon mounts the initially inventoried routes under `/api`.


Gathered by a Claude Code session running directly on the physical Jetson
Nano (`reachy-mini`), coordinated by a session on the homelab machine.
Device identity was independently verified before trusting this report —
see "Device verification" below. Raw findings only; no code, ADR, or
architecture decisions were made during this pass.

Status: **BLOCKED** on repo-compat (deliverable 1 of Phase 22). Hardware
inventory is complete; this repo cannot install its locked dependencies on
this board as currently pinned. See "Open questions / next steps."

## Device verification

Before trusting anything else in this report, the reporting session was
asked to paste raw, unparaphrased output identifying the hardware:

- `cat /proc/device-tree/model` → `NVIDIA Jetson Nano Developer Kit`
- `uname -a` → `Linux reachy-mini 4.9.253-tegra #1 SMP PREEMPT ... aarch64 aarch64 aarch64 GNU/Linux`
- `cat /etc/nv_tegra_release` → `# R32 (release), REVISION: 7.1, GCID: 29818004, BOARD: t210ref, EABI: aarch64, DATE: Sat Feb 19 17:05:08 UTC 2022`
- `hostname` → `reachy-mini`; `hostname -I` → `10.180.1.140 172.17.0.1 fdd4:...` (Tailscale/IPv6 ULA present)
- `lsusb` and `/dev/video*` / `/dev/ttyACM*` / `/dev/ttyUSB*` matched a real
  attached USB peripheral set (see Reachy attachment below)

Confirmed genuine Tegra hardware, not a VM/container impersonating one.

## Board / OS

- NVIDIA Jetson Nano Developer Kit, Tegra T210 (`t210ref`), 4x Cortex-A57, aarch64
- Ubuntu 18.04.6 LTS (Bionic Beaver); L4T R32.7.1 = **JetPack 4.6.1** (EOL,
  as expected for an original Nano); kernel `4.9.253-tegra`; glibc **2.27**
- RAM: 3.9 GB total (~1.6 GB available at idle per initial check; 3956 MB
  per `tegrastats`)
- Storage: 59 GB root (`mmcblk0p1`), 35 GB free (39% used)
- Power mode: `nvpmodel -q` → MAXN (10W/unrestricted). Fan mode unset in
  `nvpmodel` (warns "fan mode is not set"); `pwm-fan` sysfs `target_pwm=0`
  (idle, no active load at check time). All thermal zones 24-38°C, well
  under the 100.5°C CPU / 101°C GPU throttle trip points. No undervoltage
  warnings in `dmesg`.
- Time sync: `systemd-timesyncd` active and synced; TZ `Asia/Jakarta`
- Desktop: full GNOME session on physical display (Xorg, tty1, seat0) —
  **not headless**. Chromium 97.0.4692.71 installed (arm64, Bionic build).
- Network: `wlan0` up on SSID "Safelan", `10.180.1.140/24`; `eth0`
  down/unavailable (no cable attached); `docker0` bridge present.
- Docker 20.10.7 installed. `docker compose` v2 plugin and `docker buildx`
  were **not** installed at inventory time. Current setup guidance is in
  [the Docker toolchain guide](../development.md#docker-toolchain), including
  the subsequently confirmed old-engine BuildKit requirement.
- Hostname: `reachy-mini`

## Reachy variant / physical attachment

**Reachy Mini confirmed attached**, by device identity, not inference:

- `/etc/udev/rules.d/99-reachy-mini.rules` present, rules for the CH340
  USB-serial chip (`1a86:55d3`) and vendor ID `38fb:1001`
- `/dev/video0` enumerates as `SunplusIT_Inc_Reachy_Mini_Camera_J20251118V0`
- `/dev/snd/by-id/usb-Pollen_Robotics_Reachy_Mini_Audio_...` — vendor-strings
  literally as Pollen Robotics Reachy Mini Audio
- `/dev/ttyACM0` present (`dialout` group)
- Two unlabeled Pollen Robotics vendor-ID (`38fb:`) USB devices
  (`38fb:1002`, `38fb:1001`) — almost certainly the Mini's composite
  motor-controller/board interfaces

This is the smaller **Reachy Mini**, not the larger Reachy/Lite.

## Pre-existing, working SDK (separate from this repo)

Found on the box already, independent of `reachy-work-buddy`:

- `~/reachy-venv`: a working Python **3.10.18** venv (not this repo's
  pinned 3.13, not provisioned by this repo's `uv` config) with
  `reachy_mini` 1.8.4, `reachy_mini_motor_controller` 1.5.6,
  `reachy_mini_rust_kinematics` 1.0.3, `numpy` 2.2.6
- `~/reachy/hello.py`: a working example script against that SDK
  (`ReachyMini(...).goto_target(...)`) — i.e. real motor control has
  already been demonstrated from this exact machine, outside this repo
- `~/gstreamer-1.24-src`, `~/gst-plugins-rs`, `~/.reachy-gstreamer-env` →
  `/opt/gstreamer-1.24`: GStreamer 1.24 built from source with custom Rust
  plugins. Not investigated further — flagged as evidence of nontrivial
  prior setup work, not verified as still required or why the distro
  package wasn't sufficient.

None of this is wired into `reachy-work-buddy`'s own dependency chain
today; it's a parallel, already-functioning stack on the same hardware.
This is the most direct evidence available that this repo's eventual
`RobotBackend` real-hardware adapter should probably target this existing
SDK/venv rather than a fresh integration path.

## Repo dependency compatibility — FAILS, root cause identified

Repo cloned fresh to `~/reachy-work-buddy` on the Nano (public GitHub
clone over HTTPS, no credentials needed).

- No system Python ≥3.9 available (apt tops out at 3.6.9 on Bionic).
- The `uv` installer itself had to fall back to a **musl static build** —
  its normal glibc build considered this board's glibc 2.27 too old.
- `uv python install 3.13` **succeeded** — standalone
  `cpython-3.13.15-linux-aarch64-gnu`, 27.9 MB, ~3s. Python 3.13 itself is
  not the blocker.
- `uv sync --all-packages` at repo root **fails immediately**:
  ```
  error: Distribution `torch==2.9.1+cpu @ registry+https://download.pytorch.org/whl/cpu` can't be installed
  because it doesn't have a source distribution or wheel for the current platform
  hint: You're on Linux (`manylinux_2_27_aarch64`), but torch (v2.9.1+cpu) only has wheels for:
  manylinux_2_28_aarch64, manylinux_2_28_x86_64, win_amd64, win_arm64
  ```
- Tested per-service in isolation:
  - `--package reachy-embodiment` → same torch/manylinux_2_28 error
    (via `silero-vad` → torch/torchaudio)
  - `--package companion-core` → same torch/manylinux_2_28 error
    (via `sentence-transformers` → torch)
  - `--package reachy-hub` → **also fails**, but on a different package:
    `onnxruntime==1.30.0` (transitive via `faster-whisper`), same
    manylinux_2_28-only story
- **Root cause: this board's glibc is 2.27 (`ldd --version`); every
  blocking wheel is manylinux_2_28+-only.** This is a platform-wide
  one-ABI-generation gap, not specific to the CPU-torch pin or to
  ML-heavy services — **zero of the three services can `uv sync`
  natively on this OS as currently locked**, including reachy-hub, which
  has no direct torch dependency at all.
- Not attempted: building torch/onnxruntime from source (assessed as a
  multi-hour/likely-infeasible undertaking on Nano-class hardware with
  JetPack 4's toolchain). Not attempted: a newer-glibc Docker base image
  (e.g. Ubuntu 22.04) to sidestep this for CPU-only wheels — container
  userland glibc is independent of host glibc for non-GPU workloads, so
  this is untested but plausible, and is the most promising next thing to
  try. `docker compose`/`buildx` weren't installed yet at the time of this
  check, so it was treated as out of scope for this pass.
- JetPack 4's EOL status is therefore not just a future-security-patches
  concern — it is an **active blocker** to installing this repo's current
  pinned dependencies at all, on any service.

`~/reachy-work-buddy` was left on disk on the Nano (2.6M; `.venv` only 96K
since sync failed before downloading real packages) pending a decision on
next steps.

## Nano-role / topology finding (ADR 0004 conflict)

No evidence of a second "Reachy onboard computer" was found. The camera,
audio device, and motor-controller are all USB-attached directly to this
Jetson Nano, and the only working robot-control SDK reachable is the
pre-existing `~/reachy-venv` on this same box — consistent with Reachy
Mini's public design as a compact bot with no independent onboard Linux
compute, driven entirely by an external companion computer over USB.

If that holds, **this Nano is not optionally the embodiment host per the
plan's architecture table — it may be the only physically possible one**,
which conflicts with [ADR 0004](../adr/0004-offline-fallback.md)'s
requirement that embodiment survive a homelab/Jetson outage independently.
Combined with the dependency-install failure above, there is currently
**no working presence loop from this repo on real hardware at all** — the
pre-existing SDK works, but `reachy-work-buddy`'s own `reachy-embodiment`
service can't even install here yet, degraded-outage-survivable or not.

This finding is not resolved here; per [docs/phase-22-23.md](../phase-22-23.md)
it needs a reviewed ADR amendment, not a code-level decision. The "Reachy
onboard computer, if present" row in that doc's architecture table should
likely be treated as confirmed-absent for this specific physical setup,
pending confirmation that Reachy Mini hardware truly has no onboard
compute beyond what's visible from the USB side.

## Follow-up investigation: targeting `~/reachy-venv` (2026-09-22, read-only)

Investigated whether `reachy-embodiment` should run under `~/reachy-venv`'s
Python 3.10 instead of this repo's `uv`/3.13 environment. Read-only
throughout: no installs into `reachy-venv`, no repo edits, no commits.

**Finding: this would not have fixed the dependency wall above.** The
torch/onnxruntime blocker is a **glibc-floor issue, Python-version
independent**, confirmed against actual PyPI/download.pytorch.org wheel
tags:

- `torch` 2.9.0/2.9.1+cpu aarch64: every build from cp310 through cp314t
  is `manylinux_2_28_aarch64` — including cp310, `reachy-venv`'s exact
  version. No cp310 aarch64 torch wheel satisfies this board's glibc 2.27
  either.
- `onnxruntime` 1.30.0 aarch64: cp311+ only, also `manylinux_2_28` —
  doesn't ship a cp310 wheel at all (reachy-hub's blocker, separately).

`silero-vad`'s torch dependency (`services/reachy-embodiment/src/.../audio/vad.py`,
real barge-in-detection functionality, not incidental) would hit the
identical error under Python 3.10 as under 3.13.

Separately, `reachy-embodiment`'s own source already requires **Python
≥3.11** independent of the repo's declared `>=3.13` floor: `app.py` and
`presence.py` use `from datetime import UTC`, and
`shared/models/embodiment.py` (imported for `Behaviour`/`EmbodimentState`)
uses `enum.StrEnum` — both added in 3.11. Confirmed directly:
`from datetime import UTC` raises `ImportError` on `reachy-venv`'s Python
3.10.18. Running this service under that venv would fail on import before
dependencies were even reached.

**However, the `reachy_mini` SDK's own compiled packages are not the
blocker at all** — checked directly on PyPI:

- `reachy_mini` 1.8.4 is pure-Python (`py3-none-any`), no version pin.
- `reachy_mini_motor_controller` 1.5.6 and `reachy_mini_rust_kinematics`
  1.0.3 both ship `cp313-cp313-manylinux_2_17_aarch64` wheels —
  `manylinux_2_17` is far more permissive than this board's glibc 2.27.
  These install cleanly under Python 3.13 today.

So there is no SDK-compatibility reason to run `reachy-embodiment` on
Python 3.10. The only real blocker is torch (via VAD), unresolved
regardless of venv/Python choice, until one of: (a) a
manylinux_2_28-capable environment (the container route, still
deprioritized, not ruled out), (b) VAD deferred/reimplemented without
torch for the Nano deployment specifically, or (c) building torch from
source (assessed as very likely infeasible on Nano-class hardware/toolchain,
not attempted).

### Is `~/reachy-venv` reproducible?

**Reconstructible from `~/.bash_history`, but not currently captured as a
script or recipe anywhere** — no `requirements.txt`, no install script,
nothing checked in. Sequence found, in order:

1. Built Python 3.10.18 from source (`./configure --prefix=/opt/python310 && make -j4 && sudo make altinstall`) — Ubuntu 18.04's apt tops out at 3.6.
2. `python3.10 -m venv ~/reachy-venv`; `pip install reachy-mini` — clean off PyPI, no special index.
3. `apt install`ed GTK/cairo dev headers for PyGObject, with undocumented
   trial-and-error version pinning: `PyGObject==3.46.0` tried and
   abandoned for `3.44.1`, no recorded reason.
4. udev rules + `dialout` group membership for serial access — this part
   *is* durably captured, in `/etc/udev/rules.d/99-reachy-mini.rules`.
5. Built **GStreamer 1.24 from source via meson**
   (`/opt/gstreamer-1.24`), including hand-patching `gstdrmdumb.c` (a
   `DRM_FORMAT_NV15` compile error, guarded with `#ifdef`) — the distro
   package wasn't usable for whatever media pipeline `reachy_mini` needs.
6. Built `gst-plugins-rs` from source via a freshly-installed Rust
   toolchain, specifically `gst-plugin-webrtc`, manually installed the
   resulting `.so` into GStreamer's plugin dir.
7. `~/.asoundrc` set up via `reachy_mini.media.audio_utils.write_asoundrc_to_home()`
   for the ReSpeaker audio card; verified with raw `gst-launch-1.0`/`arecord`/`aplay`.
8. Manually ran `reachy-mini-daemon --headless --log-level DEBUG` to test.

**Verdict: reproducible by a human replaying bash history, not from a
documented/scripted deployment.** No systemd service exists — the daemon
is not currently running (confirmed via `ps`/`systemctl`), only invoked
manually for testing. A reflashed SD card would need this exact 8-step
sequence redone from memory/history, including the undocumented PyGObject
trial-and-error and the GStreamer source patch. This is real, valuable,
undocumented setup work that currently lives nowhere durable — worth
capturing as an actual install script independent of what's decided about
`reachy-embodiment`'s own Python target.

### `RobotBackend` vs. the `reachy_mini` API shape

**Architectural finding (the important one):** `ReachyMini.__init__`'s
signature (`robot_name, host="reachy-mini.local", port=8000,
connection_mode="auto", spawn_daemon=False, use_sim=False, ...`) reveals
that **the `ReachyMini` Python class is itself an HTTP client to
`reachy-mini-daemon`'s own FastAPI server** — it does not talk to
serial/USB hardware in-process. All the heavy native complexity
(PyGObject, custom GStreamer, Rust kinematics/motor-controller
extensions) lives in the **daemon process**, reachable over
`localhost:8000` (or network).

This reframes the question: `reachy-embodiment` does not need to share an
interpreter with `reachy-venv` at all. The daemon can run standalone
under `reachy-venv` (already proven working) as its own supervised
process, while `reachy-embodiment`'s `RobotBackend` implementation is a
thin HTTP/websocket client to it, running under whatever Python
`reachy-embodiment` itself ends up on. This matches this repo's own
"services talk HTTP only" convention (AGENTS.md) closely — the daemon
slots in as one more HTTP dependency, not a shared-interpreter one. It
does **not** remove the torch/VAD blocker above, but it does mean the
motor/camera/audio control piece specifically has a clean, non-invasive
integration path, already anticipated by `robot.py`'s existing comment
about "wrapping the reachy_mini SDK the way Jarvis's RobotController does."

- **Reasonable fit:** `ReachyMini.goto_target()` / `set_target()` /
  `play_move()` / `async_play_move()` / `cancel_move()` map conceptually
  onto `RobotBackend.play_behaviour(name, parameters)` — named behaviours
  translating into specific pose/move sequences, the pattern the existing
  code comment already expects.
- **Real mismatch worth flagging:** `RobotBackend.capture_frame() ->
  bytes` is a stateless "give me one JPEG" call. `ReachyMini`'s media
  surface is session-oriented instead — `acquire_media()` /
  `release_media()` / `media_released` / `start_recording()` /
  `stop_recording()` — closer to "open a stream, hold it, close it."
  Implementing `capture_frame()` on top of this needs real state
  management (acquire once, pull frames from a live session, decide when
  to release), not a 1:1 method mapping.
- No obvious `connected`/`sim` property was found on `ReachyMini` itself;
  that status likely needs to come from the daemon's own connection/health
  state instead — the daemon CLI has `--sim`/`--mockup-sim`/`--headless`
  flags, so the daemon clearly tracks this, just not surfaced as a simple
  client-side property from what was seen. Not investigated further:
  `reachy-mini-daemon`'s actual HTTP/websocket API surface for
  camera/audio/status.

## Newer-glibc container test for torch/onnxruntime — RESOLVED, works but with caveats (2026-09-22)

Initially blocked on `docker run` permission-denied (Nano user not in the
`docker` group; needed a human to run `sudo usermod -aG docker reachy`
and reboot for it to take effect — done by the owner). Once unblocked:

- `docker run --rm hello-world` works without sudo — group membership
  confirmed active post-reboot.
- Torch pin unchanged: `torch==2.9.1+cpu` (root `pyproject.toml` +
  `uv.lock` line 239). Tested inside `ubuntu:22.04` arm64 (glibc 2.35,
  confirmed independent of the host's 2.27 as expected).
- `pip install torch==2.9.1+cpu --index-url
  https://download.pytorch.org/whl/cpu` **installs and imports cleanly**:
  `python3 -c "import torch; print(torch.__version__)"` → `2.9.1+cpu`.
  ~80s install (network-bound). **The container route works** — this is
  the fix for the native `uv sync` failure documented above.
- **Resource overhead:** torch package itself 418MB; full writable
  container layer with python3+pip+torch ~1.06GB (base `ubuntu:22.04`
  arm64 alone is 69.8MB). Memory: torch import peak RSS ~200MB, container
  idle post-import ~179MB. **Host context that matters:** this board has
  3.9GB total RAM but only ~537MB free / ~1.6GB available at test time —
  2GB already used, mostly by the full GNOME desktop session (this board
  is non-headless, per the earlier inventory). 1.9GB swap, 168MB in use.
  Disk isn't a concern (35GB free, ~1.1GB footprint), but **RAM is a real
  open question**: torch/VAD + the rest of `reachy-embodiment`'s stack
  (whisper/sentence-transformers etc.) + container overhead + the
  existing desktop session, all inside ~1.6GB available, is a plausible
  swap-thrashing scenario that wasn't load-tested.
- **Device passthrough:** `--device=/dev/video0 --device=/dev/ttyACM0
  --device=/dev/snd` all showed up inside a throwaway container with host
  permissions/major:minor preserved. **Caveat: tested as root (uid=0)**,
  which bypasses the `dialout`/`video`/`audio` group gating entirely —
  not representative of how `reachy-embodiment` should actually run
  (non-root, matching GIDs or `--group-add`). Non-root passthrough and
  actually opening a device from inside the container (grabbing a camera
  frame, writing to the serial port) were **not tested** — only file
  visibility/permission bits.

**Assessment (updated below): "the wheel installs in a container" is
proven, and non-root device access is now also proven — only the RAM
headroom question remains open.**

## Real bug found and fixed: `silero-vad` missing its own `onnxruntime` requirement (2026-09-22)

Found during the memory load test below, **platform-independent, not
Nano-specific**: `silero-vad` 6.2.2 (what this repo's unpinned
`silero-vad>=5.1` currently resolves to) unconditionally imports
`onnxruntime` from its `sequence_vad.py` at module load time, but its own
wheel metadata does **not** declare `onnxruntime` as a required
dependency — only under an opt-in `onnx-cpu`/`onnx-gpu` extra that
nothing in this repo requested. Reproduced directly: `uv sync --frozen
--package reachy-embodiment --no-dev` (matching this service's actual
Docker build shape) followed by `from silero_vad import VADIterator,
load_silero_vad` (exactly what `audio/vad.py` does) raised
`ModuleNotFoundError: No module named 'onnxruntime'`.

This had been silently masked in every dev/CI run so far because `uv sync
--all-packages` shares one venv across all three services (AGENTS.md), and
`reachy-hub`'s `faster-whisper` dependency pulls `onnxruntime` in
transitively for itself — the same class of masking AGENTS.md already
documents for `python-multipart`. `reachy-embodiment`'s own Docker image,
built with `--package reachy-embodiment` only, gets none of that; it would
have failed to start on any platform, not just this Nano.

**Fixed:** `services/reachy-embodiment/pyproject.toml` now declares
`silero-vad[onnx-cpu]>=5.1` instead of the bare extra-less pin. Re-locked
(`uv lock`), verified the isolated `--package reachy-embodiment` install
now imports cleanly, restored the full workspace venv, and re-ran the
full suite: **300/300 tests pass**, `ruff check services shared` clean.
Committed on the homelab side, not by the Nano session (which correctly
reported this as a finding rather than patching it itself, per its
read-only instructions).

## Non-root device passthrough — RESOLVED, works correctly (2026-09-22)

Follow-up to the root-only passthrough caveat above.

- Host device gating: `dialout:20`, `video:44`, `audio:29` (matches the
  udev rule / earlier inventory; `reachy` is already in all three).
  `/dev/ttyACM0` is `crw-rw-rw-` — **world-accessible, not group-gated**,
  the odd one out. `/dev/video0` is `crw-rw----` (video group) plus an
  extra ACL entry (`getfacl`: `user:gdm:rw-`) for the desktop session's
  own camera access — a second, unrelated access mechanism on that one
  device, flagged for awareness.
- A throwaway container run as `--user 1000:1000 --group-add 20
  --group-add 44 --group-add 29` (dialout/video/audio by numeric GID, no
  need for a matching named user inside the image) with the same
  `--device=/dev/video0 --device=/dev/ttyACM0 --device=/dev/snd` flags as
  before: `id` inside correctly showed
  `uid=1000 gid=1000 groups=1000,20(dialout),29(audio),44(video)`, and
  `stat`/`ls -la` showed correct ownership/permission bits.
- Actual open-then-close (read-only, no writes, no motor interaction)
  succeeded non-root on all three: `/dev/video0`, `/dev/ttyACM0`,
  `/dev/snd/controlC0`.
- **Negative control** (same non-root user/device flags, no
  `--group-add`): `/dev/video0` and `/dev/snd/controlC0` correctly
  produced `PermissionError: [Errno 13] Permission denied`; `/dev/ttyACM0`
  opened anyway because it's world-writable regardless of group, per the
  device-gating note above. Confirms `--group-add` is doing real
  gating work for video/audio, not incidentally matching.

**No gap found.** `--group-add <gid>` by numeric GID is sufficient for
correctly-permissioned, non-root device access to all three device
classes `reachy-embodiment` would need. Combined with the torch-in-
container result, containerizing `reachy-embodiment` on this board is
**mechanically viable**; the RAM headroom question (only ~1.6GB available
on this 3.9GB, non-headless board) is now the only unresolved concern
blocking a "yes, deploy this way" conclusion, not device access. All
test containers/images were removed after; no repo changes made on the
Nano.

## `reachy-mini-daemon` HTTP/WS API surface (2026-09-22, design prep, read-only)

Read from `reachy_mini/daemon/app/routers/` in the venv (source only —
the daemon wasn't started, to avoid disturbing idle hardware state).
FastAPI-generated, so `/docs`/`/openapi.json` are live once it runs.
Prep for designing `RobotBackend`'s HTTP client; `RobotBackend` itself was
not implemented.

- **Motion/pose** (`move.py`, prefix `/move`): `POST /move/goto`
  (`{head_pose, antennas, body_yaw, duration, interpolation}` → `{uuid}`,
  async/tracked); `POST /move/stop` (cancel by uuid); `POST
  /move/play/wake_up`, `POST /move/play/goto_sleep`; `POST
  /move/play/recorded-move-dataset/{dataset}/{move_name}` — plays a named
  recorded move, the natural target for `play_behaviour(name, params)`;
  `POST /move/set_target` (immediate single-frame target, rejected with
  `{"status":"ignored"}` if a move is already running); `WS
  /move/ws/set_target` (streaming version); `WS /move/ws/updates` (move
  lifecycle events by uuid). `motors.py`: `GET /motors/status`, `POST
  /motors/set_mode/{mode}` (enabled/disabled/gravity_compensation).
- **Camera** (`camera.py`, prefix `/camera`): only `GET /camera/specs`
  (resolution list, intrinsics `K`, distortion `D`) — **no REST
  single-frame endpoint exists**; video is WebRTC-only
  (`gstwebrtc-api-2.0.0.min.js`, `sdk_ws.py`'s `/ws/sdk`,
  `media_server.py`). Confirms the earlier-flagged mismatch:
  `RobotBackend.capture_frame() -> bytes` has no 1:1 daemon equivalent —
  implementing it needs either a minimal WebRTC/GStreamer receiver inside
  `reachy-embodiment` to pull one frame off the stream, or using
  `/media/release` + direct V4L2/OpenCV access on `/dev/video0` while
  media is released from the daemon, bypassing the daemon's own camera
  path for that one call.
- **Audio/media** (`media.py`, prefix `/media`): `POST /media/release` /
  `POST /media/acquire` (daemon gives up/reclaims camera+audio for direct
  external access — the release-then-OpenCV/sounddevice path above);
  `GET /media/status` → `{available, released, no_media}`. Playback is
  two-step: `POST /media/sounds/upload` (multipart, extension-allowlisted
  + content-validated) returns a server path, then `POST
  /media/play_sound {"file": ...}` plays it — no duration is returned, so
  `RobotBackend.play_audio()`'s duration return would still need
  client-side computation from the WAV header, same as
  `SimulatedRobotBackend` already does. `POST /media/stop_sound`, `POST
  /media/clear_incoming_audio` (barge-in: drop buffered outgoing audio).
  `POST /media/wobbling/enable|disable` — audio-reactive head movement,
  unrelated to the current `RobotBackend` contract, possible future nicety.
- **Connection/status** (`daemon.py` prefix `/daemon`, `state.py` prefix
  `/state`): `GET /daemon/status` → `DaemonStatus{state,
  simulation_enabled, mockup_sim_enabled, backend_status, error, wlan_ip,
  version, hardware_id, camera_specs_name, no_media, media_released}` —
  **this is the `connected`/`sim` source** not found on the `ReachyMini`
  client class itself: `simulation_enabled`/`mockup_sim_enabled` map to
  `.sim`, `state`/`backend_status`/`error` map to `.connected`. `GET
  /daemon/hardware-id` — stable robot ID (audio device's USB serial),
  same across reboots — a possible cross-check against the udev-detected
  serial above. `GET /daemon/robot-app-lock-status` — free /
  local_app / remote_session, i.e. whether another client already holds
  the robot; relevant if `reachy-embodiment` and a manually-run SDK
  script could ever race for control. `GET /state/full` — batched
  present pose/joints/body-yaw/antennas snapshot; `WS /state/ws/full` —
  same, streamed at configurable frequency.
- **Possible alternative to torch/Silero VAD on the Nano specifically:**
  `GET /state/doa` returns `{angle, speech_detected}` — direction-of-arrival
  *and* a speech-detected boolean, computed by the daemon itself from the
  mic array (not raw audio samples, just the boolean + angle). Not a
  drop-in replacement for Silero's actual purpose in
  `services/reachy-embodiment/src/.../audio/vad.py` (barge-in timing
  precision may differ, and full STT still needs the raw audio), but
  worth evaluating as reachy-embodiment's presence-loop barge-in signal
  *specifically on the Nano*, since it would sidestep the glibc wall
  entirely for that one piece. Accuracy/latency not evaluated — flagged
  as an option, not a decision.
- Default `--fastapi-host` is `127.0.0.1` (`0.0.0.0` only with
  `--wireless-version`) — localhost-only unless told otherwise, fine as
  long as `reachy-embodiment` runs on this same Nano, which is what
  Phase 22's architecture already calls for. Reflected in
  `deploy/reachy/reachy-mini-daemon.service`.

## Install script + systemd unit landed (2026-09-22)

The 8-step manual sequence for `~/reachy-venv`/GStreamer/`gst-plugins-rs`
was transcribed into `deploy/reachy/install-reachy-venv.sh`, plus
`deploy/reachy/reachy-mini-daemon.service` to supervise the daemon. **Not
re-run end to end** — the source Nano already had a working environment
from prior manual setup, and a full from-scratch rebuild (Python +
GStreamer + gst-plugins-rs all from source) takes a long time on
Nano-class hardware, so it wasn't attempted before landing. Treat as a
faithful transcription and strong first draft, not independently proven;
validate on a clean SD card before relying on it. The unresolved
PyGObject `3.46.0`-vs-`3.44.1` question (see earlier section) is flagged
inline in the script rather than guessed at.

## Memory load test — RESOLVED, comfortable headroom (2026-09-22)

Scope corrected first: `reachy-embodiment`'s actual dependency set is
narrower than "the full multi-service stack" — just `fastapi`,
`uvicorn[standard]`, `silero-vad` (torch/torchaudio/now onnxruntime),
`numpy`, `pillow`, `python-multipart` (per its `pyproject.toml`).
`sentence-transformers`/`faster-whisper` belong to `companion-core`/
`reachy-hub`, which run in the homelab, not on the Nano.

Container: `ubuntu:22.04` (glibc 2.35), Python 3.13.15, venv with the
full corrected dependency set including `onnxruntime` (the fix above).
Measured `VmRSS` from `/proc/self/status` inside the test process at each
stage; inference used a 512-sample (32ms@16kHz) chunk matching
`vad.py`'s exact `CHUNK_SAMPLES`/`VADIterator` call shape, plus 20 more
for steady state:

| Stage | Process VmRSS | `docker stats` container total |
|---|---|---|
| Process started, no imports | 30.7MB | — |
| torch imported | 220.0MB | — |
| silero_vad imported (incl. onnxruntime) | 242.6MB | 505.6MiB |
| Silero model loaded | 250.9MB | 521.6MiB |
| After 1 inference | 274.7MB | 537MiB |
| After 20 more inferences (steady state) | 277.8MB | 538MiB |

Host `free -h`, desktop running normally throughout (not closed to
flatter the number):

- Before test: `used 1.9G / free 601M / available 1.7G` (swap 227M used)
- At peak (container ~538MiB): `used 2.1G / free 495-502M / available
  1.6G` (swap unchanged)
- After container removed: `used 1.9G / free 663M / available 1.7G`
  (swap 235M, negligible drift)

**Verdict: fits comfortably, does not get tight.** Peak container
footprint (~538MiB, mostly torch's own ~190MB import baseline) barely
dents the ~1.6-1.7GB available on this 3.9GB board — available memory
dropped only ~100MB at peak vs. baseline, swap didn't move. FastAPI/
uvicorn overhead on top is tens of MB, not hundreds; the full service
should sit comfortably under ~600-700MB resident, leaving well over 1GB
headroom alongside the existing desktop session.

## Open questions / next steps

1. **Torch/VAD dependency question: fully resolved.** Container install
   works, non-root device access works, memory footprint fits
   comfortably. The `silero-vad[onnx-cpu]` fix is committed. No remaining
   blocker on this thread; next is `RobotBackend` implementation design
   (using the daemon API map above) or, optionally, still evaluating
   `/state/doa`'s `speech_detected` as an even-lighter-weight alternative
   (not required now that the torch path is proven viable; would need
   the owner present since daemon start moves the robot by default).
2. **Install script validation:** not yet re-run end to end on a clean
   image; the PyGObject pin risk is unresolved.
3. Decide whether to leave `~/reachy-work-buddy` on the Nano as-is, wipe
   it, or hand off a specific next test.

No `RobotBackend` implementation, ADR changes beyond the topology
amendment already recorded, or launcher scripts were written as part of
this pass.
