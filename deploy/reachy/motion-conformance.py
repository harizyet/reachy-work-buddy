"""Phase 24f item 1: supervised REST vs SDK motion comparison.

Runs on the robot host with the daemon's own venv (reachy-venv/bin/python),
so the SDK path is the same one the official Testbench uses. Without
`--run` it only prints the plan: no connection, no motion. Each `--run CASE`
moves the robot, and needs the owner present and an OK for that case
(AGENTS.md). Targets and tolerances are fixed here, before measurement;
see docs/verification/phase-24f-conformance-*.md for results.

Only one controller may drive the daemon during a case. Stop
reachy-embodiment first, and do not run two cases at once.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request

PORT = 8000
BASE = f"http://127.0.0.1:{PORT}/api"

# reachy-mini 1.8.4 INIT_ANTENNAS_JOINT_POSITIONS, [right, left] in rad.
HOME_ANTENNAS = [-0.1745, 0.1745]
MOVE_S = 1.0
SETTLE_S = 0.8

# Predeclared tolerances (rad, metres). No upstream tolerance is published;
# these allow the ~0.034 rad static head error the Nano reported at rest
# after this boot's wake-up, with margin.
TOL_ABS_ROT = 0.05
TOL_ABS_XYZ = 0.003
TOL_ABS_JOINT = 0.05
TOL_REST_VS_SDK = 0.02
TOL_CROSS_AXIS = 0.03
TOL_HOLD_AFTER_STOP = 0.02

AXIS_TARGETS = [
    ("roll", 0.1),
    ("roll", -0.1),
    ("pitch", 0.1),
    ("pitch", -0.1),
    ("yaw", 0.15),
    ("yaw", -0.15),
]
ANTENNA_TARGETS = [[0.3, 0.0], [0.0, 0.3]]

CASES = {
    "zero-rest": "REST goto ZERO (identity head, antennas [0,0], body yaw 0), 1 s",
    "zero-sdk": "SDK goto_target ZERO, 1 s",
    "axes-rest": "REST: ZERO, then roll ±0.1, pitch ±0.1, yaw ±0.15 rad, each back to ZERO",
    "axes-sdk": "SDK: same targets as axes-rest",
    "antennas-rest": "REST: antennas [0.3,0] then [0,0.3] rad, head identity, then [0,0]",
    "antennas-sdk": "SDK: same targets as antennas-rest",
    "bodyyaw-rest": "REST: body yaw 0.2 explicit, then a head goto with body yaw omitted, then ZERO",
    "bodyyaw-sdk": "SDK: body yaw 0.2, then a head goto with the default body yaw, then ZERO",
    "interp": "yaw 0.15 over 2 s: SDK linear, SDK minjerk, REST 'linear'; head yaw sampled at 25 % and 50 %",
    "cancel-rest": "REST yaw 0.15 over 3 s, stopped by UUID at 1 s; pose sampled for 1.5 s",
    "recorded": "REST attentive1 to completion; final pose compared with start. Then IDLE_HOME",
    "preempt": "REST thoughtful1 stopped by UUID at 1.5 s; pose sampled for 1.5 s. Then IDLE_HOME",
    "failure-rest": "No motion expected: goto with interpolation 'bogus', unknown recorded move, stop of unknown UUID",
    "visible-rest": "Calibration: REST yaw +0.3 rad over 2 s and back to ZERO over 2 s, with late reads",
    "visible-sdk": "Calibration: SDK, same as visible-rest",
    "stream-sdk": "Pollen conversation-app method: 60 Hz SDK set_target stream, min-jerk ramp to yaw ±0.15 over 1 s, held while streaming",
    "home": "REST goto IDLE_HOME (identity, antennas [-0.1745, 0.1745], body yaw 0), 1.5 s",
}


def http(
    method: str, path: str, body: object | None = None, timeout: float = 5.0
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode(errors="replace")


def state() -> dict:
    code, body = http("GET", "/state/full?with_head_joints=true")
    assert code == 200, (code, body)
    pose = body["head_pose"]
    return {
        "t": round(time.monotonic(), 3),
        "x": pose["x"],
        "y": pose["y"],
        "z": pose["z"],
        "roll": pose["roll"],
        "pitch": pose["pitch"],
        "yaw": pose["yaw"],
        "body_yaw": body["body_yaw"],
        "antennas": body["antennas_position"],
        # [body_yaw, stewart_1..6] from the encoders; compare with ik_joints.
        "joints": body.get("head_joints"),
    }


_KIN = None


def ik_joints(roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0) -> list | None:
    """The joints the daemon commands for a target (its own IK engine).
    1.8.4's FullState drops target_head_joints, so recompute them."""
    global _KIN
    try:
        import numpy as np
        from reachy_mini.kinematics.analytical_kinematics import AnalyticalKinematics
        from scipy.spatial.transform import Rotation as R

        if _KIN is None:
            _KIN = AnalyticalKinematics(automatic_body_yaw=True)
        head = np.eye(4)
        head[:3, :3] = R.from_euler("xyz", [roll, pitch, yaw]).as_matrix()
        return [round(float(j), 4) for j in _KIN.ik(head)]
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        return [f"unavailable: {exc}"]


