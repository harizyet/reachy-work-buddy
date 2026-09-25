# Phase 24f motion source trace (2026-09-25)

**Scope:** source reading of the pinned `reachy-mini==1.8.4` (from `uv.lock`,
installed in the workspace `.venv`) and one probe against that daemon in
`--mockup-sim --no-media` mode on `127.0.0.1:18000`. No robot, Nano, MuJoCo
or physical motion was involved. Mockup-sim has no motor dynamics, so these
results cover control flow only, not tracking, heat or settling.

Still open for [item 1](../phase-24f.md#1-motion-conformance): the version
deployed on the Nano, firmware and the dataset revisions. The Nano was
offline when this was checked on 2026-09-25 (no LAN route; Tailscale last
seen 6 h earlier). The Testbench is pinned below. The source line numbers
below refer to 1.8.4 only.

## Findings

| Question | 1.8.4 behaviour | Evidence |
|---|---|---|
| Can two REST moves run at once? | **Yes.** `play_move` guards with a `threading.RLock` acquired non-blocking, but every REST move task runs on the daemon's single event-loop thread, so the re-entrant lock always succeeds. Both loops write targets at 100 Hz. | Probe: `goto` yaw +0.3 then, 0.5 s later, yaw −0.3 (both 2 s). `/move/running` showed 2; measured yaw alternated 0.23 / −0.16 / 0.30 until the first ended. Both reported `move_completed`. |
| Is `move_completed` proof the move played? | No. Overlapping moves both "complete". A move rejected by the lock (another thread owns it) logs a warning and returns normally, which also reports `move_completed`. | `daemon/backend/abstract.py` `play_move`; `routers/move.py` `create_move_task` |
| Real cancellation | `POST /api/move/stop` with the move's `{"uuid": ...}` cancels the asyncio task. The head holds the last target; it does not return. Events: `move_started` / `move_completed` / `move_failed` / `move_cancelled` on `WS /api/move/ws/updates`. | Probe: stop at 1 s of a 3 s move gave `move_cancelled`; yaw −0.160 then −0.153 1 s later (mockup converging to the last target) |
| Does `/goto` honour `interpolation`? | **No.** The field is accepted but not passed to `backend.goto_target`, so REST gotos are always min-jerk. | `routers/move.py` `goto` |
| Omitted `body_yaw` | REST passes `None`, and the body keeps its current yaw. Backend callers that omit it get the default `0.0`. | `goto` route vs `goto_target` signature |
| Recorded-move start | `play_recorded_move_dataset` calls `play_move(move)` with `initial_goto_duration=0`, so playback starts from the move's first frame with no blend from the current pose. | `routers/move.py` |
| Wake-up completion signal | At startup the daemon awaits `backend.wake_up()` before setting `state: running`, so `running` means the boot wake-up is finished (or was skipped). | `daemon/daemon.py` start sequence |
| Wake-up end pose | Identity head, antennas `(-0.1745, 0.1745)` rad (±10°, "to reduce shaking at vertical"), body yaw `0.0`. This is the proposed `IDLE_HOME`. | `INIT_HEAD_POSE`, `INIT_ANTENNAS_JOINT_POSITIONS`, `wake_up` |

## Testbench and SDK path compared with REST

Testbench revision `480b0cc0252d60f3bc2231131823a4ad7a07bf8c` (Hugging Face
Space `pollen-robotics/reachy_mini_testbench`, 2026-03-19). Its
`pyproject.toml` depends on unpinned `reachy-mini`, so it runs whatever SDK
is installed next to the daemon. The comparison below assumes 1.8.4 on both
sides and is source reading only.

The Testbench moves the robot through the Python SDK (`ReachyMini(...)`,
`connection_mode="localhost_only"`), not through REST. The SDK sends a
`GotoTaskRequest` over the daemon's WebSocket, and `io/ws_server.py` calls
the same `backend.goto_target` → `play_move` that REST `/api/move/goto`
calls. Head poses, rotation order and units therefore reach the same
backend function. The differences are in the entry points:

| Aspect | SDK / Testbench | REST `/api/move/goto` |
|---|---|---|
| Pose encoding | 4×4 matrix, flattened; `create_head_pose` uses scipy `"xyz"` Euler, **degrees** by default | `Matrix4x4Pose` `{"m": [16]}` or `XYZRPYPose` with scipy `"xyz"` Euler in **radians**, metres |
| Interpolation | `method` is passed through | Accepted and ignored: always min-jerk |
| Omitted body yaw | Default `0.0`: an explicit return to yaw 0 | Default `None`: keeps the current yaw |
| Tracking and cancellation | Not in the REST move registry: absent from `/api/move/running`, not stoppable by `/api/move/stop` | Registered; stoppable by UUID |
| Overlap | Runs as its own task on the daemon event loop, so it can overlap a REST move just as two REST moves overlap | Same |
| Automatic body yaw | `ReachyMini()` sends `set_automatic_body_yaw(True)` on connect; the daemon's default `AnalyticalKinematics` already starts at `True`, so no change in practice | Not touched |

The Testbench's "zero" is identity head with antennas `[0, 0]` and body yaw
0 (SDK default). That is our proposed `ZERO`, not the wake-up end pose
(`IDLE_HOME`, antennas ±0.1745 rad). A Testbench zero followed by the
embodiment's first recorded move is a different start pose from a fresh
wake-up.

Two consequences for the comparison runs. The Testbench and the embodiment
must not both be connected to the daemon while measuring, because nothing
arbitrates between them. A REST body-yaw case must send `body_yaw`
explicitly, or it will not match the SDK case.

**REST payload check (in process, no daemon):** `GotoModelRequest` resolves
`{"m": [...]}` to `Matrix4x4Pose` and `{"roll": ...}` to `XYZRPYPose`
(pydantic 2.13.5). A misspelled key such as `{"rol": 0.1}` also validates,
as `XYZRPYPose` with every field 0, so a typo sends the head to identity
without any error. Any client code we add for `/goto` must build the payload
from fixed keys and be tested against the model.

## Speech wobble in 1.8.4

1.8.4 has daemon-side, audio-reactive head motion. `POST
/api/media/wobbling/enable` and `/disable` switch it (the SDK uses a
`SetWobblingCmd` for the same thing). `play_sound`, the path our
`play_audio` uses after `/media/sounds/upload`, builds its audio sink with a
tee into a 16 kHz wobbler appsink. It restarts the wobbler at each play, and
offsets are composed with the current target before IK. The deployed daemon
runs with media enabled (`reachy-mini-daemon.service` has no `--no-media`),
so the path exists there, provided the Nano runs 1.8.4. Amplitudes from
`motion/speech_tapper.py`: pitch 4.5°, yaw 7.5°, roll 2.25°, x/y/z ≤ 4.5 mm,
scaled by loudness (`SWAY_MASTER` 1.5). Hops are 50 ms.

Gaps found in the source:

- `stop_sound` stops the playbin but does not reset the wobbler. Hops
  already scheduled against playback time still fire, and the last offset
  stays applied until the next `play_sound` or a disable. A stop path using
  wobble would have to call `/media/wobbling/disable`, which zeroes the
  offsets, and then enable it again.
- The feature is off until enabled, and the setting belongs to the daemon,
  not to a client. Enabling it also makes the daemon's own sounds (wake-up,
  sleep) wobble. `goto_sleep` disables it itself.
