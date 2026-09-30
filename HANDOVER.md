# Handover

Current session snapshot: 2026-09-30. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) owns deployment limits and open acceptance.

## Current work

Implemented [Phase 27.1 Foundation](docs/phase-27.md#271--foundation)
(owner-authorized ahead of Phase 26's security hardening, which the
roadmap otherwise lists as a Phase 27 prerequisite — see the roadmap row):
migration `010_meetings`, `companion_core.meetings` (durable `Meeting`
model, in-memory/Postgres `MeetingStore`, `MeetingWorker` with a real WAV
duration probe), companion-core's `POST/GET /meetings`,
`GET /meetings/{id}`, `POST /meetings/{id}/cancel`, owner-authenticated
proxies for the same on reachy-hub (`reachy_hub/operator.py`), and a
basic Meetings tab in operator-ui. Only PREPROCESSING is implemented; an
uploaded meeting correctly waits at TRANSCRIBING since 27.2 (long-form
STT) doesn't exist yet — see phase-27.md's Status section for what that
does and doesn't mean. `deploy/homelab/docker-compose.yml` and
`.env.example` gained the always-on `MEETING_AUDIO_DIR`/`meeting-audio`
volume (raw audio never goes in Postgres, same reasoning as the
owner-recognition capture store, but not optional — a meeting surviving
restart is the exit criterion). Ruff and the full companion-core/reachy-hub
pytest suites pass; see
[the verification record](docs/verification/phase-27-foundation-2026-09-30.md)
for exactly what ran and what didn't (no real Postgres, no live homelab
deploy, no real-browser check of the new UI — Playwright/Chromium weren't
available this session).
Also deployed the Phase 27.3 diarization dependency: the owner pointed at
`~/inferencing/diarization` (their own prior local experimentation,
previously tested standalone) and asked for it in reachy's deployment.
It's now `deploy/homelab/diarization/` (Dockerfile + app, model
weights/ONNX excluded — those regenerate into the `diarization-data`
volume on first start), a new `diarization` Compose profile
(`--diarization` on `scripts/start-homelab.sh`, needs an Intel iGPU
passthrough), and doc updates
([deployment](docs/deployment.md#meeting-diarization),
[service reference](docs/reference/services.md#meeting-diarization-phase-273),
phase-27.md's Status/27.3/27.4 sections). Verified with
`start-homelab.sh --check --diarization` (real `docker compose config`
against this dev box's actual `.env`, which does have `/dev/dri`) —
passed. Not built or run for real (no image build, no `/health` call);
`companion_core.meetings.worker` still does not call it.
Prior to this, this session earlier replaced [Phase 27](docs/phase-27.md)'s
own document with the owner-supplied Meeting Intelligence plan and updated
the roadmap/index/Phase 28 cross-reference (a documentation-only pass).
Implementation before that was paused by the owner at `294a1b6` (25a.4).
See the [phase ledger](docs/plan.md#6-implementation-roadmap) for scope and
[Phase 25 verification](docs/verification/phase-25-foundation-2026-09-28.md)
for the backend checks and last homelab deployment.

## Next session

1. Phase 27.1 foundation is implemented but not live-verified: run
   `010_meetings` against a real Postgres, redeploy the homelab stack with
   `MEETING_AUDIO_DIR`, upload a real recording through the operator-ui
   Meetings tab in an actual browser, and confirm the row/audio file
   survive `docker compose restart companion-core`. See
   [the verification record](docs/verification/phase-27-foundation-2026-09-30.md#next-verification-owed).
2. Phase 27.2 (long-form STT): decide where meeting transcription runs —
   companion-core doesn't currently own any STT (that's reachy-hub's
   `stt.py`, a lazy local faster-whisper instance used for conversation
   transport), and meeting transcription is an offline work-data pipeline,
   not conversation transport, so it likely needs its own local
   faster-whisper usage inside companion-core rather than a sibling import
   of reachy-hub's (disallowed outside tests, ADR 0001) or an HTTP call to
   a transport-owning service. `MeetingWorker.preprocess` (worker.py) is
   the natural place to add a TRANSCRIBING-stage handler once that's
   decided.
3. Phase 27.3 (diarization): the service dependency is now deployed
   (`deploy/homelab/diarization/`, `--diarization`) but never built or run
   — build the image, start it for real, confirm `/health` reaches
   `"status": "ready"` and `POST /diarize` returns segments for a real
   recording. Then wire `companion_core.meetings.worker`'s DIARIZING
   stage to call it (`http://diarization:8010` inside the compose
   network). Diarization doesn't need a transcript, so it may not have to
   wait on 27.2 (STT) — worth deciding whether DIARIZING can run before
   TRANSCRIBING completes, or whether the documented
   PREPROCESSING→TRANSCRIBING→DIARIZING sequence should stay strict.
4. Verify Settings · Accounts → Owner recognition in a real browser:
   opt-in, microphone recording, face capture, sample sizes, delete and
   export. Previous enrollment checks were backend-only; browser tooling
   availability must be rechecked rather than assumed.
5. Collect consenting owner/non-owner audio, including a separate dataset
   through the real Reachy microphone with noise/distance/orientation variation.
   Benchmark ECAPA and select thresholds from FAR/FRR before implementing its
   production adapter; measure concurrent Whisper + ECAPA on the homelab.
   The [existing smoke test](docs/verification/phase-25a1-voice-benchmark-2026-09-28.md)
   used public model-card clips only. Keep the sensitivity gate off pending
   the explicit owner decision described in the [plan](docs/phase-25.md#implementation-sequence).
6. Implement and evaluate the second-stage sensitivity classifier before
   enabling the gate; speaker verification alone cannot resolve UNKNOWN.
   Then proceed to 25b.1 DoA/orientation and face-model comparison. Full
   production gate prerequisites are in the
   [implementation sequence](docs/phase-25.md#implementation-sequence).
   AASIST benchmarking remains a separate pass.
7. Resume the owner-deferred 24g held-out run when requested: use the
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
8. Check the shortened privacy carry-forward window on the robot (calendar
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