LATE_S = 2.0


def running() -> list:
    return http("GET", "/move/running")[1]


def daemon_errors() -> tuple[str, object]:
    status = http("GET", "/daemon/status")[1]
    return status.get("state"), status.get("backend_status", {}).get(
        "control_loop_stats", {}
    ).get("nb_error")


def rpy_pose(roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0) -> dict:
    # Fixed keys: a misspelled key validates as identity in 1.8.4.
    return {"x": 0.0, "y": 0.0, "z": 0.0, "roll": roll, "pitch": pitch, "yaw": yaw}


def rest_goto(duration: float = MOVE_S, *, wait: bool = True, **fields: object) -> str:
    body = {"duration": duration, **fields}
    code, resp = http("POST", "/move/goto", body)
    assert code == 200, (code, resp)
    if wait:
        time.sleep(duration + SETTLE_S)
    return resp["uuid"]


def sdk():
    from reachy_mini import ReachyMini

    return ReachyMini(
        host="127.0.0.1",
        port=PORT,
        connection_mode="localhost_only",
        media_backend="no_media",
    )


def sdk_goto(
    mini,
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
    *,
    duration: float = MOVE_S,
    **kw,
):
    import numpy as np
    from scipy.spatial.transform import Rotation as R

    head = np.eye(4)
    head[:3, :3] = R.from_euler("xyz", [roll, pitch, yaw]).as_matrix()
    mini.goto_target(head, duration=duration, **kw)
    time.sleep(SETTLE_S)


def record(label: str, requested: dict, measured: dict) -> dict:
    row = {"label": label, "requested": requested, "measured": measured}
    print(json.dumps(row))
    return row


def check_abs(requested: dict, measured: dict) -> list[str]:
    fails = []
    for axis in ("roll", "pitch", "yaw"):
        if axis in requested and abs(measured[axis] - requested[axis]) > TOL_ABS_ROT:
            fails.append(f"{axis} {measured[axis]:+.4f} vs {requested[axis]:+.4f}")
    for axis in ("x", "y", "z"):
        if abs(measured[axis]) > TOL_ABS_XYZ:
            fails.append(f"{axis} {measured[axis]:+.4f} m")
    if "antennas" in requested:
        for i, (m, r) in enumerate(zip(measured["antennas"], requested["antennas"])):
            if abs(m - r) > TOL_ABS_JOINT:
                fails.append(f"antenna[{i}] {m:+.4f} vs {r:+.4f}")
    if (
        "body_yaw" in requested
        and abs(measured["body_yaw"] - requested["body_yaw"]) > TOL_ABS_JOINT
    ):
        fails.append(
            f"body_yaw {measured['body_yaw']:+.4f} vs {requested['body_yaw']:+.4f}"
        )
    return fails


def summarize(rows: list[dict], fails: list[str]) -> None:
    print(
        json.dumps(
            {
                "summary": "PASS" if not fails else "FAIL",
                "fails": fails,
                "rows": len(rows),
            }
        )
    )


