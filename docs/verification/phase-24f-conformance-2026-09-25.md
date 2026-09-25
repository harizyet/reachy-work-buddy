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

Run on the Nano by the Nano-side session, with the owner at the robot and
approving each case. `reachy-embodiment` was stopped first, and the daemon
was left running. The first round started 09:34:19Z at `e8ee988`. The
second round used `17a8ef9`, which added joint telemetry, late reads and
media reacquisition. `nb_error` stayed 0 throughout. The daemon journal
showed no IK, overheat or warning lines. Its only traceback is the expected
`KeyError` behind `failure-rest`'s HTTP 500.

| Case | Result | Evidence |
|---|---|---|
| failure-rest | PASS | 422 bad interpolation, 404 unknown move, 500 unknown stop UUID; head moved 0.0001 rad; no running move |
| home | Recorded | roll 0.033, pitch 0.034, yaw 0.011; antennas `[-0.178, 0.175]`. Owner: "seems fine" |
| zero-rest | PASS | roll 0.032, pitch 0.039, yaw 0.010; antennas `[-0.002, 0.0]`. Owner saw no change |
| zero-sdk | PASS | roll 0.034, pitch 0.046, yaw 0.006. Already at ZERO |
| axes-rest (first run) | **FAIL** | Signs correct. Reached roll +0.096 / −0.050, pitch +0.092 / −0.039, yaw +0.080 / −0.059 of ±0.1 / ±0.1 / ±0.15. Cross-axis changes up to 0.067 |
| axes-sdk | **FAIL**, same as REST | Same targets over the SDK: roll +0.075 / −0.053, pitch +0.093 / −0.039, yaw +0.080 / −0.060 |
| axes-rest (second run) | **FAIL** | Within about 0.005 rad of axes-sdk at every row. Returns to ZERO barely moved: yaw stayed 0.078 after +0.15 and −0.059 after −0.15, pitch 0.061 after +0.1. Late reads 2 s later were identical |
| visible-rest | **FAIL** | Yaw −0.063 → +0.223 for a +0.3 target, then +0.114 after returning to 0. Owner watched from the front: "It looked like it didn't move but I hear the motors move" |
| Raw logs | Kept on the Nano | `~/24f-logs/*.jsonl` (both rounds); the values above are copied from them |
| visible-sdk, antennas, body yaw, interp, cancel, recorded, preempt | Not run | Stopped after visible-rest |

The owner saw no head motion in any case. Earlier they said "the movements
are so small it's not really visually noticable".

### Analysis

- **REST and SDK agree.** Both paths gave the same result to about
  0.005 rad in every axis case, so the REST path matches the Testbench's
  SDK path at the command level. This is the question item 1 asked. The
  interpolation, omitted body yaw and cancellation differences are already
  settled from source and mockup-sim.
- **The readback is self-consistent.** After the first axes-rest, the
  encoder joints were `[0.002, 0.571, -0.623, 0.597, -0.627, 0.575,
  -0.598]`. The daemon's own 1.8.4 IK commands 0 and ±0.6265 for identity.
  The shortfalls were stewart_1 −0.056, stewart_3 −0.030, stewart_5 −0.052
  and stewart_6 +0.029. FK of these joints (computed offline with the same
  engine) gives yaw −0.0565, as reported. So the pose readback reflects
  the encoders: several motors stop about 3° short of their goals, from
  either direction, and do not creep closer over 2 s.
- **The shortfall depends on direction, on every motor.** The second
  round logged encoder joints next to the daemon's IK targets. In every
  checked move, a joint whose angle had to grow in magnitude stopped short.
  The mean shortfall per move was 0.035–0.069 rad. A joint whose angle had
  to shrink landed within 0.008 rad. Examples: in the yaw +0.3 move,
  stewart 1/3/5 had to grow and fell 0.043 / 0.029 / 0.062 short, while
  2/4/6 landed within 0.003. On the way back to zero the roles swapped:
  2/4/6 fell 0.064 / 0.062 / 0.080 short and 1/3/5 landed within 0.010.
  Roll and pitch show the same split. All six motors behave the same way,
  so this is a one-directional limit (load, friction, torque or supply),
  not one failed motor. Which physical direction "growing" is has not been
  checked.
- **The stock controller predicts a shortfall like this.** 1.8.4's
  `hardware_config.yaml` runs every stewart motor in position mode with
  PID `300, 0, 0`: proportional only, no integral term. Under a steady
  load such as the head's weight, a proportional-only loop settles where
  the load balances P × error, so it stops short in the direction that
  lifts the load. It doesn't creep, and the approach direction matters.
  That matches the direction-dependent shortfall above. How large the
  error is on a healthy Reachy Mini has not been measured here.
- **The Testbench would not have caught this.** The pinned Testbench
  (`480b0cc`) warns on motor positions only beyond 5° and errors beyond
  15°. Its rotation test rolls the head by a large angle (90° requested;
  the SDK clamps roll to ±40°), measures the real rotation from camera
  images before and after, and passes if the error is under 15°. The
  largest joint shortfall here, 0.08 rad (4.6°), passes both checks. So
  the owner's earlier successful Testbench run, on an earlier day, fits
  these numbers.
- **Still unexplained.** The owner saw no head motion for an
  encoder-reported 16° yaw, while hearing the motors. A mechanical fault
  (horn slip, a slack rod or ball joint, a loose head shell) or an
  insufficient supply are still possible, and 24d's `stewart_5` heat is
  still unexplained. Neither has been inspected or measured. The
  Testbench's camera-based rotation test measures actual head motion,
  independently of the encoders, so it can separate these possibilities.
- **The command method matches Pollen's.** No raw motor values were sent:
  both paths sent Cartesian head poses to the daemon's IK, as the
  Testbench does (`goto_target`). Pollen's conversation app
  (`reachy_mini_conversation_app` `b9f58a3`, which requires
  `reachy-mini>=1.10`) streams `set_target` at 60–100 Hz from one loop and
  uses `goto_target` only to reset to neutral. Between 1.8.4 and 1.11.0,
  nothing changed in the motor control, kinematics, gains or
  motor-controller dependency, so upgrading would not change this path.
  The `stream-sdk` case reproduces the app's method.

Result: item 1's command-path question is answered. REST, the SDK and
the Testbench send the same targets. Whether the physical shortfall is
normal for this robot or a fault is **open**. The predeclared 0.05 rad
tolerance was stricter than anything Pollen checks, and was not based
on a measured healthy robot. Next, with the owner present:

1. Run the official Testbench rotation test (camera-measured), with
   `motion-conformance.py --log 60` recording encoders alongside.
2. Run `stream-sdk`, which uses the conversation app's streaming method,
   for comparison with `axes-*`.
3. Inspect the mechanism and supply if the camera measurement disagrees
   with the encoders.

The motion switches stay off until then. Repair is outside Phase 24f.

### SDK media side effect

In 1.8.4, `ReachyMini(media_backend="no_media")` calls `release_media()` on
connect. This releases the daemon's camera and audio for every client, and
the media is not restored on disconnect. After the first SDK case the
camera socket was gone. `reachy-embodiment`'s start then waited in
`wait-media-socket.sh` until `POST /api/media/acquire` restored it, which
was done with the owner's OK and involved no motion. `17a8ef9` reacquires
media after every SDK case. Nothing that shares the daemon with the
embodiment's camera or voice should use a `no_media` SDK client.
