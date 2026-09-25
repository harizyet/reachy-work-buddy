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
- **The head does follow the motors (camera-measured, below).** The owner
  saw no motion for an encoder-reported 16° yaw, but the head camera
  measured 0.223 rad against the encoders' 0.230. The owner's view was a
  perception limit for moves of 5–13°, not a mechanical decoupling. The
  shortfall itself is real and physical. 24d's `stewart_5` heat is still
  unexplained.
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
the Testbench send the same targets, and the head moves as far as the
encoders report. It stops 2–5° short of commanded poses on every path,
including Pollen's streaming method. Whether that is normal for the stock
proportional-only gains or excess friction or load on this unit is
**open**. The predeclared 0.05 rad tolerance was stricter than anything
Pollen checks, and was not based on a measured healthy robot. The
motion switches stay off. Repair is outside Phase 24f.

### Camera-measured run (unattended, 12:47Z)

This was the first run under the owner's unattended-testing decision, at
`7e94194`, with `--camera`: zero-rest, visible-rest, axes-rest, axes-sdk,
stream-sdk, then home. The daemon stayed `running` with `nb_error` 0, and
the journal had no warnings. The run ended at IDLE_HOME.

- **Encoders:** the same as earlier runs. `stream-sdk`, which is Pollen's
  conversation-app method (60 Hz `set_target`), reached 0.074 for +0.15,
  0.061 on the return to 0, and −0.049 for −0.15. It does not avoid the
  shortfall.
- **Camera, live:** unusable. The Lite head camera is dark by default even
  in a lit room (mean 33/255, 29 ORB keypoints raw). Most rows had no
  matches, and the few that solved were spurious (0.3–1.0 rad).
- **Camera, offline re-analysis** (read-only, at `65034fd`, with CLAHE
  equalisation; 452 keypoints on the baseline): wherever the frame was
  fresh, the camera and encoders agreed within about 0.01 rad. Examples:
  visible yaw +0.3, 0.223 / 0.230, and its return, −0.115 / −0.115;
  yaw +0.15, 0.094 / 0.092; stream +0.15, 0.143 / 0.136; SDK yaw −0.15,
  −0.137 / −0.144. The disagreeing rows lag by one observation. The
  "after" frame still showed the previous position, and the pair sums to
  the encoder value, for example roll −0.1: −0.018 then −0.121, against
  −0.132.

Script changes from this: frames are CLAHE-equalised. The script refuses
to start below 400 baseline keypoints, drains 0.6 s of frames before
measuring, and marks a move invalid below 35 inliers or an inlier ratio
of 0.3. The ratio gate is set from the agreeing rows above (0.36–0.5).
The owner may want the Lite camera's exposure raised; Pollen's
troubleshooting suggests auto-exposure priority. That is a host camera
setting and has not been changed.

### Camera-measured run 2 (unattended, 12:57Z)

At `955d01c`, all bounded cases except the two recorded-animation ones.
The daemon stayed `running` with `nb_error` 0, the journal was clean, and
the run ended at IDLE_HOME.

| Case | Result |
|---|---|
| zero-rest | PASS; camera PASS |
| axes-sdk, stream-sdk | Encoders FAIL with the usual shortfall. Camera PASS: every valid row within 0.02 rad of the encoders |
| axes-rest | Encoders FAIL, the same poses as axes-sdk. Camera FAIL: every disagreeing move/return pair has opposite-sign differences that cancel, the stale-frame signature. The 0.6 s drain was not always enough; see below |
| visible-rest | +0.3 → 0.221, return → 0.102. The +0.3 camera row was invalid (30/79 inliers) |
| antennas-rest, antennas-sdk | PASS, the same on both paths: `[0.3, 0]` → `[0.299, 0.0]`, `[0, 0.3]` → `[±0.005, 0.299]`. The first element is the one that moved for `[0.3, 0]`; the SDK documents it as the right antenna. That physical side has not been checked |
| bodyyaw-rest, bodyyaw-sdk | Confirms the source trace physically. Explicit 0.2 → 0.199 on both paths. A REST head goto with body yaw omitted then **kept** 0.199, while an SDK goto with its default returned it to 0.006 |
| cancel-rest | PASS: stop 200, no running move, and the pose held within 0.002 rad for 1.6 s. The shortfall meant little progress had been made by the 1 s stop, so this shows the hold, not partial travel |
| interp | Inconclusive: each variant started where the last ended, and the 25 %/50 % samples fell inside the shortfall |

