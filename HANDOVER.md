# Handover

Current session snapshot: 2026-09-25. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) collects deployment limits and open
acceptance. This file holds only session continuation details.

## Current work

[Phase 24f](docs/phase-24f.md) is in progress. Its physical rows are
waiting on a camera-measured Testbench check.
This session worked with the Nano-side session, with the owner at the
robot. The [conformance record](docs/verification/phase-24f-conformance-2026-09-25.md)
has the versions: daemon and SDK 1.8.4, hardware id `43c05f5047e8dcfe`.
REST and the SDK (Testbench) path command the same poses (≤0.005 rad),
but the robot stops 2–5° short on both. Joints fall short only when
their angle has to grow in magnitude, and don't settle further. For an
encoder-reported 16° yaw, the owner saw no head motion and heard the
motors. After the owner questioned the method, Pollen's sources were
checked. The stock stewart gains are proportional-only (PID 300/0/0),
which predicts this one-directional shortfall. The pinned Testbench
tolerates 5–15°, which explains its earlier pass. Pollen's conversation
app streams `set_target` rather than using goto, but the path is the same
from 1.8.4 to 1.11.0. So normal versus fault is open.

Unattended development testing is now allowed (owner's decision,
2026-09-25, in [AGENTS.md](AGENTS.md)). Full animations and the daemon's
wake-up still need the owner. `motion-conformance.py --camera DIR`
measures each move from head-camera frames, so nobody has to watch.

