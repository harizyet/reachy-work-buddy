# Phase 24f motion conformance (2026-09-25)

**Scope:** [item 1](../phase-24f.md#1-motion-conformance). This compares
the daemon's REST path with the SDK path the official Testbench uses, on
the deployed robot. The source reading behind it is in the
[source trace](phase-24f-source-2026-09-25.md). The targets and tolerances
below were committed before any physical measurement.

## Compatibility table

Read-only facts from the Nano, collected by the Nano-side session at about
09:25Z. Nothing was started, restarted or moved to collect them.

| Item | Value |
|---|---|
| Robot host | `reachy-mini`, Jetson Nano, L4T R32.7.1, kernel 4.9.253-tegra, aarch64 |
| Robot identity | daemon `hardware_id` `43c05f5047e8dcfe`, `robot_name` `reachy_mini`, camera specs `lite`, not wireless |
| Daemon | `reachy-mini` 1.8.4 (`pip show` in `reachy-venv`, Python 3.10; `/api/daemon/status` `version`) |
| Python SDK | Same 1.8.4 install as the daemon. The Testbench runs whatever SDK sits next to the daemon |
| Testbench | `480b0cc` ([source trace](phase-24f-source-2026-09-25.md#testbench-and-sdk-path-compared-with-rest)) |
| Kinematics | `AnalyticalKinematics`, collision check off (`/api/kinematics/info`) |
| Firmware | Not exposed. 1.8.4 has no version, firmware or motor-model endpoint (`/api/daemon/version` 404) |
| Recorded-move dataset | `pollen-robotics/reachy-mini-emotions-library`, as preloaded by the daemon. Revision not exposed over the API |
| Nano checkout | `422c18b`, 12 commits behind `origin/main` at the time of the check |
| Embodiment image | `sha256:4c36865684c5…`, created 2026-09-24 21:47 +07:00, no revision label |
| Daemon status | `running`, motor control `enabled`, control loop ≈49.5 Hz, `nb_error` 0 |

`backend_status.ready` reads `false` while the backend runs. In 1.8.4 the
robot backend builds its status with `ready=False` and never updates that
field (`daemon/backend/robot/backend.py`), so it is not a fault signal.

At rest after this boot's wake-up, `/api/state/full` reported head roll
0.034, pitch 0.028 and yaw 0.016 rad, translation ≤ 1.2 mm, antennas
`[-0.178, 0.178]` and body yaw 0.0015 rad. The wake-up target is identity
with antennas `[-0.1745, 0.1745]`. This static error sets the absolute
tolerance below. It is also much smaller than the 0.31–0.43 rad roll seen
in 24d.

`/api/state/full` returns the head as x/y/z in metres and roll/pitch/yaw in
radians (a matrix with `use_pose_matrix=true`), body yaw in radians and
antennas as two radians. The SDK documents the antenna order as
`[right, left]`.

## Method

The script is [`deploy/reachy/motion-conformance.py`](../../deploy/reachy/motion-conformance.py).
It runs with `reachy-venv/bin/python` on the Nano. Without `--run` it only
prints the plan. Each `--run CASE` is one bounded sequence, run with the
owner present and approving that case. `reachy-embodiment` is stopped first
so that only one controller drives the daemon. A case refuses to start
unless the daemon is `running` with no active move.

Targets: ZERO (identity head, antennas `[0, 0]`, body yaw 0); single-axis
roll ±0.1, pitch ±0.1, yaw ±0.15 rad from ZERO; antennas `[0.3, 0]` and
`[0, 0.3]`; body yaw 0.2 rad. Moves take 1 s, and the pose is read 0.8 s
after the move's nominal end. REST sends every field explicitly with fixed
keys.

Tolerances, fixed before measurement (rad and metres). Pollen publishes no
tolerance, so they are sized from the static error above:

| Check | Tolerance |
|---|---|
| Head orientation vs target, per axis | 0.05 |
| Head translation from 0 | 0.003 m |
| Antenna and body yaw vs target | 0.05 |
| REST vs SDK, same case | 0.02 |
| Single-axis delta from ZERO | same sign, within 30 % of target |
| Cross-axis change | 0.03 |
| Head yaw change after a stop (1.5 s) | 0.02 |

Telemetry limit: the pose is read about 0.8 s after the nominal end over
HTTP. That shows where the head came to rest, but not how well it tracked
along the way or how long it took to settle.

## Mockup-sim dry run (no robot)

All 14 cases ran against a local 1.8.4 `--mockup-sim --no-media` daemon on
port 18000. Mockup-sim has no motor dynamics, so this only checks the
script and the control flow. Every PASS/FAIL case passed. The recorded
cases matched the source trace:

- **Body yaw:** REST with body yaw omitted kept 0.2. The SDK default
  returned it to 0.0.
- **Interpolation:** yaw at 25 % and 50 % of a 2 s move was 0.035 / 0.073
  for SDK `linear`, 0.014 / 0.070 for SDK `minjerk` and 0.014 / 0.072 for
  REST `"linear"`. REST ignores the field and runs min-jerk.
- **Failure responses:** an unsupported interpolation gave 422, an unknown
  recorded move 404, and a stop of an unknown UUID 500, with no motion.

## Physical results

Pending: to be run with the owner present.
