# Handover

Current session snapshot: 2026-09-27. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) collects deployment limits and open
acceptance. This file holds only session continuation details.

## Current work

**[Phase 24e](docs/phase-24e.md) is in progress and is not ready to
close.** Everything it built is deployed. Most of its rows passed on the
robot with the owner:
- the [24e physical run](docs/verification/phase-24e-physical-2026-09-25.md)
  (2026-09-25/26);
- [clock, reply labelling and small.en](docs/verification/clock-routing-stt-physical-2026-09-27.md)
  (2026-09-27);
- the [correctness set](docs/verification/phase-24e-correctness-2026-09-25.md)
  (94.3%).

These exit criteria are still open:
- **Coexistence and sustained use:** the supervised 30-minute session.
  It's also a [Phase 25 prerequisite](docs/phase-24e.md#prerequisites-for-phase-25).
  It needs `max_session_seconds` ≥ 1800 for the run.
- **Adaptive end of turn:** cancelling a *held* turn on the robot. Long
  utterances with pauses already passed.
- **Item 4, Nano diagnostics:** not started. The Nano has no persistent
  journal (`/var/log/journal` is missing, and only the current boot is
  listed), no power logging, and no diagnosis procedure in the deployment
  guide. It needs the owner's sudo and approval for system changes.
- **Renewed owner acceptance of usability,** recorded after the above.

TV speech answered as a turn is a known limit, deferred to Phase 25 by
the owner. The audio-fault recovery sub-row is in process only, also by
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
  as designed). The daemon runs as PID 7340. It was resumed from standby at
  03:52Z and was `running` with no error at 05:27Z. The checkout is
  `6f6eb24`. Embodiment runs `reachy-embodiment:local` = `6f6eb24`
  (`0ab5ebdf`), recreated at 05:26:54Z with the read-only `/tmp` →
  `/host-tmp` mount. The rollback image `:edb03f5` (`e9df1677`) lacks the
  `/host-tmp` link, so roll back the checkout with it: the launcher at
  `edb03f5` recreates the old file bind. Older images are `:b36736d` and
  `:eb1e92e9`. Gestures and wobble are **off**, and they also reset to
  off on any embodiment restart. Sudo on the Nano needs a password, so the
  owner runs `systemctl` steps and container recreates. This dev box has
  key SSH as `Reachy-Mini-Jetson`. The system `python3` is too old for
  `voice-timing.py`: use `~/reachy-venv/bin/python`, and pass `--session N`
  when a log holds several voice sessions. No MediaPipe on the Nano (palm
  stop is hub-side); voice is enabled. `opencv-python-headless` for the
  24f tools is in `~/24f-tools` only (use `PYTHONPATH`). Logs are in
  `~/24f-logs` and `~/24d-logs`. `reachy-embodiment.service` and
  `reachy-daemon-recovery.service` are enabled, and the container has no
  Docker restart policy. Embodiment is host-networked on 8100, and the
  daemon is on loopback 8000. Apply the
  [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
  before daemon starts or motion; `--check` stays read-only.
- **Homelab:** the hub was rebuilt at `0ec9c52` (05:10Z). Core is unchanged
  since `c2db3d2` (2026-09-26 15:09Z). `STT_MODEL=small.en`,
  `PALM_STOP_ENABLED=true` and `VOICE_CONTINUATION_WINDOW_MS=3000` are in
  the private `.env`. The schema is `008_assistant_context`. The latest
  pre-deploy backup is
  `~/reachy-backups/reachy-before-clock-stt-deploy-20260927T041220.dump`
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
