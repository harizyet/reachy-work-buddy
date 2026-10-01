# Handover

Current session snapshot: 2026-10-01. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) owns deployment limits and open acceptance.

## Current work

[Phase 29](docs/phase-29.md) (coding agent supervisor) added to the
roadmap, and its first stage, 29.1 (contracts and session store), is now
implemented at `services/coding-agent-service`: `CodingAgentSupervisor`
creates/resumes/stops a durable `CodingAgentSession` against a provider
registry and records normalized `CodingAgentEvent`s; a `SimulatedProvider`
and an in-memory store stand in for the real Claude Code adapter (29.3)
and Postgres durability (29.27), both still planned. Wire models
(`CodingProject`, `CodingAgentSession`, `CodingAgentEvent`,
`ProviderCapabilities`, `UsageSnapshot`, request schemas) live in
`shared/models/coding_agent.py`; routes/service-token constant in
`shared/protocols/coding_agent.py`. Added to the uv workspace
(`services/coding-agent-service`); `uv sync --all-packages` restored after
an accidental `--package`-scoped sync pruned the shared dev venv mid-session
(no production impact — dev venv only).

29.2 (container runner) is implemented too: `runtime.py`'s
`DockerCLIContainerRuntime` shells out to the real `docker` CLI to start a
labeled, resource-limited, non-root, no-socket container, and
`reconcile.py`'s `reconcile_sessions` marks a session `LOST` (never
`COMPLETED`) when its container is no longer running. Verified against
this machine's **real, live Docker daemon** — the same one running the
actual `reachy-homelab-*` production containers — using disposable
`busybox` containers labeled distinctly and always cleaned up; no
`reachy-homelab-*` container was touched, started, stopped or restarted.

29.19 (credentials) was pulled forward out of sequence, per explicit
instruction this session to make sure any real keys/login credentials this
phase needs are reachable from the web UI rather than left to env files:
`credentials.py`'s `EncryptedFileCredentialStore` (AESGCM, own key file via
`CODING_AGENT_SECRET_KEY_FILE`, separate from companion-core's keyring)
backs `PUT`/`GET`/`DELETE /providers/{provider}/credential` in
coding-agent-service; `reachy_hub/coding_agent.py` +
`reachy_hub/coding_agent_client.py` proxy those under owner cookie+CSRF
auth (same shape as `reachy_hub/accounts.py`); and the operator UI's
Settings · Accounts tab has a "Coding agent credentials" card
(`clients/operator-ui/coding_agents.js`) to set/replace/remove the Claude
Code or Codex credential — the secret is never echoed back once saved,
only `last_four`.