- Not run: mockup-sim was started with `--no-media`, so no wobble probe was
  possible. Physical behaviour, motor noise during capture, and interaction
  with recorded moves are untested.

This makes wobble the first candidate for speaking feedback under
[item 3](../phase-24f.md#3-local-conversational-motion-policy), subject to
a supervised check. It is not enabled anywhere.

## Where our code can overlap moves

- The embodiment's `play_behaviour` POSTs a recorded move and discards the
  returned UUID. It never checks `/move/running` and cannot stop the move.
- Idle presence sends nothing to the real daemon: `IDLE_BREATHING`,
  `SUBTLE_SCAN` and `ANTENNA_TWITCH` are unmapped, so they no-op.
- The hub's WebRTC call path (`reachy_hub/webrtc.py`) sends LISTENING →
  THINKING → SPEAKING → WAITING in quick succession. The mapped moves are
  `attentive1` (≈4.3 s), `thoughtful1` (≈5.9 s) and `waiting` (≈10.0 s),
  with durations measured from the locally cached dataset JSON. THINKING
  starts once STT finishes, which for a short utterance is typically before
  `attentive1` ends. The next turn's LISTENING can land inside `waiting`.
- Explicit `/behaviour/{name}` requests and hub gesture alerts can also
  overlap each other or any of the above.

**Hypothesis, not established:** overlapping recorded moves send
conflicting targets at 100 Hz. This could explain the 24d `stewart_5` heat,
lag and drift that the Testbench, which runs one move at a time, did not
reproduce. It is untested on hardware, and whether 24d's sessions used the
WebRTC path is not recorded here.

## Preemption fix check

`ReachyDaemonBackend` now stops its previous move before starting the next
([ADR 0003 amendment](../adr/0003-embodiment-command-api.md#phase-24f-move-preemption-amendment-2026-09-25)).
Checked against the same 1.8.4 mockup-sim daemon, with `HF_HUB_OFFLINE=1`
and the cached emotions dataset. LISTENING was played, then THINKING 1 s
later, through the real backend class:
`attentive1` `move_started` 0.22 s, `move_cancelled` 1.22 s;
`thoughtful1` `move_started` 1.31 s; `/move/running` stayed at 1; `close()`
then cancelled `thoughtful1`. Mock-transport unit tests cover the stop
ordering, stop-after-finish (500), failed plays, standby and close. This is
not a physical check: whether the fix removes the 24d tracking anomalies is
untested.

## Probe

`.venv/bin/reachy-mini-daemon --mockup-sim --no-media --no-wake-up-on-start
--headless --fastapi-host 127.0.0.1 --fastapi-port 18000`. Then a short
httpx/websockets script sent the two overlapping gotos, sampled
`/api/state/present_head_pose` and `/api/move/running` every 0.25 s, and
stopped a third goto by UUID. The daemon was then stopped. Port 8000 was
avoided because an unrelated local service uses it.
