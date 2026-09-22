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

## Open questions / next steps

1. **Dependency compat:** test whether a newer-glibc Docker base (Ubuntu
   22.04+) run on this Nano's kernel allows `uv sync` to succeed for
   CPU-only wheels, now that Docker itself is present (compose/buildx
   still need installing per AGENTS.md's Dev setup section). If that
   fails too, the fallback is deciding whether `reachy-embodiment`
   specifically should target the pre-existing `~/reachy-venv` (Python
   3.10, already has the real `reachy_mini` SDK working) instead of this
   repo's `uv`-managed 3.13 environment for the Nano deployment
   specifically — a real architectural choice, not something to decide
   unilaterally mid-inventory.
2. **ADR 0004 amendment:** resolve whether the Nano being the sole
   robot-attached machine is accepted (revising the outage-survivability
   guarantee) or whether an independent local-fallback runtime needs to
   exist elsewhere before Phase 22 can proceed on the "real hardware
   adapter" deliverable.
3. Decide whether to leave `~/reachy-work-buddy` on the Nano as-is, wipe
   it, or hand off a specific next test (e.g. the container/newer-glibc
   route above).

No code, ADRs, or launcher scripts were written or modified as part of
this inventory pass.