Next (the daemon start needs the owner, since it plays the wake-up; the
cases below don't):
- Run `motion-conformance.py --camera ~/24f-logs/frames --run zero-rest
  visible-rest axes-rest axes-sdk stream-sdk`, comparing camera-measured
  rotation with the encoders.
- Optionally run the official Testbench rotation test alongside `--log 60`.
- Only if the camera measurement disagrees with the encoders, inspect the
  mechanism and supply.

The Nano was parked in standby by the owner at 09:55:39Z, and
`reachy-embodiment` is stopped. To resume: `POST /api/daemon/start`
(wake-up motion, owner present), then start the unit. Not yet run:
antennas, body yaw, interp, cancel, recorded, preempt and visible-sdk.
Raw logs are in the Nano's `~/24f-logs`.

The motion owner (`reachy_embodiment/motion.py`, `4f43817`) is implemented,
with its [ADR 0003 amendment](docs/adr/0003-embodiment-command-api.md#phase-24f-motion-ownership-amendment-2026-09-25):
`CONVERSATION_MOTION_ENABLED` and `SPEECH_WOBBLE_ENABLED`, both off. It
was decided not to add a startup home, because 1.8.4's wake-up already
ends at IDLE_HOME. Tests are fake-backend and in-process only: embodiment
125 passed, 6 skipped, and ruff passes. The launcher passthrough is
untested on the Nano. Nothing is deployed: the Nano checkout was pulled to
`17a8ef9` for the conformance script, but the embodiment image is still
from 2026-09-24. `deploy/reachy/motion-conformance.py` runs one bounded
case per `--run`. Its SDK cases now reacquire daemon media: a 1.8.4
`no_media` SDK client releases the daemon's camera for everyone, which
blocked the embodiment start once.

The owner added [24e item 5](docs/phase-24e.md#5-open-palm-stop): a held
open palm stops a spoken reply and Reachy listens again. At the owner's
direction, detection now runs on the hub (`reachy_hub/palm_stop.py`,
MediaPipe). The robot (`reachy_embodiment/gesture.py`) only uploads 640 px
frames during playback when the hub's `PALM_STOP_ENABLED` (off) turns it
on for the session. Tested in process and in amd64 hub/embodiment image
builds, not deployed ([record](docs/verification/phase-24e-palm-stop-2026-09-25.md)).
Next: rebuild the hub on the homelab and the embodiment image on the Nano
(no motion needed), then the physical rows.

Branch `main`. [Phase 24e](docs/phase-24e.md) item 1 (adaptive end of turn)
is committed in `6f292be`. This session added item 2's deterministic part:
search-rule fixes in `companion_core/websearch/policy.py` (closings,
greetings and self-identity never search, bare "now" is not a freshness
cue, and follow-ups must refer back to the previous search) and an STT
`initial_prompt` with "Reachy" plus the persona name. Design choices are in
[the item 2 notes](docs/phase-24e.md#implementation-notes-item-2). A parallel
session had started the same policy rewrite and disconnected mid-edit; its
version was kept and completed. Nothing is deployed: the homelab hub and
Nano embodiment image still run the pre-24e turn path.

Verification: ruff passed. Core 380 passed, 18 skipped; hub 197 passed,
9 skipped; `slow` real-speech tests (tiny.en, espeak via
`/tmp/espeak-extract`) 11 passed, 1 skipped (no Piper model). In-process
only, not physical acceptance.

The correctness set (`services/companion-core/eval/`), its
[scoring rules](docs/phase-24e.md#correctness-set-scoring-rules) and the
owner's threshold (≥90% overall, every category ≥80%) were committed before
any measurement; plain statements with a freshness word no longer search.
The local model then passed it: 82/87 (94.3%), every category ≥ 87.5%,
in the [correctness record](docs/verification/phase-24e-correctness-2026-09-25.md);
the cloud model was not needed. Next: 24e item 4 (Nano diagnostics, needs
the owner's approval for system changes), then the physical run.
Deploy items 1–2 when the owner schedules the physical run. Phase 25
remains blocked on the
[hardware prerequisites](docs/phase-24e.md#prerequisites-for-phase-25).

## Last-reported machine state

These are previous session observations, not health checks performed during
this documentation pass. Recheck state before relying on them.

- **Nano:** checkout `00a5e68` or later; embodiment image from `1a66f01`,
  voice enabled. `reachy-embodiment.service` and
  `reachy-daemon-recovery.service` enabled; container uses `--mount` and no
  restart policy. Embodiment is host-networked on 8100, daemon loopback on
  8000. Apply the [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
  before daemon starts or motion; `--check` stays read-only.
- **Homelab:** dev/test stack at `9251efc`, schema `008_assistant_context`.
  Start only through `scripts/start-homelab.sh`. Piper `en_US-lessac-medium`;
  search policy Auto, Brave/Exa/Tavily rotation then SearXNG. Backups in
  `~/reachy-backups/` (0600). Core readiness needs a separate check after
  launcher hub health succeeds.
- **Local inference:** an unrelated `ovms` container previously served
  `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` on localhost:8000. Re-query
  `/v1/models`; leave unrelated services alone.
- Hosted credentials are in gitignored `deploy/homelab/.env.local`.
  Check presence and ignore rules without printing values. No Google OAuth
  client file or live helper run was supplied in the preceding session.
- Nano Tailscale endpoints to the homelab switched between 10.180.1.23,
  .54 and .254; a stall caused a watchdog disconnect before its increase
  to 15 s. Network cleanup remains the owner's call.
- Robot logs from 24d are in `~/24d-logs/`; `/tmp` is cleared on reboot.
  Development caches may also be gone; use [development](docs/development.md).

## Immediate cautions and continuation

The owner reports successful official Testbench zeroing and rotations after
24d's tracking anomalies; a persistent hardware fault is not established.
Phase 24f will compare the motion paths; current evidence is recorded below
in project state.
The unexplained power loss, RTC problem and daemon recovery verification
limit are in [project state](docs/project-state.md#known-hardware-and-software-limitations).
The automatic error restart remains fake-tested only.

Inspect `git status`, recent commits and the diff before implementation.
Hardware work previously involved a separate Nano-side session; verify raw
device identity before accepting remote reports. Use
[camera socket recovery](docs/deployment.md#camera-socket-directory-recovery)
if the socket becomes a directory again. Durable build, credential, upgrade
and supervision procedures are in the deployment/development guides.