29.3 (Claude Code provider) is also now implemented, making the 29.2
runtime and 29.19 credential both actually used for the first time:
`claude_provider.py`'s `ClaudeCodeProvider` is wired into
`create_app()`'s default provider registry under `"claude-code"`, alongside
`"simulated"`. `services/coding-agent-service/docker/claude-code/Dockerfile`
builds a real image (`node:20-slim` + `npm install -g
@anthropic-ai/claude-code`) — **this was actually built and run on this
machine's real Docker daemon** (`docker build ...`, then `docker run
reachy-coding-agent-claude:latest --help`/`--version`/a real `-p "say hi"
--output-format stream-json` call with a deliberately invalid API key, no
real cost incurred) to confirm the exact CLI flags and JSONL output shape
rather than guessing from documentation. Confirmed live at claude-code
2.1.197: `claude`'s own `--session-id <uuid>` flag lets the provider assign
and know the session id immediately at start, instead of parsing it out of
output; `--output-format stream-json` prints one JSON object per line,
ending in a `{"type":"result",...}` line whose `is_error`/`usage`/
`total_cost_usd` drive completion/failure/usage; and a bad credential
produces repeated `{"type":"system","subtype":"api_retry",...}` lines
while the CLI retries for minutes rather than failing fast, which is why
`start_session` only starts the container and assigns the session id — it
does not block waiting for completion. `inspect_session` (exposed as the
new `POST /sessions/{id}/refresh` route) is what a caller polls later.
`--dangerously-skip-permissions` is never passed, matching AGENTS.md's
stance that the LLM has no authority to bypass its own action gate either.
A `collect_usage` using the parsed `usage`/`total_cost_usd` and an
opportunistic `RATE_LIMITED` status on a `429` retry line are also wired.
Verified end to end against the real image and real Docker daemon with an
intentionally invalid key (`services/coding-agent-service/tests/
test_claude_provider_docker.py`, opt-in via `CODING_AGENT_DOCKER_TEST=1`):
real container starts, real session id tracked, real stdout parsed, real
stop. **Completing an actual task against the real Anthropic API needs the
owner's own `claude-code` credential entered in the operator UI — that has
not happened and was not exercised by any automated test**, since it would
cost real money.

Two follow-up fixes/additions after 29.3 landed, both same-session:

1. **Bug found and fixed:** `ClaudeCodeProvider` originally sent every
   stored credential as `ANTHROPIC_API_KEY` regardless of its
   `CredentialKind` — an owner who picked "OAuth token" (a Claude Pro/Max
   subscription) in the operator UI would have had it silently fail to
   authenticate. Confirmed by grepping the real installed `claude.exe`
   binary for its actual env-var names: a subscription's long-lived token
   (from `claude setup-token`, run interactively elsewhere — this
   container cannot do that sign-in itself) belongs in
   `CLAUDE_CODE_OAUTH_TOKEN`, a different variable. `_credential` now
   reads the stored kind and routes to the right one; the operator UI card
   got an explanatory note on how to get a subscription token.
2. **Hard read-only guardrail for a real subscription credential (owner
   request, 2026-10-01):** this integration has never completed a real
   task against the real API, so a `CLAUDE_CODE_OAUTH_TOKEN` session is
   now forced read-only. The real, trusted layer is
   `ContainerSpec.read_only_mount` → a Docker `:ro` bind mount — **confirmed
   by an actual blocked write**, twice: once directly with `docker run`
   against a `:ro` volume, once with `docker exec` into a live, real
   `claude` container running with a subscription credential, both getting
   "Read-only file system". A tool-level restriction (`--disallowedTools`
   naming every tool claude-code 2.1.197 is known to advertise except
   `Read`/`Grep`/`Glob`/`WebSearch`/`WebFetch`, plus `--permission-mode
   plan`) is layered on top, but **is best-effort, not the guarantee** —
   live testing found `--allowedTools` alone does *not* restrict the
   active toolset the way its help text implies; only `--disallowedTools`
   measurably removed tools from a real init event's `tools` array. This
   is not a runtime toggle; lifting it for a subscription credential needs
   a deliberate future code change once the integration has actually
   completed a real task successfully. A pay-per-use API key session is
   unaffected. See `claude_provider.py`'s module docstring for the full
   reasoning and exactly what was tested vs. assumed.

Nothing wires coding-agent-service's *session* lifecycle into
companion-core or reachy-hub yet (29.6/29.7 — only the credential routes
reach the browser so far), there is no hook-based mid-task
`WAITING_FOR_INPUT`/`WAITING_FOR_PERMISSION` detection (29.4), and it is
not in `deploy/homelab/docker-compose.yml` — all deliberately deferred to
their own stages per
[docs/phase-29.md](docs/phase-29.md#2929--implementation-sequence).
41 coding-agent-service tests exist (37 pass by default; the 4 real-Docker
ones are opt-in via `CODING_AGENT_DOCKER_TEST=1` and all pass given the
built image, including the two guardrail checks above), plus 4 reachy-hub
tests (`test_coding_agent_credentials.py`) and one Playwright test
(`coding_agents.test.cjs`, run externally — Playwright/Chromium is not
installed in a default dev shell). Full `services shared` suite (994
passed; one unrelated `test_wake.py` flake reproduced as a pass on rerun,
not a regression) and `ruff check .` both still pass. See
[service reference](docs/reference/services.md#coding-agent-service-phase-29-planned)
for the exact route/behavior surface.

Meeting UI wording/layout cleanup is implemented locally, not deployed.
Rows separate title/status/date/actions; ALIGNING displays “Processing
paused” with the missing speaker-alignment feature explained. Raw errors
are collapsed in detail, and phase numbers are removed from user copy.
The reported metadata_errors row is the historical failure documented in
foundation verification; its dependency fix already exists. No records
were deleted or retried. Chromium with fixture data passed mobile layout,
literal text, paused wording, collapsed errors, detail reset and cancel
routing; JS syntax and Ruff passed. This is not live pipeline acceptance.
See [operator guide](docs/operator-guide.md#meeting-recordings).

Long-meeting transport fixes implemented: spooled Hub uploads, bounded
Core disk copies, file-backed worker inference requests, configurable
six-hour inference response waits and sidecar busy rejection. No schema
change. Existing live containers remain untouched; verification used a
separate `reachy-long-meeting-check` Compose project with read-only model
caches and the updated server source mounted into existing images.
See [long-audio verification](docs/verification/phase-27-long-audio-2026-09-30.md)
for exact checks and remaining limits, and
[operations](docs/deployment.md#long-meeting-recordings) for settings.
No representative human meeting recording was supplied.

The deployed pipeline stores raw speech results and waits at ALIGNING.
The live run built transcription and reused the owner's standalone
diarization container; it did not build the repository diarization image.
See the [verification record](docs/verification/phase-27-foundation-2026-09-30.md)
for dated evidence, dependency fixes and remaining acceptance. Four test
meetings remain in the database/audio volume; no delete endpoint exists.

## Next session

0. Phase 29 next: either a **real owner-authorized end-to-end run** (set a
   real `claude-code` credential in the operator UI — needs
   `CODING_AGENT_SECRET_KEY_FILE` set first, chmod 0600, or it won't survive
   a restart — then `POST /sessions` against a real test repository and
   poll `POST /sessions/{id}/refresh` to watch it actually complete and
   report real cost/usage; this costs real money and hasn't been done by
   any session yet), **or** keep building: 29.4 (Claude hooks) would wire
   `SessionStart`/`Stop`/`StopFailure`/`PermissionRequest`/`Notification`
   into the event bridge so a mid-task permission or input wait becomes
   `WAITING_FOR_PERMISSION`/`WAITING_FOR_INPUT` instead of just sitting in
   `RUNNING` until the container exits. Either way, decide whether a
   `Postgres*CodingAgentStore` is worth adding, or whether staying
   in-memory until restart durability actually matters (29.27) is fine a
   while longer. No `docker-compose.yml` entry yet; add one once there's
   real session-lifecycle wiring to companion-core/hub to supervise
   (29.6/29.7), not before.
1. Roll out the long-audio changes to Core, Hub and both sidecars, including
   the standalone diarization server (do not create a competing instance).
   Coordinate speech-token activation with that restart. Representative
   human speech/resource acceptance remains open despite synthetic
   65-minute infrastructure checks.
1. The pipeline reached ALIGNING with a short synthetic clip
   (upload → transcribe → diarize → wait at ALIGNING, ~2s); alignment
   itself is not implemented. Still owed: open
   the operator-ui Meetings tab in an actual browser (upload, record via
   `meeting-record-start`/`-stop`, and confirm the detail view renders
   `transcript_segments`/`diarization_segments` correctly — everything so
   far was exercised via curl, not a real browser); run a real 30–60
   minute multi-speaker meeting through it and record duration/RTF/CPU/
   RAM per the 27.2/27.3 exit criteria; decide what to do with the four
   leftover test meetings in the real database (no delete endpoint
   exists yet); decide whether to enable `SPEECH_SERVICE_TOKEN` (would
   need rebuilding/restarting the existing diarization container — see
   below); and confirm a meeting's row/audio file survive
   `docker compose restart companion-core`. See
   [the verification record](docs/verification/phase-27-foundation-2026-09-30.md)'s
   live-deployment addendum for exactly what's proven vs. still open.
2. 27.4 (alignment): once 1 above confirms both sidecars actually work,
   the next real gap is that `transcript_segments` and
   `diarization_segments` sit on the `Meeting` row unmerged — no
   canonical speaker-attributed `TranscriptSegment` exists yet, and
   `MeetingWorker` runs TRANSCRIBING/DIARIZING strictly sequentially
   rather than concurrently (ADR 0025 allows parallel; not done). Decide
   whether to tackle the parallelism and the alignment reducer together
   or separately.
3. 27.6 (meeting analysis): the Meetings detail view currently shows raw
   segments and says explicitly that minutes/decisions/actions don't
   exist — that's the next user-visible gap once 27.4 lands.
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

- **Homelab:** hub/core rebuilt and recreated 2026-09-30 for Phase 27
  speech inference (this session, real deployment — see Current work);
  schema is now `011_meeting_speech_results`. The `transcription` profile
  is running (`reachy-homelab-transcription-1`); `diarization` is
  **not** a `reachy-homelab`-managed container — it's the owner's
  pre-existing standalone `diarization` container (separate Compose
  project, `docker ps` shows it un-prefixed), joined to the
  `reachy-homelab_default` network by `docker network connect` so the
  `diarization` hostname resolves for companion-core; don't `docker
  compose -p reachy-homelab --profile diarization up` without first
  deciding whether to keep both or replace the standalone one (see the
  verification record). `STT_MODEL=small.en`, `PALM_STOP_ENABLED=true`
  and `VOICE_CONTINUATION_WINDOW_MS=3000` are in the private `.env`
  (unrelated to the new `MEETING_STT_MODEL=small.en` for the
  transcription sidecar, a separate model instance). The latest
  pre-deploy backup is
  `~/reachy-backups/reachy-before-phase27-speech-deploy-20260930T143344.dump`
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
