# Phase 22b first physical acceptance session — 2026-09-23

Owner-supervised session, coordinated across two Claude Code sessions (one
on the homelab box, one on the Nano) plus the owner physically present at
the robot throughout. Scope: bring up the ADR 0019 WSS connection for real,
then attempt the first-ever command to real Reachy Mini motors. Stopped
after finding a head-motion hardware fault; owner inspection follows this
record, not included in it. This is a BLOCKED partial run against the
[acceptance matrix](../phase-22-23.md#satisfactory-run-acceptance-matrix),
not a completed physical acceptance pass.

## Code fix: WS scheme derivation (blocking bug, fixed and merged)

`RobotWSClient` passed the configured `HUB_WS_URL` straight to
`websockets.connect` without ever deriving `ws://`/`wss://` from a
`http://`/`https://` value, despite ADR 0019 and `deploy/reachy/.env.example`
documenting that derivation. Every real (non-`ws://`-literal) `HUB_WS_URL`
failed with "scheme isn't ws or wss". Found live on the Nano. Fixed in
`services/reachy-embodiment/src/reachy_embodiment/robot_ws_client.py`
(commit `5443a93`), with unit test coverage added; full `services` + `shared`
suite (371 passed/14 skipped) and Ruff pass on the homelab tree.

## Outbound WSS connectivity — PASS (first real registration)

With the scheme fix, a correct `nano-1` token in homelab's `ROBOT_TOKENS`,
and `HUB_WS_URL=http://hariz-venus-series.tailc70e8d.ts.net:8080/hub`
(Tailscale MagicDNS), the Nano's embodiment container registered over WSS
through Caddy for the first time. Hub logs: `WebSocket /robots/connect
[accepted]` then `connection open`, stable with no further 403s or
disconnects. The connection self-recovered once (local port changed
33046→33642) without owner intervention.

Wrong-token rejection was incidentally exercised live: a mistranscribed
47-character token (should have been 64 hex characters) was rejected with
HTTP 403 on every retry attempt before the correct token was supplied,
after which registration succeeded with no other change. Counts as evidence
for that acceptance-matrix sub-case; a separate revoked-token-after-valid
test still remains open.

`GET /robots` (the old HTTP registry) stayed empty until `start-jetson.sh`'s
step 3 ran `POST /robots` with `ROBOT_HTTP_BASE_URL=http://100.113.42.25:8100`
(the Nano's stable Tailscale IP); it then returned
`{"robot_id":"nano-1","base_url":"http://100.113.42.25:8100"}`. This is a
separate registry from the WS connection manager and does not by itself
prove WS registration — both were independently confirmed.

Not exercised this session: real TLS (Caddy still has none — see
`deploy/homelab/Caddyfile`), a genuine network-change/hub-restart reconnect
drill, or revoked-token-after-valid rejection.

## Daemon bring-up — PASS (real, non-simulated)

`reachy-mini-daemon` 1.8.4, `--headless`, `sim=False`, `mockup_sim=False`,
`kinematics_engine=AnalyticalKinematics`, `wake_up_on_start=True`. First run
PID 12441 started cleanly (`Daemon started successfully`, 19:52:39 WIB); the
owner was not watching that exact moment but confirmed afterward, from a
later restart, that the wake-up routine does perform a nod and the head
then settles tilted rather than at neutral. `/api/daemon/status`:
`state=running`, `simulation_enabled=false`,
control loop ~49.3 Hz, `nb_error=0`. `backend_status.ready` stayed `false`
and `last_alive` stayed `null` throughout both runs, cause not investigated.

Audio is broken independently of motion: `Could not open audio device for
recording: 'reachymini_audio_src': No such file or directory` and `playbin
failed to activate sinks`, logged at both daemon starts. Possibly a device
contention with the embodiment container, which also holds `/dev/snd`. Not
investigated this session — blocks the voice/audio acceptance rows
regardless of the head issue below.

## First real-motor command — BLOCKED: head does not track commanded pose

Baseline pose before any command (daemon, 19:54:46 WIB): roll 14.6°,
pitch 5.4°, yaw -3.4°, x -9.6mm, y 5.2mm, z -3.7mm, antennas -10.5°/+10.1°.

`POST /behaviour/acknowledgement` (embodiment → daemon
`recorded-move-dataset/.../yes1`) returned 200, but the daemon logged an IK
warning during the move (`Collision detected or head pose not achievable!`,
19:55:27) and the head settled **further from neutral** than its start
(roll 20.6°, yaw -13.2°, z 12.0mm) rather than completing a nod and
returning to rest. Antennas moved further too (-13.4°/+24.3°) as an
apparent side effect, not the intended gesture.

The owner then power-cycled the robot without stopping the daemon process,
which put the daemon into `state=error` (`Motor communication error!` on
every motor, 19:56:33) — an expected consequence of losing the serial
connection mid-session, not a new finding. The owner restarted the daemon
(`sudo systemctl restart reachy-mini-daemon`, new PID 13943) and it came up
running/non-simulated again, but the owner reported the head visibly
tilted at rest.

Targeted diagnostic, owner watching and approving directly: `POST
/api/move/goto` with head pose and antennas both commanded to zero,
duration 3.0s.
- Antennas tracked smoothly to target: -10.2°/+10.4° → -0.6°/0.0°.
- Head barely moved despite a 3-second window: roll 14.2°→12.8° (target
  0°, only ~1.4° of ~14° covered), pitch 6.9°→6.1°, yaw -6.8°→-5.8°
  (target 0°, only ~1° of ~6.8° covered). No IK warning this time.

**Conclusion: antenna motors and the daemon→embodiment→hub command chain
work correctly on real hardware. The head (Stewart platform, motors
`stewart_1`–`stewart_6`) does not reach commanded poses** — consistent with
a mechanical obstruction, a stalled/under-torque head motor, or a
head-specific power/calibration fault. This reads as hardware, not the
`ReachyDaemonBackend`/embodiment software path, which dispatched every
command correctly and reported daemon responses accurately.

**Follow-up diagnostic (owner-approved daemon restart, read-only otherwise):**
`GET /api/state/full?with_head_joints=true&with_target_head_joints=true`
returned present joint angles but a null target (the backend holds no
target once wake-up completes), so the neutral target was computed offline
with the daemon's own `AnalyticalKinematics` engine (pure computation, no
robot I/O) against `INIT_HEAD_POSE`. Present vs. neutral-target per joint:

| joint | present | target | diff |
|---|---|---|---|
| body_yaw | -0.09° | 0.00° | -0.09° |
| stewart_1 | 40.17° | 35.90° | +4.27° |
| stewart_2 | -34.89° | -35.90° | +1.01° |
| stewart_3 | 32.52° | 35.90° | -3.38° |
| stewart_4 | -36.47° | -35.90° | -0.58° |
| **stewart_5** | **19.34°** | **35.90°** | **-16.56°** |
| stewart_6 | -30.41° | -35.90° | +5.49° |

Forward-kinematics check (same offline engine): setting only `stewart_5` to
its present value while holding the other five at neutral reproduces
roll 7.8°/pitch 6.6°/yaw -9.1° — most of the actually observed tilt. Any
other single motor set the same way gives at most ~2.6° on any axis.
**`stewart_5` (motor id 15) is the primary fault**; the other motors' 1-5°
errors are consistent with being dragged off-target by the constrained
Stewart platform rather than independent faults. Candidate causes (not
confirmed): obstructed/binding/disconnected linkage, a weak or
current-limited motor, or a wrong homing offset for id 15 (though the
daemon's own config check reported homing offsets as correct). Owner
physical check suggested: with the daemon stopped, inspect motor 5's arm
and rod (5th of 6 around the base) for free movement and both ball-joint
connections, comparing its resting angle by eye against `stewart_3`.

**Owner manual adjustment and retest:** the owner manually adjusted the head
toward upright (details of what was touched not yet captured), then the
daemon was restarted (PID 15314) and settled near neutral (roll -1.2°,
pitch 2.6°, yaw 1.7°) — visually much improved, and `stewart_5`'s error
against the ±35.90° IK target dropped from -16.56° to -6.19°, but
`stewart_2` worsened to +8.04° (was +1.01°), i.e. errors partly cancelling
in the visible pose rather than a real fix. The Nano session correctly
declined to save this position as a calibration/homing offset, since it
isn't a true zero.

A second owner-approved `goto` to all-zero (head pose 0, antennas 0, 3s,
20:12:24 WIB) showed **`stewart_1`, `3`, `6` track normally; `stewart_2`,
`4`, `5` do not respond to the position command at all** — `stewart_4`
held exactly -33.05° through every sample, `stewart_2` drifted only 0.5°,
and `stewart_5` moved 2.6° in the wrong direction (likely dragged by the
three working motors). No IK/collision warning this time. This is broader
than the single-motor (`stewart_5`) hypothesis from the first diagnostic —
three motors sharing a fault points more toward a shared cause (a power or
communication-bus segment, thermal/current protection possibly following
the earlier motor-communication-error event during the uncontrolled power
cycle, or a shared mechanical binding) than three independent motor
failures. The daemon does not expose per-motor hardware error/LED state
over its HTTP API as far as checked; `Failed to read hardware errors` was
only logged during the power-cycle motor-communication error, which isn't
informative about this state. **Recommendation: stop remote motion
diagnostics here — this needs hands-on inspection of motors 2, 4, and 5's
wiring/linkages and any accessible error/status indicators**, beyond what
HTTP-level commands can resolve.

Separately noted, not yet investigated: embodiment's `/behaviour/*` HTTP
response reported `"sim":true,"connected":false` for this command even
though the real daemon actually executed it (`sim=false` confirmed
independently via `/api/daemon/status`) — a likely status-reporting bug in
`reachy_embodiment`, tracked as a follow-up, not a safety issue since the
daemon's own state was checked independently rather than trusted from that
field.

## Session outcome

Motion testing stopped by owner decision after the head-tracking fault.
Daemon was stopped cleanly (`Daemon stopped successfully`, 20:00:21) before
ending the session, so no command could reach motors during the owner's
planned physical inspection. Embodiment container was left running (no
daemon reachable, so its own commands can only fail with connection
refused, not move anything). Physical inspection findings are a follow-up,
not part of this record.

## Status against the acceptance matrix

| Row | Result |
|---|---|
| Automated baseline | PASS (this session): 371 passed/14 skipped, Ruff clean, `bash -n` clean on launchers (ShellCheck unavailable on homelab box, not run) |
| Outbound connectivity | PARTIAL PASS: real WSS registration + incidental wrong-token rejection proven; TLS, network-change reconnect, revoked-token not exercised |
| Physical identity | PARTIAL: `sim=false` confirmed via daemon and hub HTTP registry; camera/fresh-scene and audible-playback correspondence not exercised |
| Motion/fallback | BLOCKED: head motor fault found on the very first real command; do not resume until physically inspected |
| Physical voice | BLOCKED: daemon audio device errors independent of the head fault |
| All other rows | Not attempted this session |