The LOCAL reader keeps only the newest frame (`appsink` `max-buffers` 1,
`drop`), so a stale frame means the camera pipeline itself runs behind on
the Nano. `grab_frame` now waits until the image stops changing (two
consecutive 0.3 s steps with a mean difference under 2/255 on a blurred
1/8-size frame, up to 6 s), and marks the move invalid if it never does.
In a synthetic check with three lagging reads, including one mid-motion
frame, it measured 0.1505 for a 0.15 move. `interp` now starts every
variant at yaw −0.2, moves to +0.2 over 2 s, and reports the fraction of
travel at 25/50/75 %. On mockup-sim: SDK linear 0.23/0.48/0.74, min-jerk
0.09/0.47/0.89, REST "linear" 0.09/0.47/0.88 (min-jerk, as the source
says).

### Camera-measured run 3 (unattended, 13:07Z)

At `7d9dc67`. A first attempt at 13:04Z refused before any motion: the
scene had 256 keypoints after equalisation (under the 400 minimum). The
owner then placed a textured target, raising it to 1436. The daemon
stayed `running` with `nb_error` 0, the journal was clean, and the run
ended at IDLE_HOME. No move was invalid and the stillness wait never
timed out. The daemon's media pipeline reports a latency of 36.7 ms
minimum and 1.064 s maximum at startup. That maximum is why a fixed
0.6 s wait could still return a stale frame.

| Case | Encoders | Camera |
|---|---|---|
| visible-rest | +0.3 → 0.233, return → 0.093 | PASS |
| visible-sdk | +0.3 → 0.248, return → 0.105 | PASS |
| axes-rest | Usual shortfall and coupling | 2 of 13 rows over 0.02: pitch −0.1 (camera −0.165, encoders −0.097) and yaw −0.15 (−0.087 vs −0.110). Their neighbouring rows agree, so this is not the stale-frame pattern. The camera sits about 5 cm from the rotation centre, and a target placed near the head breaks the distant-scene assumption, so these two are attributed to parallax, not to motion |
| interp | Travel fraction at 25/50/75 %: SDK linear 0.12/0.30/0.54, SDK min-jerk 0.01/0.29/0.84, REST "linear" 0.01/0.29/0.81 | PASS |

Interpolation is now shown physically: REST ignores `"linear"` and moves
with the min-jerk profile. Each profile keeps its shape but trails its
ideal by about 0.2 of travel at 50 %, roughly 0.4 s on a 2 s move,
consistent with the proportional-only tracking lag. The start was about
−0.11 rather than −0.2 for the same reason.

### Item 1 outcome

| Row | Result |
|---|---|
| Identity head / zero antennas | ZERO reached within tolerance on both paths |
| Roll, pitch, yaw | Signs correct on both paths, which agree within about 0.005 rad. Shortfall 2–5° when a joint's angle must grow. The camera confirms the head moves as the encoders report |
| Antennas | Order `[right, left]` per the SDK, identical on both paths, on target. Physical side unchecked |
| Body yaw | REST omitted value keeps the current yaw; the SDK default returns to 0. Explicit values match |
| Duration / interpolation | REST always min-jerk; the SDK honours linear. Both lag their ideal by about 0.4 s at mid-travel |
| Cancellation | Stop by UUID works; the pose holds within 0.002 rad |
| Recorded moves | Run with the owner watching (13:14Z, "it played normally"). `attentive1` took 6.28 s and **ends at its own final pose** (pitch −0.28 rad, left antenna 0.81), not back at the start. `thoughtful1` stopped by UUID at 1.5 s: stop 200, no running move; one settle step of about 0.04 rad in the first 0.28 s, then held within 0.003 rad for 1.3 s. IDLE_HOME afterwards reached as usual |
| Failure | 422 bad interpolation, 404 unknown move, 500 stop of an unknown UUID; no motion |

Consequence for item 3: after a recorded gesture the head stays wherever
the gesture ended. In 1.8.4 the next recorded move starts from its own
first frame with no blend (`initial_goto_duration=0`, source trace). So
conversational gestures need a bounded return toward IDLE_HOME between
them, or the next one may start with a jump. The motion controller
currently returns home only at a normal session end. This must be
settled before `CONVERSATION_MOTION_ENABLED` is tried.

The command paths conform. The one open physical question is the
direction-dependent 2–5° shortfall. It appears on every path, including
Pollen's streaming method, and the stock proportional-only gains predict
it. Whether this unit has extra friction or load is a hardware question
outside 24f. Until the owner accepts it or it is fixed, pose-dependent
motion should not assume better than about 0.08 rad accuracy.

### SDK media side effect

In 1.8.4, `ReachyMini(media_backend="no_media")` calls `release_media()` on
connect. This releases the daemon's camera and audio for every client, and
the media is not restored on disconnect. After the first SDK case the
camera socket was gone. `reachy-embodiment`'s start then waited in
`wait-media-socket.sh` until `POST /api/media/acquire` restored it, which
was done with the owner's OK and involved no motion. `17a8ef9` reacquires
media after every SDK case. Nothing that shares the daemon with the
embodiment's camera or voice should use a `no_media` SDK client.
