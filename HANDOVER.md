# Handover

Current session snapshot: 2026-09-28. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) owns deployment limits and open acceptance.

## Current work

Review follow-up completed: corrected Phase 26's stale plaintext claims,
recorded early benchmark controls and planned key-domain separation, and
made classifier acceptance an explicit gate-enablement prerequisite in
[Phase 25](docs/phase-25.md#request-sensitivity-classification).
No services, models or robot commands were run during this pass.
Implementation was previously paused by the owner at `294a1b6` (25a.4).
See the [phase ledger](docs/plan.md#6-implementation-roadmap) for scope and
[Phase 25 verification](docs/verification/phase-25-foundation-2026-09-28.md)
for the backend checks and last homelab deployment.

## Next session

1. Verify Settings · Accounts → Owner recognition in a real browser:
   opt-in, microphone recording, face capture, sample sizes, delete and
   export. Previous enrollment checks were backend-only; browser tooling
   availability must be rechecked rather than assumed.
2. Collect consenting owner/non-owner audio, including a separate dataset
   through the real Reachy microphone with noise/distance/orientation variation.
   Benchmark ECAPA and select thresholds from FAR/FRR before implementing its
   production adapter; measure concurrent Whisper + ECAPA on the homelab.
   The [existing smoke test](docs/verification/phase-25a1-voice-benchmark-2026-09-28.md)
   used public model-card clips only. Keep the sensitivity gate off pending
   the explicit owner decision described in the [plan](docs/phase-25.md#implementation-sequence).
3. Implement and evaluate the second-stage sensitivity classifier before
   enabling the gate; speaker verification alone cannot resolve UNKNOWN.
   Then proceed to 25b.1 DoA/orientation and face-model comparison. Full
   production gate prerequisites are in the
   [implementation sequence](docs/phase-25.md#implementation-sequence).
   AASIST benchmarking remains a separate pass.
4. Resume the owner-deferred 24g held-out run when requested: use the
   [scenario list](docs/phase-24g.md#acceptance-requirements) and
   [agreed targets](docs/phase-24g.md#agreed-numeric-targets-owner-2026-09-27),
   with conversational motion off. Include 3–5 immediate-question,
   3–5 natural-pause, and a few wait-for-acknowledgement attempts (user
   pauses to watch the alert pose, then speaks) — the doc's acceptance
   requirements were extended 2026-09-28 to cover this third interaction
   style and to require that speech is never lost to the animation. Record
   fresh evidence; the
   [previous held-out attempt](docs/verification/phase-24g-physical-2026-09-27.md#admission-fix-and-calibration-follow-up)
   failed before the timeout increased to 6 s.
   `WakeMonitor._listen_and_capture` (`services/reachy-embodiment/src/reachy_embodiment/wake.py`)
   already fires the alert-pose goto without awaiting it before starting
   capture, matching that requirement, but no test currently asserts the
   timing (only move ordering); consider adding one with a slow fake
   `rest_move` before relying on it further.
5. Check the shortened privacy carry-forward window on the robot (calendar
   question, then 7–8 unrelated turns), the Trusted mode UI, and palm stop
   after the next authorized standby/wake. These live checks remain open.

## Last-reported machine state

These are previous session observations, not health checks performed during
this documentation pass. Recheck state before relying on them.

- **Nano:** booted 2026-09-27 06:47 WIB (motor supply was off on the first
  boot; the once-per-boot recovery restarted the daemon once and stopped,
  as designed). The daemon runs as PID 7340 and was `running` at 09:33Z.
  - **Checkout/image:** `c579cc8` was physically verified at 10:57:45Z;
    the later `bab441e` latency-logging build was also reported deployed.
    Inspect the actual running revision before relying on either report.
    "Hey Reachy" was armed; the arm persists in the hub database.
  - **Rollback:** `:0880b1b` (`15ba2797`), then `:b62a023` (`ebfffcef`),
    then `:6f6eb24` (`0ab5ebdf`); roll the checkout back with it.
  - **Motion:** 24f gestures and wobble were switched **on** by the owner
    at about 10:48Z; they reset to off on any embodiment restart.
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

- **Homelab:** latest reported hub/core rebuild was `19c6545` on
  2026-09-28 06:34 UTC for encrypted benchmark capture. The capture store
  was left empty with benchmark mode off; schema remains `009_wake_arm`.
  `STT_MODEL=small.en`, `PALM_STOP_ENABLED=true` and
  `VOICE_CONTINUATION_WINDOW_MS=3000` are in the private `.env`. The
  latest pre-deploy backup is
  `~/reachy-backups/reachy-before-enrollment-hardening-deploy-20260928T063311.dump`
  (backups are 0600). Use the [homelab launcher](docs/deployment.md#homelab).
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

Use [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
before daemon starts or motion; launcher `--check` stays read-only. Keep
conversational motion off for Phase 25 until deferred 24f acceptance passes.
Hardware work previously involved a separate Nano-side session; verify raw
device identity before accepting remote reports.

Disposable Nano scratch: `~/24g-bench`, `~/24g-src`; acceptance logs under
`/tmp/.../scratchpad/24g-acceptance/` were session-scoped, not durable.
A recreated hub downloaded small.en again (112 s before voice worked);
this was noticed but not investigated.