ZERO = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0, "antennas": [0.0, 0.0], "body_yaw": 0.0}


def rest_zero(duration: float = MOVE_S) -> None:
    rest_goto(duration, head_pose=rpy_pose(), antennas=[0.0, 0.0], body_yaw=0.0)


def run_zero(path: str) -> None:
    if path == "rest":
        rest_zero()
    else:
        with_sdk(lambda m: sdk_goto(m, antennas=[0.0, 0.0], body_yaw=0.0))
    measured = state()
    summarize([record(f"zero-{path}", ZERO, measured)], check_abs(ZERO, measured))


def with_sdk(fn) -> None:
    mini = sdk()
    try:
        fn(mini)
    finally:
        # In 1.8.4 a no_media client releases the daemon's camera and audio
        # on connect and does not give them back on disconnect. Reacquire,
        # or the camera socket stays gone and reachy-embodiment cannot start.
        try:
            mini.acquire_media()
        finally:
            mini.client.disconnect()
        print(json.dumps({"media_status_after_sdk": http("GET", "/media/status")[1]}))


def run_axes(path: str) -> None:
    rows, fails = [], []

    def go(roll=0.0, pitch=0.0, yaw=0.0, mini=None):
        if mini is None:
            rest_goto(
                head_pose=rpy_pose(roll, pitch, yaw), antennas=[0.0, 0.0], body_yaw=0.0
            )
        else:
            sdk_goto(mini, roll, pitch, yaw, antennas=[0.0, 0.0], body_yaw=0.0)

    def body(mini=None):
        go(mini=mini)
        base = state()
        rows.append(record("zero", {**ZERO, "ik_joints": ik_joints()}, base))
        for axis, value in AXIS_TARGETS:
            go(mini=mini, **{axis: value})
            measured = state()
            requested = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0, axis: value}
            requested["ik_joints"] = ik_joints(**{axis: value})
            rows.append(record(f"{axis}{value:+}", requested, measured))
            # Diagnostic only: does it keep settling after the checked read?
            time.sleep(LATE_S)
            record(f"{axis}{value:+} late (+{LATE_S} s)", requested, state())
            fails.extend(
                f"{axis}{value:+}: {f}" for f in check_abs(requested, measured)
            )
            delta = measured[axis] - base[axis]
            if math.copysign(1, delta) != math.copysign(1, value) or abs(
                delta - value
            ) > 0.3 * abs(value):
                fails.append(f"{axis}{value:+}: delta {delta:+.4f} (sign or magnitude)")
            for other in {"roll", "pitch", "yaw"} - {axis}:
                if abs(measured[other] - base[other]) > TOL_CROSS_AXIS:
                    fails.append(
                        f"{axis}{value:+}: cross-axis {other} moved {measured[other] - base[other]:+.4f}"
                    )
            go(mini=mini)
            record(
                f"back to zero after {axis}{value:+}",
                {**ZERO, "ik_joints": ik_joints()},
                state(),
            )

    if path == "rest":
        body()
    else:
        with_sdk(body)
    summarize(rows, fails)


def run_visible(path: str) -> None:
    """A larger move the owner can see, to calibrate the eye against the
    readback. Same absolute tolerances."""
    rows, fails = [], []

    def go(yaw, mini=None):
        if mini is None:
            rest_goto(
                2.0, head_pose=rpy_pose(yaw=yaw), antennas=[0.0, 0.0], body_yaw=0.0
            )
        else:
            sdk_goto(mini, yaw=yaw, duration=2.0, antennas=[0.0, 0.0], body_yaw=0.0)

    def body(mini=None):
        for yaw in (0.0, 0.3, 0.0):
            go(yaw, mini)
            requested = {
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": yaw,
                "ik_joints": ik_joints(yaw=yaw),
            }
            measured = state()
            rows.append(record(f"yaw {yaw:+}", requested, measured))
            fails.extend(f"yaw {yaw:+}: {f}" for f in check_abs(requested, measured))
            time.sleep(LATE_S)
            record(f"yaw {yaw:+} late (+{LATE_S} s)", requested, state())

    if path == "rest":
        body()
    else:
        with_sdk(body)
    summarize(rows, fails)


