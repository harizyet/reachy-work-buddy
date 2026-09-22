# Phase 22 inventory and compatibility report — 2026-09-22

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
  are **not** installed — matches the exact gap AGENTS.md's Dev setup
  section already documents install steps for; those should apply as-is.
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

## Open questions / next steps

1. **Torch/VAD blocker (unresolved):** decide between the deprioritized
   container route, deferring/reimplementing VAD without torch for the
   Nano deployment, or accepting torch-from-source as infeasible and
   ruling it out explicitly.
2. **`reachy-venv`/daemon reproducibility:** decide whether to capture the
   8-step manual sequence above as a real install script (and give the
   daemon a systemd unit) before relying on it as part of Phase 22's
   "repeatable deployment" deliverable.
3. **`reachy-mini-daemon` API surface:** not yet investigated — needed
   before implementing `RobotBackend`'s HTTP client, especially for the
   `capture_frame()` session-vs-stateless mismatch and daemon-side
   connection/sim status.
4. Decide whether to leave `~/reachy-work-buddy` on the Nano as-is, wipe
   it, or hand off a specific next test.

No code, ADRs, or launcher scripts were written or modified as part of
this inventory pass.
