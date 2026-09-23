# Phase 22a bring-up verification — 2026-09-22/23

Consolidated from the implementation handover. These are historical results,
not a claim that the machines are currently running. The owner split Phase
22 into completed bring-up (22a) and deferred physical acceptance (22b), with
Phase 23 proceeding first. The [acceptance plan](../phase-22-23.md) owns the
remaining pass criteria; the [deployment guide](../deployment.md) owns the
current startup procedure.

## Hardware and dependency evidence

The [inventory report](phase-22-inventory-2026-09-22.md) contains raw identity,
USB, dependency, device-permission, and memory evidence from the physical
Nano. It established original Jetson Nano, JetPack 4.6.1/L4T R32.7.1,
Ubuntu 18.04/glibc 2.27, about 3.9GB RAM, and directly attached Reachy
camera/audio/motor devices. There is no second onboard embodiment computer.

Native torch/onnxruntime wheel compatibility failed independently of Python
version. A newer-glibc CPU container resolved it. Non-root device access was
verified with numeric dialout/video/audio groups and a negative control;
`/dev/ttyACM0` was world-writable. Peak embodiment container memory was about
538MiB, with no additional swap pressure. The missing isolated onnxruntime
dependency was fixed with `silero-vad[onnx-cpu]`; 300 tests passed afterward.

The Python 3.10 daemon setup was captured in an installer/systemd unit from
working shell history. A clean-image install and the fragile PyGObject pin
remain unverified. The optional daemon `speech_detected` VAD alternative was
identified but not evaluated; the working container removed that blocker.

## Backend and connectivity

The real backend first passed 15 HTTP-transport tests plus two connection-
check tests (317 total), isolated package installation, image build/run,
honest unreachable-daemon status, and invalid-backend startup failure.
Those tests did not establish real movement or camera/audio correctness.

WS auth/registration/heartbeat/generation-fencing/reconnect then passed
unit checks (345 total) and a real two-container run over Docker networking:
valid registration/acks, wrong-token HTTP 403, hub stop, robot backoff, and
automatic reconnect to a replacement hub. This run used plain WS; TLS/Caddy,
real network changes, live credential revocation, outbound media, and WS
semantic commands were not exercised. Commands remain on the HTTP path.

Production Compose mode was verified with four services; simulation adds
embodiment and Mailpit. Re-running the homelab launcher created no duplicate
containers. Temporary homelab test resources were removed.

## Launcher and real Nano findings

Read-only launcher checks were run on the Nano, with post-check confirmation
that they started no daemon/container or motion. Several defects were fixed
and the final diagnostic report completed correctly on the old systemd:

- Argument parsing in a process-substitution subshell lost flag assignments;
  a plain call/global array fixed `--check` actually starting the stack.
- The daemon-start command originally preceded the `--check` guard. Review
  caught this before a live Nano run; start now occurs only after that guard.
- `systemctl list-unit-files` returned exit 0 for nonexistent units. Checking
  result rows fixed false “installed” reports.
- `timedatectl show` is unsupported on systemd 237. A failed unguarded shell
  assignment under `set -e` crashed diagnostics; guarded `status` parsing and
  an audit of other substitutions fixed it.
- Embodiment-host diagnostics were incorrectly hidden when the daemon unit
  was absent. Device/group/env reporting now runs for plausible robot hosts.
- Ignore patterns swallowed a new `.env.example`; explicit example-file
  exceptions restored tracking without exposing actual `.env` secrets.

On 2026-09-23 the owner started the real daemon: it woke/moved the robot and
reported both simulation flags false. Audio source/sink warnings were noted
but not resolved by that successful startup. A fresh pass against the real
OpenAPI and sockets found and fixed:

- All daemon routes mount under `/api`, omitted in the initial source-only
  inventory/backend assumptions. Backend and launcher URLs were corrected.
- The daemon owns port 8000; embodiment moved to default 8100.
- The daemon binds loopback only, unreachable through a bridge gateway.
  Owner-approved host networking made it reachable from embodiment.
- A personal `.env` retained the old bridge URL after the default changed;
  updating it to loopback was necessary for the fix to take effect.
- Engine 20.10.7 needed explicit BuildKit despite buildx being installed.
  A piped build initially hid failure until image existence was checked.

With those fixes, the real Nano container returned `connected:true,
sim:false`. Daemon and container were left running at the owner's request;
recheck current state before any next action. Some earlier handover paragraphs
still claimed no systemd installation/live start had happened; this later
observed startup supersedes them. It does not prove clean provisioning.

## Real daemon simulator movement

At the owner's request, named-move testing then used the real daemon's
built-in simulator on the homelab, **not the physical Nano**. A temporary
system-site-packages venv installed reachy-mini 1.11.0; daemon ran on 8200
with `--mockup-sim --headless --no-media` to avoid the live media plugin need.
The temporary venv is not a reproducible deployment artifact.

All 14 configured move names resolved in
`pollen-robotics/reachy-mini-emotions-library`. Eight exercised behaviours
(waiting, listening, thinking, greeting, sleep, wake, task_complete,
cannot_comply) produced real daemon HTTP 200s and running-move UUIDs that
appeared then drained. Unmapped idle_breathing/subtle_scan/antenna_twitch
logged and no-op'd without reaching the daemon. A recurring kinematics
warning did not produce a daemon status error.

This verifies dispatch, dataset loading, and lifecycle, not trajectory,
collision safety, timing quality, physical audio/video, or device passthrough.
Both temporary processes were stopped. A named behaviour command against
actual Nano motors, 8-hour desk use, 24-hour idle soak, physical speech,
outage/reconnect, and backup restore remain unaccepted under Phase 22b.
The daemon's startup wake movement is not that named-behaviour acceptance.