def run_stream() -> None:
    """How Pollen's conversation app drives the head: one loop calling
    set_target every tick, never goto, with the target held by continued
    streaming. Same yaw targets as the axes cases, for comparison."""
    import numpy as np
    from scipy.spatial.transform import Rotation as R

    rows, fails = [], []
    period = 1.0 / 60.0

    def head(yaw: float):
        m = np.eye(4)
        m[:3, :3] = R.from_euler("xyz", [0.0, 0.0, yaw]).as_matrix()
        return m

    def stream(
        mini, start: float, end: float, ramp_s: float = MOVE_S, hold_s: float = SETTLE_S
    ) -> None:
        t0 = time.monotonic()
        while True:
            t = time.monotonic() - t0
            if t >= ramp_s + hold_s:
                return
            s = min(t / ramp_s, 1.0)
            s = s * s * s * (10 - 15 * s + 6 * s * s)  # min-jerk
            mini.set_target(
                head=head(start + (end - start) * s), antennas=[0.0, 0.0], body_yaw=0.0
            )
            time.sleep(max(0.0, period - ((time.monotonic() - t0) - t)))

    def body(mini):
        sdk_goto(mini, antennas=[0.0, 0.0], body_yaw=0.0)
        base = state()
        rows.append(record("zero", {**ZERO, "ik_joints": ik_joints()}, base))
        current = 0.0
        for yaw in (0.15, 0.0, -0.15, 0.0):
            stream(mini, current, yaw)
            current = yaw
            requested = {
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": yaw,
                "ik_joints": ik_joints(yaw=yaw),
            }
            measured = state()  # read while the target is still being held
            rows.append(record(f"stream yaw {yaw:+}", requested, measured))
            fails.extend(
                f"stream yaw {yaw:+}: {f}" for f in check_abs(requested, measured)
            )

    with_sdk(body)
    summarize(rows, fails)


