# Handover

Current session snapshot: 2026-09-27. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) collects deployment limits and open
acceptance. This file holds only session continuation details.

## Current work

**[Phase 24e](docs/phase-24e.md) closed by owner re-scope (2026-09-27).**
Everything it built is deployed. Most of its rows passed on the robot with
the owner:
- the [24e physical run](docs/verification/phase-24e-physical-2026-09-25.md)
  (2026-09-25/26);
- [clock, reply labelling and small.en](docs/verification/clock-routing-stt-physical-2026-09-27.md)
  (2026-09-27);
- the [correctness set](docs/verification/phase-24e-correctness-2026-09-25.md)
  (94.3%).

Owner decisions after closing, 2026-09-27:
- **Waived** as Phase 25 gates, never run on the robot: the supervised
  30-minute session, and cancelling a held turn (in-process test only).
- **Renewed usability acceptance.**
- **Deferred:** item 4, Nano diagnostics. The Nano has no persistent
  journal, no power logging and no diagnosis procedure. It needs the
  owner's sudo and approval.

**[Phase 24g](docs/phase-24g.md) is implemented, not deployed or
accepted (2026-09-27).** It is described in the
[ADR 0023 wake addendum](docs/adr/0023-robot-voice-conversation.md#addendum-wake-started-sessions-2026-09-27-phase-24g).

Owner decisions:
- monitoring is owner-armed and stays armed across restarts;
- anyone may converse while it is armed;
- candidates are transcribed in hub memory;
- the robot plays the wake animation on detection and rests in its sleep
  pose while armed and idle;
- the follow-up timeout is 10 s.

The detector is the community Edge Impulse "Hey Reachy" `.eim`
([bench and live session](docs/verification/phase-24g-detector-bench-2026-09-27.md)).
The robot's local acoustic-event filter is deferred, so the VAD and the hub
relevance rules gate candidates.

Verified off the robot:
- the fast suites, the browser tests and the Postgres migration suite (new
  `009_wake_arm`);
- the detector client against the real aarch64 model on the Nano, in a
  `--network none` container;
- the pinned `ADD` lines, built on the Nano's Docker 20.10.7.

Deployed 2026-09-27 (see machine state below). Not yet done:
- **Physical run:** arm from the panel and run the 24g scenarios. The
  wake-up move is a full animation with sound, so a development test of it
  needs the owner present.

`WAKE_ANIMATION_ENABLED` is on by default, including unattended production
use while armed. This is an owner decision of 2026-09-27, recorded in
AGENTS.md. The moves had not yet run on the robot in this flow when it was
made.

Scratch on the Nano: `~/24g-bench` (models, clips, wheels) and `~/24g-src`
(source mounts for the detector check); both are disposable.
Phase 25 owner recognition follows; its
24e prerequisites remain settled. Keep conversational motion off until
24f's deferred rows pass.

TV speech answered as a turn remains a known limit: 24g now covers false
wake admission, while Phase 25 retains speaker attribution and open-session
input gating. The audio-fault recovery sub-row is in process only, also by
owner decision.

**Owner decisions on 2026-09-27:**
- Open-ended spoken questions take about 8 s to first audio, because the
  local model writes about 60 words at about 21 tokens/s. This is
  accepted as is: the 4 s budget is measured on short questions.
- [Phase 24f](docs/phase-24f.md) is **closed by re-scope**. Its passed
  rows are silent poses, wobble, stops, 409 arbitration, palm stop and
  switch-off. The rest is deferred to a future phase, so Phase 25 runs
  with motion off until those pass.

**Fixed and deployed 2026-09-27:**
- **Camera across daemon media restarts** (`0ec9c52`, `6f6eb24`): a
  standby wake used to leave the camera and palm stop without frames
  until embodiment restarted. It is now verified with a no-motion media
  release/acquire
  ([record](docs/verification/phase-24f-physical-2026-09-27.md#camera-socket-fix-on-nano-1)).
  A real standby wake has not been retried: after the next `/reachy wake`,
  confirm that palm stop still works.
- **Abandoned palm-frame uploads:** the hub answers them with a 400
  instead of a traceback.

**Noticed, not investigated:** a recreated hub container downloads small.en
again (112 s before voice works).

## Last-reported machine state

These are previous session observations, not health checks performed during
this documentation pass. Recheck state before relying on them.

- **Nano:** booted 2026-09-27 06:47 WIB (motor supply was off on the first
  boot; the once-per-boot recovery restarted the daemon once and stopped,
  as designed). The daemon runs as PID 7340 and was `running` at 09:33Z.
  - **Checkout and image:** the checkout is `b77ff6a`, and embodiment
    runs `reachy-embodiment:local` = `b77ff6a` (`796d65ee`). The container
    was recreated by the owner at about 09:32Z with voice on and
    `WAKE_ANIMATION_ENABLED=true`, and registered as generation 4, wake
    capable. "Hey Reachy" was not armed yet at that point.
  - **Rollback:** the image is `:6f6eb24` (`0ab5ebdf`); roll the checkout
    back with it. Older images are `:edb03f5` (`e9df1677`, which lacks the
    `/host-tmp` link), `:b36736d` and `:eb1e92e9`.
  - **Motion:** 24f gestures and wobble are **off**, and reset to off on
    any embodiment restart.
  - **Access:** sudo on the Nano needs a password, so the owner runs
    `systemctl` steps and container recreates. This dev box has key SSH
    as `Reachy-Mini-Jetson`.
  - **Tools:** the system `python3` is too old for `voice-timing.py`: use
    `~/reachy-venv/bin/python`, and pass `--session N` when a log holds
    several voice sessions. There is no MediaPipe on the Nano (palm stop is
    hub-side). `opencv-python-headless` for the 24f tools is in
    `~/24f-tools` only (use `PYTHONPATH`).
  - **Logs:** `~/24f-logs` and `~/24d-logs`; the 24g image build logs are
    in `~/24g-logs`.
  - **Units:** `reachy-embodiment.service` and
    `reachy-daemon-recovery.service` are enabled, and the container has no
    Docker restart policy.
  - **Network:** embodiment is host-networked on 8100, and the daemon is on
    loopback 8000.

  Apply the [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
  before daemon starts or motion; `--check` stays read-only.
- **Homelab:** hub, core and migrate were rebuilt at `95cbc0a` (09:18Z,
  24g). `b77ff6a` changed only the robot side and docs. `STT_MODEL=small.en`,
  `PALM_STOP_ENABLED=true` and `VOICE_CONTINUATION_WINDOW_MS=3000` are in
  the private `.env`. The schema is `009_wake_arm`. The latest
  pre-deploy backup is
  `~/reachy-backups/reachy-before-24g-deploy-20260927T091652.dump`
  (backups are 0600). Start only through `scripts/start-homelab.sh`, which
  is allowed in the gitignored `.claude/settings.local.json`, so a session
  can run it. To restart only core, run
  `docker restart reachy-homelab-companion-core-1`: `docker compose
  restart` without the launcher fails on the generated SearXNG secret.
  Core readiness needs a separate check after the launcher's hub health.
  The hub's in-memory turn records (`GET /hub/robot-voice` with the
  `REMOTE_UI_TOKEN` bearer) give per-turn STT/LLM/TTS timings. They also
  contain transcripts, so extract only what a record needs. Piper
  `en_US-lessac-medium`; search policy Auto, Brave/Exa/Tavily rotation,
  then SearXNG.
- **Local inference:** an unrelated `ovms` container serves
  `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` on localhost:8000. Leave
  unrelated services alone.
- Hosted credentials are in gitignored `deploy/homelab/.env.local`.
  Check presence and ignore rules without printing values. No Google OAuth
  client file or live helper run has been supplied.
- Nano Tailscale endpoints to the homelab have switched between
  10.180.1.23, .54 and .254. Network cleanup remains the owner's call.

## Immediate cautions and continuation

The unexplained power loss, RTC problem, daemon recovery verification
limit and the 2–5° motion shortfall are in
[project state](docs/project-state.md#known-hardware-and-software-limitations).
The automatic error restart has one real run (2026-09-27, no motor power);
a wake-up error restart is still fake-tested only.

Inspect `git status`, recent commits and the diff before implementation.
Hardware work previously involved a separate Nano-side session; verify raw
device identity before accepting remote reports. Use
[camera socket recovery](docs/deployment.md#camera-socket-directory-recovery)
if the socket becomes a directory again. Durable build, credential, upgrade
and supervision procedures are in the deployment/development guides.