def run_log(seconds: float) -> None:
    """Read-only: samples pose and encoder joints at 5 Hz. Sends nothing, so
    it can run beside the official Testbench to log a known-working method."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        print(json.dumps({"log": state()}))
        time.sleep(0.2)


def run_antennas(path: str) -> None:
    rows, fails = [], []

    def go(antennas, mini=None):
        if mini is None:
            rest_goto(head_pose=rpy_pose(), antennas=antennas, body_yaw=0.0)
        else:
            sdk_goto(mini, antennas=antennas, body_yaw=0.0)

    def body(mini=None):
        for target in [*ANTENNA_TARGETS, [0.0, 0.0]]:
            go(target, mini)
            measured = state()
            requested = {"antennas": target}
            rows.append(record(f"antennas{target}", requested, measured))
            fails.extend(
                f"antennas{target}: {f}" for f in check_abs(requested, measured)
            )

    if path == "rest":
        body()
    else:
        with_sdk(body)
    summarize(rows, fails)


def run_bodyyaw(path: str) -> None:
    rows = []
    if path == "rest":
        rest_goto(head_pose=rpy_pose(), antennas=[0.0, 0.0], body_yaw=0.2)
        rows.append(record("explicit 0.2", {"body_yaw": 0.2}, state()))
        rest_goto(head_pose=rpy_pose())  # body_yaw omitted
        rows.append(record("omitted", {"body_yaw": "omitted"}, state()))
        rest_zero()
    else:

        def body(mini):
            sdk_goto(mini, antennas=[0.0, 0.0], body_yaw=0.2)
            rows.append(record("explicit 0.2", {"body_yaw": 0.2}, state()))
            sdk_goto(mini)  # SDK default body_yaw=0.0
            rows.append(record("default", {"body_yaw": "sdk default"}, state()))
            sdk_goto(mini, antennas=[0.0, 0.0], body_yaw=0.0)

        with_sdk(body)
    rows.append(record("zero", ZERO, state()))
    print(
        json.dumps(
            {
                "summary": "RECORDED",
                "note": "compare the omitted/default rows between paths",
            }
        )
    )


def sample_during(duration: float, fractions: list[float], start: float) -> list[dict]:
    out = []
    for f in fractions:
        time.sleep(max(0.0, start + f * duration - time.monotonic()))
        s = state()
        s["fraction"] = f
        out.append(s)
    return out


def run_interp() -> None:
    import threading

    from reachy_mini.utils.interpolation import InterpolationTechnique

    duration, target = 2.0, 0.15
    fractions = [0.25, 0.5]

    def sdk_case(mini, method):
        sdk_goto(mini, antennas=[0.0, 0.0], body_yaw=0.0)
        start = time.monotonic()
        t = threading.Thread(
            target=sdk_goto,
            args=(mini, 0.0, 0.0, target),
            kwargs={"duration": duration, "method": method},
        )
        t.start()
        samples = sample_during(duration, fractions, start)
        t.join()
        record(f"sdk {method.value}", {"yaw": target, "duration": duration}, samples)

    def body(mini):
        sdk_case(mini, InterpolationTechnique.LINEAR)
        sdk_case(mini, InterpolationTechnique.MIN_JERK)
        sdk_goto(mini, antennas=[0.0, 0.0], body_yaw=0.0)

    with_sdk(body)
    rest_zero()
    start = time.monotonic()
    rest_goto(
        duration, wait=False, head_pose=rpy_pose(yaw=target), interpolation="linear"
    )
    samples = sample_during(duration, fractions, start)
    record("rest 'linear'", {"yaw": target, "duration": duration}, samples)
    time.sleep(duration + SETTLE_S - (time.monotonic() - start))
    rest_zero()
    print(
        json.dumps(
            {
                "summary": "RECORDED",
                "note": "ideal yaw at 25%/50%: linear 0.0375/0.075, minjerk 0.0156/0.075",
            }
        )
    )


def stop_and_watch(uuid: str) -> list[dict]:
    before = state()
    code, resp = http("POST", "/move/stop", {"uuid": uuid})
    stopped_at = time.monotonic()
    samples = [before]
    for _ in range(6):
        time.sleep(0.25)
        samples.append(state())
    print(
        json.dumps({"stop_http": code, "stop_body": resp, "running_after": running()})
    )
    return [stopped_at, *samples]


def run_cancel() -> None:
    rest_zero()
    uuid = rest_goto(
        3.0, wait=False, head_pose=rpy_pose(yaw=0.15), antennas=[0.0, 0.0], body_yaw=0.0
    )
    time.sleep(1.0)
    _, *samples = stop_and_watch(uuid)
    record("cancel at 1 s", {"yaw": 0.15, "duration": 3.0}, samples)
    drift = max(abs(s["yaw"] - samples[1]["yaw"]) for s in samples[2:])
    fails = (
        []
        if drift <= TOL_HOLD_AFTER_STOP
        else [f"yaw moved {drift:.4f} rad after stop"]
    )
    rest_zero()
    summarize(samples, fails)


EMOTIONS = "pollen-robotics/reachy-mini-emotions-library"


def play_recorded(name: str) -> str:
    code, resp = http(
        "POST", f"/move/play/recorded-move-dataset/{EMOTIONS}/{name}", timeout=30.0
    )
    assert code == 200, (code, resp)
    return resp["uuid"]


def rest_home() -> None:
    rest_goto(1.5, head_pose=rpy_pose(), antennas=HOME_ANTENNAS, body_yaw=0.0)


def run_recorded() -> None:
    rest_home()
    start_pose = state()
    record("start (IDLE_HOME)", {"antennas": HOME_ANTENNAS}, start_pose)
    t0 = time.monotonic()
    play_recorded("attentive1")
    while running() and time.monotonic() - t0 < 15.0:
        time.sleep(0.25)
    elapsed = time.monotonic() - t0
    time.sleep(SETTLE_S)
    end = state()
    record("after attentive1", {"compare_with": "start"}, end)
    print(json.dumps({"elapsed_s": round(elapsed, 2), "errors": daemon_errors()}))
    rest_home()
    record("IDLE_HOME again", {"antennas": HOME_ANTENNAS}, state())
    print(json.dumps({"summary": "RECORDED"}))


def run_preempt() -> None:
    rest_home()
    uuid = play_recorded("thoughtful1")
    time.sleep(1.5)
    _, *samples = stop_and_watch(uuid)
    record("thoughtful1 stopped at 1.5 s", {}, samples)
    drift = max(abs(s["yaw"] - samples[1]["yaw"]) for s in samples[2:])
    fails = (
        []
        if drift <= TOL_HOLD_AFTER_STOP
        else [f"yaw moved {drift:.4f} rad after stop"]
    )
    rest_home()
    summarize(samples, fails)


def run_failure() -> None:
    before = state()
    results = {
        "bogus_interpolation": http(
            "POST",
            "/move/goto",
            {"duration": 1.0, "head_pose": rpy_pose(), "interpolation": "bogus"},
        ),
        "unknown_move": http(
            "POST", f"/move/play/recorded-move-dataset/{EMOTIONS}/no-such-move"
        ),
        "stop_unknown_uuid": http(
            "POST", "/move/stop", {"uuid": "00000000-0000-0000-0000-000000000000"}
        ),
    }
    time.sleep(0.5)
    after = state()
    for name, (code, body) in results.items():
        print(json.dumps({"case": name, "http": code, "body": str(body)[:300]}))
    moved = max(abs(after[a] - before[a]) for a in ("roll", "pitch", "yaw"))
    print(json.dumps({"running_after": running(), "max_rot_change": round(moved, 4)}))
    summarize([], [] if moved <= 0.01 else [f"head moved {moved:.4f} rad"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--run", choices=sorted(CASES), help="execute one case (moves the robot)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="daemon port (another port for a mockup-sim check)",
    )
    parser.add_argument(
        "--log",
        type=float,
        metavar="SECONDS",
        help="read-only: log pose and joints at 5 Hz for SECONDS (no motion)",
    )
    args = parser.parse_args()
    global PORT, BASE
    PORT, BASE = args.port, f"http://127.0.0.1:{args.port}/api"
    if args.log is not None:
        run_log(args.log)
        return 0
    if args.run is None:
        print("Plan only; nothing was sent. Cases:")
        for name, desc in CASES.items():
            print(f"  {name:14} {desc}")
        print(
            f"Tolerances: abs rot {TOL_ABS_ROT}, xyz {TOL_ABS_XYZ} m, joints {TOL_ABS_JOINT}, "
            f"REST vs SDK {TOL_REST_VS_SDK}, cross-axis {TOL_CROSS_AXIS}, hold after stop {TOL_HOLD_AFTER_STOP}"
        )
        return 0

    daemon_state, errors_before = daemon_errors()
    if daemon_state != "running" or running():
        print(
            json.dumps(
                {
                    "refused": "daemon not running or a move is active",
                    "state": daemon_state,
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "case": args.run,
                "daemon_state": daemon_state,
                "nb_error_before": errors_before,
            }
        )
    )
    name = args.run
    if name.startswith("zero-"):
        run_zero(name.split("-")[1])
    elif name.startswith("axes-"):
        run_axes(name.split("-")[1])
    elif name.startswith("visible-"):
        run_visible(name.split("-")[1])
    elif name == "stream-sdk":
        run_stream()
    elif name.startswith("antennas-"):
        run_antennas(name.split("-")[1])
    elif name.startswith("bodyyaw-"):
        run_bodyyaw(name.split("-")[1])
    elif name == "interp":
        run_interp()
    elif name == "cancel-rest":
        run_cancel()
    elif name == "recorded":
        run_recorded()
    elif name == "preempt":
        run_preempt()
    elif name == "failure-rest":
        run_failure()
    elif name == "home":
        rest_home()
        record("home", {"antennas": HOME_ANTENNAS, "body_yaw": 0.0}, state())
    print(
        json.dumps(
            {
                "case_done": name,
                "daemon": daemon_errors(),
                "media": http("GET", "/media/status")[1],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
