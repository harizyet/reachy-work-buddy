# HANDOVER.md

Living document. A new coding-agent session starts with **zero memory** of
prior sessions — this file is how it picks up where the last one left off.
Read this before doing anything else, then update it before you finish
your session (new phases done, new gotchas found, what's next).

This file is a *snapshot + gotchas* doc, not a duplicate of the real
documentation. For anything durable, the source of truth is:

- [AGENTS.md](AGENTS.md) — how to work in this repo (conventions, testing,
  Docker, dependency gotchas, verification discipline). Read this too,
  every session.
- [README.md](README.md)'s "Status" section — the authoritative, detailed
  per-phase record of what's built and how it was verified.
- [docs/plan.md](docs/plan.md) — the full roadmap and exit criteria.
- [docs/adr/](docs/adr/) — binding architecture decisions.

If anything below conflicts with those, trust the dated docs (README
Status, ADRs) over this file's prose — but update this file to fix the
conflict once you notice it.

## Where things stand

**Phases 0-21 are implemented.** Last implementation: **Phase 21 — Hybrid
local/cloud LLM routing**, now including a real hosted-provider live check.
See [ADR 0018](docs/adr/0018-hybrid-llm-routing.md).

- Core `llm/router.py` dispatches local-only, cloud-only, or local then cloud
  on actual failure. No automatic quality judgment. `force_frontier` travels
  hub → core and skips local for one generic turn; intents/consent still win.
- Cloud uses the existing compatible provider contract. First cloud setup
  defaults to fallback if local exists, otherwise cloud-only; explicit routing
  wins and subsequent edits preserve policy/omitted keys. Cloud policies
  require their providers. Disable both roles with local-only to restore echo.
- UI exposes cloud configuration, routing policy, one-message frontier toggle,
  role usage totals and latest escalation reason/time within the usage window.
  Cloud receives bounded conversation context, as explained in the UI.
- Usage persists each actual attempt and nullable `escalation_reason`:
  `manual` or `error`. Startup adds the column idempotently without resetting
  existing volumes; config remains JSONB. Reads map columns by name.
- Provider deadline 60 seconds total, hub timeout 130, browser 135. External
  cancellation does not fall back. Same-session turns still serialize.

**Phase 21 verification:** 300 Python tests passed (two existing deprecation
warnings), clean Ruff/JS/whitespace checks, and Chromium chat regression.
Real Docker/Postgres/Caddy/OVMS verification (`phase21verify`) covered local
success, unreachable-local fallback (both attempts logged), healthy-local
manual override, cloud settings and usage in Chromium at desktop/mobile,
and persistence across hub/core restart. An old-shape usage table was
upgraded and its seeded historical row survived with a null reason.
**OVMS backed both roles**; this is live dispatch/inference evidence, not a
hosted-cloud test. No `CLOUD_LLM_*` credentials were available in `.env.local`.
The temporary stack and volumes were removed; `ovms` remains untouched.

**Hosted-cloud live check (2026-09-22, `phase21togetherverify`):** the
owner chose Together AI's compatible endpoint (`https://api.together.xyz/v1`)
with model `zai-org/GLM-5.3` as the cloud role, key in gitignored
`deploy/homelab/.env.local` as `TOGETHER_API_KEY` (also mirrored under the
`CLOUD_LLM_*` names this file had been waiting on). A disposable isolated
Compose project (own throwaway Postgres/session-secret/admin creds, OVMS
as local role via `host.docker.internal:8000/v1` + the documented
`extra_hosts: host-gateway` override) verified, all through the owner-auth
hub API, not just curl-to-Together:
- Local-only success (OVMS reply, tokens/latency logged, `escalation_reason: null`).
- `force_frontier: true` on one message dispatched straight to Together and
  logged `escalation_reason: "manual"` with a real GLM-5.3 reply.
- Pointing local at an unreachable URL and sending a normal message produced
  a real error-triggered fallback: the failed local attempt logged with a
  sanitized `error_message` (no URL/key), the successful cloud attempt right
  after logged `escalation_reason: "error"`, and the user still got a real
  cloud reply.
- `GET /llm/usage` reflected all of the above correctly in both `entries`
  and `by_role` summaries; `PUT /settings/llm` masked the cloud key in every
  response.
- **Gotcha specific to this model:** GLM-5.3 is a reasoning model — its
  `reasoning_content` competes with `content` for the same token budget.
  A raw `curl` with `max_tokens: 10` came back with empty `content` (all
  budget spent on `reasoning_content`, `finish_reason: "length"`), which
  would trip `client.py`'s "Empty completion" `ValueError` → provider
  failure → fallback. `companion_core/llm/client.py` sends no `max_tokens`
  at all, so it takes Together's provider default, which was large enough
  in every check above (54-420 completion tokens) — but if cloud replies
  ever start coming back empty/truncated in production, check
  `finish_reason` on the raw response before assuming it's a routing bug;
  it's likely this model spending its budget on reasoning first.
- Local config was restored to the correct OVMS URL before teardown; the
  disposable stack and its volumes were removed, `ovms` left running.

### Phase 20 foundation (historical verification)

See [ADR 0017](docs/adr/0017-web-chat-channel.md), the root README Status,
and [chat deployment notes](deploy/homelab/README.md#web-chat-phase-20).

- The operator dashboard at `/hub/ui/` (direct hub: `/ui/`) now has
  Overview and Chat views. `chat.js` sends through the existing
  `POST /messages` with `Channel.WEB`/text modality; core's runtime is
  unchanged. Direct replies always render, regardless of routing metadata.
- `/status.default_user_id` comes from `TELEGRAM_DEFAULT_USER_ID`, so web
  chat starts with the same user as the bot. The UI also supports explicit
  user selection, shared with Overview. First send creates a session if
  needed. Mode/DND/active-channel indicators use existing session reads.
- The transcript is tab-local DOM only: refresh/logout/user switch clears
  it. “Clear view” does not reset the session or erase memory. Pending
  sends block duplicates/user changes; failures preserve drafts and warn
  against blind retries. Plain text rendering prevents HTML injection;
  login expiry clears the view and late logout responses are discarded.
- UI login is checked before sending, but `/messages` itself retains its
  existing trusted-network access contract. Do not claim a new API auth
  boundary or durable/retrievable chat history.
- `reachy_hub/telegram_health.py` holds `TelegramPollHealth` and the single
  `poll_updates` step. `app.state.telegram_poll_health` resets on restart.
  `/status.telegram` includes `configured`, `last_poll_at`, sanitized
  `last_poll_error`, and `healthy`. Success (including empty batches)
  clears errors; failures mark unhealthy immediately; 60 seconds without
  success is stale. This measures polling, not outbound delivery or LLM
  health; a slow message-processing batch can also become stale.
- Phase 20 itself added no schema, dependency, or core runtime changes.
  Phase 21 additions are recorded above.

**Phase 20 verification:** 287 Python tests passed, including speech and
WebRTC; Ruff, JavaScript syntax, and whitespace checks passed. The committed
Chromium regression at `clients/operator-ui/tests/chat.test.cjs` uses a
local HTTP fixture for browser behavior, including direct/proxied mounts,
HTML-looking text, failures, user switches, refresh, and login expiry/late
replies. Run it with Playwright available through Node's module path.

A separate real Docker/Postgres/Caddy run (`phase20verify`) used the actual
OVMS Qwen model and Chromium at desktop/390px mobile widths. A web message,
a simulated Telegram-channel HTTP call, and another web message shared IDs
and context; the model recalled “Teal.” Office/DND and a private calendar
reply worked in chat. An intentionally invalid temporary Telegram token
produced a real Bot API HTTP 401 while web chat still worked. No real
Telegram-account message was sent; successful-poll recovery was covered by
controlled unit tests. The temporary stack, volumes, and credentials were
removed; the existing `ovms` container was left running.

### Phase 19 foundation (still applicable)

See [ADR 0016](docs/adr/0016-operator-ui.md) and
[deployment instructions](deploy/homelab/README.md#operator-dashboard-phase-19).

- `clients/operator-ui/` is served at `/ui/` (Caddy: `/hub/ui/`). Plain
  HTML/JS/CSS; owner login, component probes, LLM utilization, runtime model
  configuration, existing-session mode/DND controls, audit/queue views.
- `reachy-hub` bootstraps one owner from `ADMIN_USERNAME`/`ADMIN_PASSWORD`
  when `SESSION_SECRET_KEY` is configured. PBKDF2 hashes in `users`;
  signed 12-hour HttpOnly/SameSite=Strict cookie. Cookie mutations require
  `X-Reachy-CSRF: 1`; bearer access remains supported. Telepresence uses
  the cookie now. Session mode/DND/privacy-context PATCH routes are gated.
- **There is now a real LLM.** Core's generic conversation branch uses
  `llm/client.py`; deterministic intent/consent handlers are unchanged.
  No provider means the old echo fallback; provider failures are logged
  and return an honest unavailable reply. In-memory transcripts now hold
  user/assistant messages, limit inference to the latest 39 messages,
  serialize simultaneous same-session turns, and preserve private context
  labels in generated follow-ups. Transcript history still resets on restart.
- Shared config contracts are in `shared/models/llm.py`, not a service
  package, so the hub proxy can validate without crossing runtime service
  boundaries. `LLMConfig` stores local/cloud providers and routing policy as one JSONB
  row in `llm_config` (the cloud role became active in Phase 21). Partial PUT
  merges fields; omitted keys retain credentials, explicit null removes
  them. Keys are masked in API responses but **plaintext at rest**.
- `llm_usage_log` records role/model/token counts/latency/success/errors,
  never prompts, completions, or raw provider error bodies. A missing token
  count is null, with an explicit unreported count in the dashboard.
- Caddy blocks `/core/settings/*` and `/core/llm/*` so the debug proxy cannot
  bypass the authenticated hub settings/usage routes. Other existing
  conversation/internal APIs retain their previous trust boundary.
- The old empty-string `TELEGRAM_BOT_TOKEN` polling bug is fixed. The UI
  now reports polling health through the Phase 20 extension above.

**Phase 19 verification (historical):** 278 tests passed including the real speech/WebRTC tests;
Ruff and JS syntax checks passed. Real image builds and isolated Compose
project `phase19verify` exercised Postgres/Caddy with Chromium desktop and
390px mobile. Real OVMS completion succeeded with persisted usage (first
call: 60 input / 17 output tokens, ~1.5 s), model settings/mode/DND controls,
credential masking, telepresence cookie access, logout, and Caddy isolation.
Settings, usage, owner login and session controls survived service recreation.
Stopping core showed its outage while retaining hub/robot status.

**This machine's OVMS is available:** `GET http://localhost:8000/v1/models`
returns `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov`; no key is required. It is an
existing Docker container named `ovms`, using GPU inference. Do not stop or
replace it as test cleanup. Core in Compose reaches it via
`http://host.docker.internal:8000/v1` with the `host-gateway` extra-host
mapping documented in deployment setup. The temporary verification stack
uses its own credentials/volumes and is removed after verification; these
credentials are not user deployment settings.

**Next work:** the hosted-cloud live check is done (see
`phase21togetherverify` above) — Together AI / `zai-org/GLM-5.3` is
verified end-to-end, but no production stack has this cloud config applied
yet; that's still a normal operator-UI action against the real deployment,
not something this session did to the user's actual running instance. Phases 22–23 are now planned in
[docs/phase-22-23.md](docs/phase-22-23.md) and the roadmap, not implemented.
The user confirmed an **original Jetson Nano**; OS/JetPack, Reachy variant
and physical wiring remain unknown. Start Phase 22 with that inventory and
resolve the ADR 0004 conflict if Nano would be the only embodiment host.
The plan defines real backend work, homelab/Reachy/Nano Bash launchers with
GUI access, measurable physical acceptance and soak tests. Phase 23 adds
production read-only Gmail/Calendar Accounts settings, OAuth, encrypted
credentials and live integration acceptance. No scripts or connectors were
implemented during this planning session, and no hardware was tested.
Existing uncommitted hosted-cloud verification notes in this file and
`deploy/homelab/README.md` were preserved.

**Phase 22 connectivity decision:** [ADR 0019](docs/adr/0019-robot-initiated-hub-connectivity.md)
accepts robot-initiated authenticated WSS, logical identity/capabilities and
active-connection routing; HTTP remains explicit dev/simulation compatibility.
Separate outbound HTTPS frame/PTT/audio transfers remove inbound robot media
dependencies while hub retains browser WebRTC. Launchers establish the robot
connection rather than register an address. Include token provisioning,
generation fencing, no command replay, bounded backoff and real network-change/
blocked-inbound/media-load tests. One hub worker initially. The actual runtime
is still HTTP; this session changed architecture/planning docs only. Existing
ADRs have scoped amendments; Nano placement/fallback constraints still apply.

**Phase 23 prerequisite planned:** add Alembic schema versioning with validated
legacy adoption and a serialized pre-start migration job, then a shared
core-owned SecretStore before Google tables/tokens. Migrate existing local/
cloud LLM keys from plaintext JSONB; reuse credential storage for Google,
SMTP and future connectors. The plan includes data-preserving upgrade,
interruption/restore tests, key rotation and historical-backup caveats.
Neither framework nor encryption is implemented yet; current plaintext/startup
DDL limitations still apply. ADR 0018 now records the later Together AI live
verification in a top amendment, preserving its original design decision.

**Phase 24 planned:** [docs/phase-24.md](docs/phase-24.md) defines single-owner
enrollment, strictly >60% calibrated live owner-in-view confidence for room
speech, separate speaker attribution before STT/conversation admission, and
continuous output cancellation on presence loss. Recognition never authorizes
email/calendar writes; authenticated text-only consent remains mandatory.
The scope includes API identity/modality bypasses, replay/liveness tests,
biometric retention, Nano failure behaviour and physical acceptance targets.
User clarification: calibration must run through the project's web portal,
with user-run accuracy tests. The plan now specifies a guided enroll/calibrate/
test/review/activate workflow using actual robot sensors, held-out labelled
trials, false-accept/reject reports, isolated diagnostics, versioned profiles
and server-enforced activation gates. No manual threshold editing is required.
No recognition code, enrollment or hardware tests were performed. Phases
22–24 remain planned; implement in roadmap order.

**Phase 22 inventory done, dependency blocker found (2026-09-22):** a
Claude Code session running directly on the physical Jetson Nano
(`reachy-mini` hostname) did Phase 22 deliverable 1. Device identity was
verified with raw hardware output (device-tree model, `nv_tegra_release`,
etc.) before trusting anything else it reported — see the "Device
verification" section of
[docs/verification/phase-22-inventory-2026-09-22.md](docs/verification/phase-22-inventory-2026-09-22.md)
for the full report and how to re-verify a future cross-session claim like
this. Key findings:

- Genuine original Jetson Nano, JetPack 4.6.1 (L4T R32.7.1, EOL), glibc
  2.27, Ubuntu 18.04 Bionic, 3.9GB RAM, Reachy Mini confirmed attached via
  USB device identity (camera/audio/motor-controller, not inferred).
- **This repo cannot `uv sync` on this board at all, on any of the three
  services** — not just the torch-heavy ones. Root cause: this board's
  glibc 2.27 vs. manylinux_2_28+-only wheels (torch for
  companion-core/reachy-embodiment, onnxruntime via faster-whisper for
  reachy-hub). This is a platform-wide ABI gap, not a per-service pin
  problem. Untested candidate fix: a newer-glibc Docker base image, since
  container userland glibc doesn't depend on host glibc for CPU-only
  workloads — not yet pursued (see below).
- A **pre-existing, working** Python 3.10 venv (`~/reachy-venv`) with a
  real `reachy_mini` SDK (1.8.4) already does real motor control on this
  box (`~/reachy/hello.py`), entirely independent of this repo's own
  dependency chain. Likely the real integration target for `RobotBackend`.
- **No second "Reachy onboard computer" exists.** Camera/audio/motor
  controller are all USB-attached directly to the Nano; the only working
  robot SDK reachable is on this same box. The owner decided: accept the
  Nano as the sole/required embodiment host rather than pursue a second
  host. [ADR 0004 was amended](docs/adr/0004-offline-fallback.md#phase-22-topology-amendment-2026-09-22)
  — homelab-outage survivability is unaffected, but the old "Jetson
  offline has no effect" guarantee no longer holds for this topology:
  Jetson offline now honestly means the robot is inert. `docs/phase-22-23.md`'s
  architecture table was updated to match (no more "if present" hedge).

**`~/reachy-venv` investigation done (2026-09-22, read-only):** targeting
`reachy-embodiment` at `~/reachy-venv`'s Python 3.10 does **not** fix the
torch/onnxruntime glibc wall above — confirmed the wall is
Python-version-independent (no torch/onnxruntime aarch64 wheel below
manylinux_2_28 exists for any CPython version). `reachy-embodiment`'s own
code also already requires Python ≥3.11 (`datetime.UTC`, `enum.StrEnum`),
independent of the repo's declared 3.13 floor — running it under 3.10
would fail on import regardless of dependencies. See the full report's
"Follow-up investigation" section for detail, including the reasoning
behind each conclusion.

**Genuinely useful finding underneath that, though:** `ReachyMini` (the
Python SDK class) is itself only an HTTP client to `reachy-mini-daemon`'s
own FastAPI server — the daemon process holds all the native complexity
(PyGObject, custom-built GStreamer 1.24, Rust kinematics/motor-controller
extensions), not the client library. So `reachy-embodiment`'s
`RobotBackend` doesn't need to share an interpreter with `reachy-venv` at
all: the daemon runs standalone under `reachy-venv` (already proven
working via `~/reachy/hello.py`), and `RobotBackend` becomes a thin
HTTP/websocket client to it — matching this repo's existing
services-talk-HTTP-only convention. `goto_target`/`play_move`/etc. map
reasonably onto `play_behaviour(name, parameters)`; `capture_frame()` is a
real mismatch needing actual work, since `ReachyMini`'s media surface is
session-oriented (`acquire_media`/`release_media`/`start_recording`) not
a stateless per-frame poll. The daemon's own HTTP/websocket API surface
(needed to implement this client) has not been investigated yet.

Also found: `~/reachy-venv` and its GStreamer/daemon setup is
**reconstructible from `~/.bash_history` only, not from any checked-in
script or recipe** — real, valuable setup work (Python 3.10 built from
source, custom GStreamer with a hand-patched compile error, PyGObject
version trial-and-error, Rust-built `gst-plugin-webrtc`) that would need
manual history-replaying to reproduce on a reflashed SD card today. No
systemd unit exists for the daemon either; it's only been run manually
for testing. Worth capturing as a real install script + service
regardless of the Python-target decision, before relying on it for
Phase 22's "repeatable deployment" deliverable.

**Owner decided (2026-09-22):** pursue the newer-glibc container route for
the torch/VAD blocker, and have the Nano session write the install
script/systemd unit + investigate the daemon API surface now (not wait).
All three landed:

- **Container test: RESOLVED — works, but viability as a long-term
  deployment path is still open.** After the owner ran `sudo usermod -aG
  docker reachy` and rebooted, `torch==2.9.1+cpu` installs and imports
  cleanly inside an `ubuntu:22.04` arm64 container (glibc 2.35 vs. the
  host's 2.27 — confirmed independently as expected). **This is the fix
  for the native `uv sync` dependency wall.** Two things are still
  untested before committing to it: (1) **memory headroom** — this board
  has only 3.9GB RAM and runs a full non-headless GNOME desktop, leaving
  ~1.6GB available at idle; torch/VAD + the rest of `reachy-embodiment`'s
  stack + container overhead + desktop wasn't load-tested and could swap
  hard; (2) **non-root device passthrough** —
  `/dev/video0`/`/dev/ttyACM0`/`/dev/snd/*` passthrough was only proven
  as root (uid=0), which bypasses the `dialout`/`video`/`audio` group
  gating `reachy-embodiment` would actually need to run under. See the
  inventory report's corresponding section for full numbers.

**Non-root device passthrough: also RESOLVED, no gap found.**
`--group-add <gid>` by numeric GID (`dialout:20 video:44 audio:29`,
`reachy` is already in all three on the host) gives correctly-permissioned
non-root access to all three device classes — verified with a positive
test (open-then-close succeeded on `/dev/video0`, `/dev/ttyACM0`,
`/dev/snd/controlC0`) and a negative control (same setup minus
`--group-add` correctly denied permission on video/audio; `/dev/ttyACM0`
is world-writable regardless of group, worth knowing). **Containerizing
`reachy-embodiment` on this board is now mechanically viable** —
install works, device access works. The RAM headroom question (only
~1.6GB available on this 3.9GB, non-headless board) is the only
remaining open concern before calling this a settled deployment path.
- **Install script + systemd unit: landed** at
  `deploy/reachy/install-reachy-venv.sh` and
  `deploy/reachy/reachy-mini-daemon.service` (see
  `deploy/reachy/README.md`'s new section). Transcribed from the Nano's
  bash history, **not re-run end to end** — validate on a clean SD card
  before trusting it unattended. One unresolved fragile step flagged
  inline: a `PyGObject` version pin whose original failure mode wasn't
  captured.
- **Daemon HTTP/WS API surface: investigated**, full endpoint map in
  `docs/verification/phase-22-inventory-2026-09-22.md`'s corresponding
  section. Key results: `GET /daemon/status` is the `connected`/`sim`
  source that was missing from the `ReachyMini` client class itself;
  camera access is WebRTC-only with no REST single-frame endpoint
  (confirms `capture_frame()` needs real implementation work, not a 1:1
  mapping); sound playback is upload-then-play, two calls; and — a real
  find — `GET /state/doa` exposes a daemon-computed `speech_detected`
  boolean that might serve as a **torch-free barge-in signal specific to
  the Nano**, sidestepping the glibc wall for that one piece of
  functionality. Not evaluated for accuracy/latency; flagged as an option.

**Memory load test: RESOLVED, comfortable headroom.** Correction first:
`reachy-embodiment`'s real dependency set is narrower than "the full
stack" — fastapi/uvicorn/silero-vad(torch+onnxruntime)/numpy/pillow only;
`sentence-transformers`/`faster-whisper` belong to `companion-core`/
`reachy-hub` in the homelab, not the Nano. Peak container footprint
measured at ~538MiB (torch import is ~190MB of that baseline); host
available memory only dropped ~100MB from baseline at peak, swap didn't
move, on a board with ~1.6-1.7GB available. **Fits comfortably — this
concern is closed.**

**Real bug found and fixed during this test (platform-independent, not
Nano-specific):** `silero-vad` 6.2.2 (what `silero-vad>=5.1` currently
resolves to) unconditionally imports `onnxruntime` but doesn't declare it
as a required dependency — only under an unrequested `onnx-cpu` extra.
This was silently masked in every dev/CI run because the shared
`--all-packages` dev venv gets `onnxruntime` for free via `reachy-hub`'s
`faster-whisper` (same masking class AGENTS.md already documents for
`python-multipart`) — `reachy-embodiment`'s own isolated Docker build
would have failed to start on any platform. **Fixed:**
`services/reachy-embodiment/pyproject.toml` now declares
`silero-vad[onnx-cpu]>=5.1`; re-locked, verified the isolated
`--package reachy-embodiment` install imports cleanly, full suite re-run
clean (300/300 tests, ruff clean). Committed on the homelab side.

**Phase 22's dependency-blocker thread is now fully resolved:** container
install works, non-root device access works, memory fits, and the
underlying `silero-vad` bug is fixed. The `/state/doa` VAD-alternative
idea is no longer required (the torch path is proven viable) but remains
available if ever wanted; would need the owner physically present since
daemon start moves the robot by default.

**Phase 22 deliverable 2 (`RobotBackend` real implementation): done, but
unverified against a live daemon.** `ReachyDaemonBackend` in
`services/reachy-embodiment/src/reachy_embodiment/robot.py` implements
the `RobotBackend` protocol as an HTTP client to `reachy-mini-daemon`,
selected via `ROBOT_BACKEND=reachy_daemon`/`REACHY_DAEMON_URL` (env vars,
`_default_backend()` in `app.py`; defaults to simulated when unset, same
as every prior phase, but an *unrecognized* value now raises at startup
rather than silently falling back — Phase 22's "real mode must fail
clearly" requirement).

- `connected`/`sim` query the daemon's `GET /daemon/status`; unreachable
  daemon → `connected=False`, `sim=True` (never claims confirmed real
  hardware when it can't verify). `PresenceLoop` now re-checks
  `backend.connected` periodically (`connection_check_seconds`, default
  2s) instead of only once at startup — previously `ServiceState.connected`
  never updated after boot regardless of backend, a real gap for a
  backend whose daemon connection can drop independently of homelab
  heartbeats. Bounded/rate-limited so a real backend's blocking HTTP
  check doesn't stall the 30Hz idle-animation loop.
- `play_behaviour` posts to `POST /move/play/recorded-move-dataset/{dataset}/{move_name}`,
  mapped from `Behaviour` via a configurable, **unverified** default
  mapping (dataset `"default"`, move name = the Behaviour's own string
  value) — no real dataset/move-name inventory has been done against a
  live daemon. A failed/missing move logs and no-ops rather than raising,
  so one bad mapping entry doesn't break every behaviour call.
- `capture_frame()` implements the V4L2/OpenCV-direct-access path
  (`/media/release` → `cv2.VideoCapture("/dev/video0")` → one frame →
  `/media/acquire`, always re-acquiring even on failure) discussed in the
  inventory report, since the daemon has no REST single-frame endpoint.
  Adds `opencv-python-headless` as a new dependency (manylinux2014 wheels,
  more permissive than the manylinux_2_28 floor that blocked torch/
  onnxruntime — expected fine given the proven container path, not yet
  confirmed on real hardware).
- `play_audio()` uploads via `POST /media/sounds/upload` then
  `POST /media/play_sound`; the upload response's field name is a guess
  among plausible keys (`path`/`file`/`filename`/`name`) since no live
  response has been inspected — raises `RobotBackendError` clearly if
  none match, rather than silently mis-playing or guessing further.
- **What was actually verified (not just unit-tested):** real `uv sync
  --frozen --package reachy-embodiment --no-dev` install succeeds
  (matches the Docker build shape); a real `docker build` of
  `services/reachy-embodiment/Dockerfile` succeeds with the new deps
  (`onnxruntime`/`opencv-python-headless`/`httpx` all resolve correctly);
  the built container actually run and hit over HTTP — default (simulated)
  backend serves `/health`/`/state` correctly; `ROBOT_BACKEND=reachy_daemon`
  pointed at an unreachable URL starts cleanly, reports
  `connected:false, sim:true` honestly, and `/behaviour/greeting` still
  returns 200 (logs the failed daemon call, doesn't crash the request);
  an unrecognized `ROBOT_BACKEND` value crashes at import/startup with a
  clear `ValueError`, not a silent sim fallback. Full suite: 317/317
  tests pass (15 new `ReachyDaemonBackend` tests against
  `httpx.MockTransport`, 2 new presence-loop connection-check tests),
  ruff clean. **What was NOT verified: anything against the real daemon**
  — no live `reachy-mini-daemon` has been started this whole Phase 22
  session (starting it moves the robot via `--wake-up-on-start` by
  default and needs the owner physically present/supervising), so the
  move-name mapping, upload-response field name, and status field
  semantics are all still best-effort reads of daemon source, not
  confirmed live behaviour. Next: either get the owner present to start
  the daemon and do a real end-to-end pass, or continue to deliverable 3
  (repeatable deployment/launchers) and fold live `RobotBackend`
  verification into that pass's acceptance testing.

**Phase 22 deliverable 3 (repeatable deployment), first piece — ADR 0019
WSS control connection: connectivity substrate implemented and verified
live, command routing deliberately deferred.** Owner-scoped decisions for
this slice: robot credentials are in-memory + `ROBOT_TOKENS` env var (not
Postgres — avoids one more ad hoc startup-DDL table right before Phase
23's migration framework), and this pass builds auth/registration/
generation-fencing/heartbeat/reconnect only, not semantic command routing
over the new connection (existing HTTP `EmbodimentClient` is completely
untouched and still how reachy-hub actually drives reachy-embodiment).

- `shared/protocols/robot_ws.py` (route `/robots/connect` + protocol
  version) and `shared/models/robot_ws.py` (Register/Registered/
  Heartbeat/HeartbeatAck/Error messages, WS close codes) are the wire
  contract both sides import — explicitly scoped to connectivity only;
  command/result/cancellation schemas are a follow-up.
- Hub side: `robot_credential_store.py` (`InMemoryRobotCredentialStore`,
  reuses `user_store.py`'s PBKDF2 hash/verify so plaintext tokens are
  never retained past provisioning; `load_from_env()` parses
  `ROBOT_TOKENS` as `{robot_id: token}` JSON, fails closed — unset means
  no robot can authenticate, same pattern as `REMOTE_UI_TOKEN`).
  `robot_connection_manager.py` (`RobotConnectionManager`, one
  authoritative connection per `robot_id`, process-local in-memory only
  per ADR 0019, atomic generation fencing that closes a superseded
  connection with code 4409). `robot_ws.py` installs the actual
  `/robots/connect` WebSocket route: rejects before `accept()` on
  missing/wrong credentials (surfaces as HTTP 403 to a real client, or
  `WebSocketDisconnect(4401)` under Starlette's TestClient — same
  behavior, different client-side framing), validates the register
  payload's `robot_id` matches the authenticated header identity and the
  protocol version matches, then runs a heartbeat/watchdog loop (2s/5s
  defaults) where *any* received message counts as liveness, not just
  explicit acks. Wired into `create_app` via new
  `robot_credential_store`/`robot_connection_manager` params.
- Robot side: `robot_ws_client.py`'s `RobotWSClient` connects out,
  registers, answers hub heartbeats, and reconnects forever (until its
  `run()` task is cancelled) with exponential backoff+jitter (1s
  doubling to 30s cap, per ADR 0019). Wired into `reachy_embodiment/app.py`
  via `HUB_WS_URL`/`ROBOT_ID`/`ROBOT_TOKEN` env vars — unset (the default)
  means no outbound connection is attempted at all, so every existing
  dev/simulation workflow is completely unaffected.
- New deps: `websockets>=13.0` added explicitly to reachy-embodiment
  (imports it directly; reachy-hub doesn't need a direct declaration
  since it only uses uvicorn's own server-side WS support, not the
  client API).
- **Verified for real, not just unit tests** (34 new tests across both
  services, all passing, ruff clean, 345/345 full suite): built real
  Docker images for both services; ran a live `reachy-hub` container
  against a disposable Postgres and connected a real `websockets` client
  from the host over the mapped port — full register/heartbeat/ack round
  trip worked, and a wrong-token attempt was correctly rejected (HTTP
  403, never reaching `accept()`); built and ran a real `reachy-embodiment`
  container pointed at the hub container over actual Docker networking
  (`HUB_WS_URL=ws://reachy-hub-phase22-test:8000`) — hub logs showed a
  real accepted connection from the embodiment container's real IP,
  stable with no reconnect loop; **stopped the hub container and watched
  the embodiment container detect the loss and retry with backoff for
  real** (`[Errno -3] Temporary failure in name resolution` while the hub
  was down, no crash, no tight loop); **started a fresh hub container and
  watched the embodiment container reconnect automatically** within its
  backoff schedule, no manual intervention. All disposable containers/
  images/network removed afterward.
- **What was NOT verified:** real TLS/Caddy in front of the WS route (the
  live test used a direct port mapping, not the documented HTTPS/WSS
  production path); real network changes/half-open connections (ADR
  0019's "physical LAN/Wi-Fi changes" acceptance row); multiple hub
  workers (explicitly out of scope — ADR 0019 requires one worker until
  connection routing across workers is designed); credential rotation/
  revocation exercised live (the store supports `revoke()`, not
  exercised end-to-end here); and obviously anything against the actual
  Jetson Nano or real Reachy Mini hardware — this was homelab-machine-only,
  two generic containers standing in for hub and robot.
- **Explicitly not done, by design, this pass:** semantic command routing
  over the WS connection (`play_behaviour`/`capture_frame`/`play_audio`
  still only ever go over HTTP via `EmbodimentClient`), the separate
  outbound HTTPS media transfer path ADR 0019 also calls for, token
  provisioning/rotation tooling beyond the env-var loader. The Bash
  launchers below now exist.

**Phase 22 deliverable 3, second piece — Bash launchers, done and mostly
live-verified.** `scripts/lib/common.sh` (shared `--env-file`/`--no-browser`/
`--check`/`--help` parsing, logging, bounded HTTP waits, browser-open-or-
print, secret-redaction helper) plus `scripts/start-homelab.sh`,
`scripts/start-reachy.sh`, `scripts/start-jetson.sh`,
`scripts/check-platform.sh`, matching docs/phase-22-23.md's launcher
contract table.

- `deploy/homelab/docker-compose.yml`: `reachy-embodiment` and `mailpit`
  are now gated behind a `simulation` Compose profile — a bare `docker
  compose up` (what `start-homelab.sh` runs by default) no longer starts
  either; `--simulation` (`--profile simulation`) does. `SMTP_HOST`/
  `SMTP_PORT`/`SMTP_FROM` and a new `ROBOT_TOKENS` passthrough are now
  `.env`-overridable for production. Verified live: `docker compose
  config --services` resolves to exactly the right 4 vs. 6 services in
  each mode; a real production-mode `up` (no simulation) started
  Postgres/hub/core/Caddy and served `/hub/health` through Caddy with
  no reachy-embodiment/mailpit containers created.
- `start-homelab.sh`: validates config, starts the stack (with `--build`/
  `--simulation` as needed), waits for hub health, reports whether
  `ROBOT_TOKENS` is configured, opens/prints the GUI. **Found and fixed a
  real bug by actually running it**: the shared arg parser originally
  used `readarray -t REMAINING < <(parse_common_args "$@")`, which runs
  the function in a process-substitution subshell — every
  `COMMON_ENV_FILE`/`COMMON_NO_BROWSER`/`COMMON_CHECK_ONLY` assignment
  inside it was silently discarded once the subshell exited, so
  `--check` did nothing and the very first live test of this script
  actually built and started the whole stack instead of validating and
  exiting. Fixed by having `parse_common_args` populate a global array
  (`COMMON_REMAINING_ARGS`) via a plain function call instead of stdout
  + subshell. Re-verified after the fix: `--check` now genuinely starts
  nothing; a real start (production mode) came up correctly; running it
  a second time created zero duplicate containers (`docker compose up
  -d`'s own idempotency); `--simulation` correctly added
  `reachy-embodiment`/`mailpit` (6 services vs. 4). All test
  containers/images/volumes removed after.
- `start-reachy.sh`: checks `reachy-mini-daemon` (systemd) is active and
  reports real hardware (`simulation_enabled`/`mockup_sim_enabled` both
  false) before doing anything else — refuses to proceed against a
  simulated daemon. Runs `reachy-embodiment` as a Docker container with
  the exact device/group-passthrough shape verified live on the Nano
  during this session (`--device`/`--group-add` by GID,
  `host.docker.internal` for reaching the host-run daemon), idempotent
  (won't duplicate an already-running container). **Honest limitation,
  documented in the script's own header and in
  `deploy/reachy/.env.example`**: command routing over the new WSS
  connection isn't built yet, so this script *also* still registers the
  robot's HTTP `base_url` with the hub the old way
  (`ROBOT_HTTP_BASE_URL`) — real behaviour/camera/audio commands
  currently need that, contradicting ADR 0019's "no inbound robot ports"
  end goal until command routing actually moves onto WS. Verified
  live on this homelab machine: `--help` output, and graceful/clear
  failure at each expected step (missing env file, daemon not
  installed) — could not be verified end-to-end against a real daemon
  from here (no Reachy hardware on this machine).
- `start-jetson.sh`: Nano-specific sanity checks (device-tree model,
  `/etc/nv_tegra_release`, hub reachability — all non-fatal/informational)
  then delegates to `start-reachy.sh` via `exec`, per the topology
  decision that the Nano is this deployment's embodiment host. Verified
  live (on this non-Nano machine, so the model check correctly warned):
  `--help`, and delegation actually happening and failing at the same
  step `start-reachy.sh` would on its own.
- `check-platform.sh`: non-destructive report covering host info, Docker
  toolchain, homelab role (compose config validity, redacted env status),
  and embodiment-host role (daemon status, device/group presence,
  container health) — whichever sections apply to the host it's run on.
  `--test-hardware` requires interactive confirmation (or `--yes`) before
  triggering one bounded `wake_up` move; never attempted in this session
  (no owner present, no real daemon here). Verified live on this
  homelab machine: correctly detected the homelab role, correctly
  reported all secrets as redacted ("set"/"unset" only, never values).
- **Also found and fixed while building this:** the root `.gitignore`'s
  `.env.*` pattern was silently swallowing any *new* `.env.example` file
  outside `deploy/homelab/` (whose copy only stayed tracked because it
  predated that gitignore rule) — `deploy/reachy/.env.example` (added
  this session) never showed up in `git status` until this was caught
  and fixed with a `!.env.example`/`!**/.env.example` negation. Worth
  checking for this pattern again if a future `.env.example` in some
  other new directory mysteriously doesn't show as untracked.
- **Critical safety bug found and fixed before any live Nano test (would
  have moved the robot unsupervised):** `start-reachy.sh` originally
  called `sudo systemctl start reachy-mini-daemon` *before* checking
  `COMMON_CHECK_ONLY` — meaning `--check` would have actually started
  the daemon (which moves the robot by default via `--wake-up-on-start`)
  if it wasn't already running, directly contradicting both the script's
  own documented "`--check`: start nothing" contract and this whole
  project's established rule that the daemon never starts without the
  owner physically present. Caught during review before asking the Nano
  session to run anything — not caught by `bash -n`/shellcheck, which
  can't reason about *when* a command runs relative to a flag check.
  Fixed: `--check` now only ever reads `systemctl is-active` and queries
  `/daemon/status` if already active; it never calls `systemctl start`.
  Verified with a faked `systemctl` shim: confirmed `--check` calls only
  `list-unit-files`/`is-active`, and non-`--check` mode still correctly
  attempts `start` (regression-checked, not just the fix in isolation).
**Launcher scripts: live-verified on the real Jetson Nano (2026-09-22),
one more bug found and fixed.** The Nano session pulled the `--check`
safety fix, independently reviewed the diff itself before running
anything (confirmed the guard genuinely sits before `sudo systemctl
start` and always exits first), then ran `check-platform.sh`,
`start-jetson.sh --check`, and `start-reachy.sh --check` for real —
nothing started, moved, or was installed; verified afterward via
`systemctl is-active` (inactive) and `docker ps -a` (empty).

**Second bug found along the way:** `systemctl list-unit-files
NAME.service >/dev/null 2>&1` — used by both `check-platform.sh` and
`start-reachy.sh` to detect whether `reachy-mini-daemon.service` is
installed — **exits 0 even for a unit that doesn't exist at all**, on
this board's systemd 237 (Ubuntu 18.04/Bionic); it only errors on
malformed input, not "zero matches" (confirmed with a made-up unit name
too, so not specific to this one service). Not a safety issue (`--check`
still never started anything either way), but it meant the diagnostic
report always claimed "installed" regardless of truth, and non-`--check`
mode would have skipped the clear "not installed, see
install-reachy-venv.sh" error in favor of a less helpful "failed to
start" message pointing at the wrong fix. **Fixed:** added
`systemd_unit_installed()` to `scripts/lib/common.sh` (checks
`list-unit-files --no-legend` actually has a result row, not just exit
code), used by both call sites; verified locally with a shim
reproducing the Nano's exact exit-0-empty-output behavior. Also
tightened `check-platform.sh`'s "time sync: unknown" line (same class
of gotcha — `timedatectl show -p NTPSynchronized --value` can return
empty without failing) with a fallback to parsing `timedatectl status`.
Both fixes pushed; **not yet re-verified live on the Nano** — that's the
natural next step before trusting the diagnostic report's "installed"
line again.

**Third bug: my own fix for the second bug regressed into a script-
crashing failure, also caught live by the Nano.** The `timedatectl show
-p NTPSynchronized --value` fallback I wrote assumed it could come back
*empty* on some systemd builds; on this board's systemd 237, `show` in
any form doesn't exist at all (`unrecognized option`/`Unknown operation
show` — a hard failure every invocation, not an empty result). Worse,
the fix used a bare, unguarded `VAR="$(cmd)"` assignment — under this
script's `set -euo pipefail`, that failure killed the *entire script*
immediately, before printing anything past the memory line, never even
reaching the correct fallback logic sitting right below it. The
original code had accidentally been safe (`|| echo unknown` lived
*inside* the same substitution); my rewrite split that into two
statements and dropped the guard on the first one.

**Fixed properly:** removed the `show` attempt entirely (it never works
on this systemd version, so there was nothing worth attempting first)
and parse `timedatectl status` directly, with an explicit `|| true`
guarding the whole pipeline (grep finding no match would otherwise hit
the identical crash class). **Also audited every other command
substitution in all four scripts for the same pattern** — verified
empirically (not assumed) that `echo "text: $(cmd)"` does NOT trigger
`set -e` even if `cmd` fails (only a bare `VAR="$(cmd)"` assignment
does, since then the substitution's exit status *is* the statement's
exit status) — found and fixed one more real gap
(`check-platform.sh`'s `STATUS_JSON` daemon-status curl was called
twice, once guarded/discarded and once completely unguarded; collapsed
to one guarded call) plus one low-risk-but-worth-guarding case
(`start-jetson.sh`'s device-tree `MODEL` read). Verified the actual fix
locally with a `timedatectl` shim reproducing the Nano's exact reported
behavior (`show` hard-fails, `status` works) — confirmed the script now
completes with exit 0 and prints "time sync: yes" correctly, all the
way to "=== end of report ===". Pushed; **not yet re-verified live on
the Nano** — three bugs deep in review/fix cycles on this one line is
itself a signal to have it confirmed live before trusting it again.

**Fix confirmed live on the Nano** — `check-platform.sh` completes with
exit 0, "time sync: yes" prints correctly, full report through "=== end
of report ===".

**Fourth issue, a pre-existing structural gap the Nano's fresh eyes
caught** (not a new bug from the three fixes above — it existed since
this script was first written, just masked): the entire "Embodiment-host
role" section, including device/group/`.env` checks that have nothing
to do with the daemon, was gated behind `if systemd_unit_installed
reachy-mini-daemon`. While that check was falsely always-true (bug #2
above), the section always printed; once fixed to be accurate on a host
where the daemon genuinely isn't installed, the whole section —
including info that's most useful *before* installing — silently
vanished. **Fixed:** the section now runs whenever the host plausibly
looks like an embodiment host (real Reachy Mini devices present, a
`deploy/reachy/.env` exists, or the daemon unit is installed), and
device/group/`.env`/container checks are always shown within it
regardless of daemon-install status; only the daemon-specific lines are
conditional, with an honest "NOT installed" message instead of silently
omitting the section. Verified locally (exit 0, correct output on this
homelab machine, which has `/dev/snd` so the section now appropriately
shows with honest "missing"/"NOT installed" lines rather than staying
hidden or lying), **and confirmed live on the Nano**: exit 0, full
report end to end, "NOT installed" line shows exactly as intended,
devices/groups/`.env` all correctly reported (matching the Nano's own
independent earlier checks). This closes out the launcher-script
verification round.

**Real hardware milestone (2026-09-23): reachy-mini-daemon started for
real on the Jetson Nano, robot woke and moved, sim=false confirmed
live.** The owner ran `sudo systemctl start reachy-mini-daemon`
themselves (this session's non-interactive sudo blocker — same as the
docker-group issue earlier — meant it couldn't be started via
`start-reachy.sh` alone); daemon logs show a real `Waking up Reachy
Mini...` / `Daemon started successfully`, and `GET /api/daemon/status`
confirmed `simulation_enabled: false, mockup_sim_enabled: false,
hardware_id: "43c05f5047e8dcfe"`. Two harmless daemon-log warnings
noted, not yet investigated: an audio recording-device open error
(`reachymini_audio_src`) and a gstplaybin2 sink-activation error —
daemon started fine despite them, may matter for the audio path later.

**Two more real, load-bearing bugs found immediately once the daemon
was actually live** — neither visible from source-reading, only from
querying the running daemon's real `/openapi.json`:

1. **Every reachy-mini-daemon route lives under `/api`** (e.g.
   `/api/daemon/status`, `/api/move/play/recorded-move-dataset/...`),
   not the bare paths the whole Phase 22 inventory and
   `ReachyDaemonBackend` assumed from reading router source alone (each
   `APIRouter`'s own sub-prefix like `/move` doesn't show the top-level
   `/api` mount applied when the daemon assembles its FastAPI app).
   Every HTTP call `ReachyDaemonBackend` makes would have 404'd — caught
   and no-op'd by existing error handling, so nothing would crash, but
   nothing would move the robot either. **Fixed** at the `httpx.Client`
   base_url level (append `/api` once at construction, verified httpx
   preserves it regardless of leading `/` on the request path) rather
   than touching every call site; added a `transport` constructor param
   so tests exercise the real base_url construction instead of bypassing
   it. Also fixed the same bug independently present in
   `start-reachy.sh` (`DAEMON_STATUS_URL`) and `check-platform.sh`
   (daemon status display, the `--test-hardware` wake_up trigger) — none
   of these were touched by the `robot.py` fix, since they're separate
   files making the same bare-path assumption.
2. **`start-reachy.sh`'s default port (8000) collides with the daemon's
   own port.** `reachy-mini-daemon` already binds host `127.0.0.1:8000`
   (confirmed via `ss -tlnp` on the Nano); `docker run -p 8000:8000`
   for reachy-embodiment would publish `0.0.0.0:8000`, overlapping the
   already-bound specific address. Predicted by the Nano session, not
   yet confirmed with a real `docker run` (the script died at the
   `/api` bug before reaching that step) — but the underlying host-port
   fact is confirmed real. **Fixed:** new `REACHY_EMBODIMENT_PORT` env
   var (`deploy/reachy/.env.example`), defaulting to 8100, resolved with
   precedence `--port` flag > env var > 8100 default; `check-platform.sh`
   reads the same var for its reachy-embodiment `/health` check instead
   of assuming 8000.

**Also found (unrelated to these fixes, but real):** `AGENTS.md`
previously claimed "plain `docker build` picks up buildx automatically,
no `DOCKER_BUILDKIT=1` needed" once `buildx` is installed — true only on
Docker Engine 23.0+ (where BuildKit became default). On the Nano's
Docker Engine 20.10.7, plain `docker build` still silently falls back to
the legacy builder even with `buildx` installed, and fails on the first
`--mount` exactly like a missing `buildx` would. **Fixed the doc** to
note the version cutoff and the explicit `DOCKER_BUILDKIT=1` workaround.
Also worth remembering generically (not fixed anywhere, just noted): the
Nano session's own first build attempt appeared to "succeed" only
because it had piped `docker build`'s output through `| tail -100`,
which silently discards `docker build`'s real exit code in favor of
`tail`'s (always 0) — caught only by checking `docker images` afterward
and finding nothing there. Same bug class as several of this session's
own script fixes, just in an ad hoc test command instead of committed
code — verify a piped build with a following `docker images`/`docker
inspect`, not the pipeline's own reported exit status.

**Fourth bug, found immediately after the previous three were verified
working: the daemon's `127.0.0.1`-only bind makes it unreachable from
any bridge-networked container, period** — independent of the `/api`
path fix and the port-collision fix, both of which were real and
necessary but didn't touch this. Confirmed directly on the Nano:
`docker exec reachy-embodiment curl http://host.docker.internal:8000/api/daemon/status`
→ connection refused, while the exact same call from the host itself
(`curl 127.0.0.1:8000/...`) succeeds; `curl 172.17.0.1:8000/...` (the
bridge gateway address `host.docker.internal` resolves to) also refused
from the host directly, proving this isn't a container-specific
routing problem — the daemon's listening socket itself only accepts
loopback-origin connections. Matches the daemon's own documented
default (`--fastapi-host 127.0.0.1`, `0.0.0.0` only with
`--wireless-version`) and this repo's own pre-existing
`reachy-mini-daemon.service` comment, which already assumed
same-namespace access ("fine as long as reachy-embodiment runs on this
same Nano") — that assumption just hadn't been checked against
Docker's default bridge isolation until the container was actually run
against the daemon for the first time.

**Fixed, per the owner's decision:** `start-reachy.sh` now runs
`reachy-embodiment` with `--network host` instead of bridge + `-p`/
`--add-host`, putting it in the same network namespace as the daemon so
`127.0.0.1:8000` inside the container genuinely is the daemon (new
`REACHY_DAEMON_URL` default). Trade-off, accepted: this container loses
Docker's network namespace isolation (device passthrough via
`--device`/`--group-add` is a separate mechanism, unaffected). Because
host networking removes the usual container-internal/external port
mapping, the image's baked-in `uvicorn --port 8000` CMD is now
explicitly overridden at `docker run` time to the resolved
`$HTTP_PORT` (8100 default) — otherwise reachy-embodiment's own listen
socket would try to claim host port 8000 too and collide with the
daemon exactly like the original bridge-mode default did.
`deploy/reachy/.env.example` updated to match (no more
`host.docker.internal` guidance).

**Confirmed live on the Nano (2026-09-23):** `--network host` fix
works. `GET /state` → `{"connected": true, "sim": false, ...}` — real
daemon, real hardware, genuinely reachable from the container. One
snag along the way, self-diagnosed and fixed by the Nano session rather
than reported back as a new bug: its own `deploy/reachy/.env`, created
earlier from the old `.env.example` template, still had the stale
`REACHY_DAEMON_URL=http://host.docker.internal:8000` hardcoded — since
`: "${VAR:=default}"` doesn't override an already-set variable, the
new `127.0.0.1` default never took effect until that file was updated
to match. A reminder that a stale personal `.env` copy can mask an
otherwise-correct code fix — worth checking first if a future session
sees unexpected old-behavior after pulling a fix that changes a
default.

**This closes out the "container reaches real daemon" bug chain**:
default-dataset naming (wrong dataset guessed) → `/api` prefix (bare
paths assumed) → port collision (8000 used twice) → bridge-vs-host
networking (daemon's loopback-only bind) — four real, load-bearing
bugs, each found only by actually running things against real
hardware, none catchable by reading source or by `bash -n`/shellcheck.

**Deliberately not yet done — the owner's explicit call, not a
blocker hit:** the actual `POST /behaviour/waiting` (or any other) move
trigger has **not been attempted**. Infrastructure connectivity is
fully verified; the actual SDK/move-triggering layer above it is not.
The owner chose to stop here for today and treat live animation/motion
verification as its own dedicated future session rather than
open-endedly live-debug whatever might surface at that layer today.
**Daemon and the reachy-embodiment container are both left running on
the Nano** (owner's choice) — a future session can pick up immediately
at "trigger the first real move" without re-running any install/start
steps, as long as nothing has changed the Nano's state in between.

**Not yet verified:** the daemon actually being installed/started via
these launchers (systemd unit was never installed on this Nano —
running `--check` against a genuinely-installed-and-active daemon has
not happened yet, and installing it plus starting the daemon needs the
owner physically present per this whole project's standing rule), or
anything past `--check` on real hardware. Given four real issues found
in this small a set of scripts across several review/fix rounds — a
destructive action ordered before its guard flag, a systemd command
whose exit code doesn't mean what it looks like, a "fix" that introduced
a worse crash than the bug it fixed, and a structural gap masked by one
of the other bugs — treat every further launcher change on this
old-systemd Nano target as needing live verification before trusting
it, not just `bash -n`/shellcheck (which caught none of the four). The
Nano session was disciplined throughout this round: reviewed every diff
itself before running it (including catching that a fix's own new
variable reference was actually defined, under `set -u`) rather than
taking fixes on trust, and reported the structural gap unprompted.

**First real move-trigger test, done on the homelab machine via the real
daemon's built-in simulator (2026-09-23), not yet repeated on the Nano.**
The owner explicitly asked to resume animation testing "but use the
simulator for now" rather than touch the Nano's real hardware. This
homelab machine is x86_64 with modern glibc/GStreamer already installed
via apt (none of the Nano's ABI wall applies here), so `pip install
reachy-mini` into a `--system-site-packages` venv
(`/tmp/reachy-sim-venv`, not committed — `/tmp` won't survive a session)
worked cleanly and pulled in the real `reachy-mini-daemon` (v1.11.0)
unmodified — this is the actual Pollen Robotics daemon, not this repo's
`SimulatedRobotBackend` stub. Ran it with `--mockup-sim --headless
--no-media` (no MuJoCo needed; `--no-media` sidesteps the missing
`gst-plugin-webrtc`/webrtcsink element, which Ubuntu's apt doesn't
package — irrelevant for motion-only testing) on port 8200 (8000 was
taken by `ovms`). Then ran `reachy-embodiment` itself
(`ROBOT_BACKEND=reachy_daemon REACHY_DAEMON_URL=http://127.0.0.1:8200`)
and drove it over real HTTP:

- `GET /api/move/recorded-move-datasets/list/pollen-robotics%2Freachy-mini-emotions-library`
  against the real daemon confirmed **all 14 move names in
  `robot.py`'s `_DEFAULT_BEHAVIOUR_MOVES`** (the mapping already fixed
  and said to be "verified live on the Nano" in commit 8878fd8) resolve
  to real, currently-existing entries in the real HuggingFace dataset —
  independent reconfirmation, not just trusting the Nano session's own
  report.
- `POST /behaviour/waiting`, `/listening`, `/thinking`, `/greeting`,
  `/sleep`, `/wake`, `/task_complete`, `/cannot_comply` each returned 200
  from `reachy-embodiment` and produced a real
  `POST /api/move/play/recorded-move-dataset/pollen-robotics/reachy-mini-emotions-library/<move>`
  200 on the daemon side (visible in its own access log, not inferred).
  `GET /api/move/running` showed real per-move UUIDs appear then drain
  over the next few seconds as each mockup-sim move actually completed —
  genuine move lifecycle, not a blind ack. One harmless recurring log
  line: `reachy_mini.kinematics.analytical_kinematics - WARNING - Head
  is not upright, recomputing FK` during several moves; daemon stayed
  healthy (`/api/daemon/status.error` stayed `null`) throughout.
- Unmapped behaviours (`idle_breathing`, `subtle_scan`, `antenna_twitch`)
  correctly logged-and-no-op'd on `reachy-embodiment`'s side exactly as
  designed, never reaching the daemon.

**What this does and doesn't prove:** this is the real daemon's actual
move-dispatch/dataset-loading/lifecycle logic exercised for real, a
genuine step up from unit tests against `httpx.MockTransport` — but
`--mockup-sim` has no MuJoCo physics and no visualizer, so nothing about
*correct* motion (trajectory shape, timing, collision) was checked, only
that the right move name in the right dataset gets accepted and
completes without error. It also doesn't touch `--network host`,
`--group-add` device passthrough, or any of the four real bugs already
found/fixed on the Nano (`/api` prefix, port collision, loopback-only
bind, dataset naming) — those were Nano-specific and this session ran
entirely on the homelab machine instead. The owner's original plan (an
actual `POST /behaviour/waiting` against real Nano hardware, robot
physically present) is **still not done** — this closes the "has nobody
ever actually triggered a named move end-to-end" gap, not the "verified
on real hardware" one. Both the throwaway daemon and the
`reachy-embodiment` uvicorn process were killed at the end of this
session; nothing was left running on the homelab machine.

**Cross-session coordination note:** this Phase 22 work happened live
across two Claude Code sessions (homelab + Nano) via `SendMessage`/cross-session
messaging, not a single session doing everything. If you're continuing
this work in a fresh session, check `ListAgents` for a live Nano-side peer
before re-deriving inventory facts by hand — but re-verify device identity
yourself the same way (raw `/proc/device-tree/model` etc.) rather than
trusting a peer's self-description, the same caution this session applied.

Phase 21 upgrades a current Phase 19/20 database additively. Earlier
missing-column caveats below remain relevant only to older schemas.

**Postgres schema-addition caveat (no migration framework yet, same as ADR
0010's precedent):** Phase 17 added `dnd`/`last_interruption_at` columns to
`sessions`, an `action` column to `audit_log`, and a whole new
`notification_queue` table. `CREATE TABLE IF NOT EXISTS` does not retrofit
columns onto an already-running dev Postgres volume — a session continuing
against a pre-Phase-17 volume needs explicit schema changes for those
columns. Preserve deployment data; recreate volumes only for disposable
test stacks. Confirmed clean in this sandbox because the volume
used for live verification was already down-and-recreated from a prior
session's `.env`; if a future session hits a column-does-not-exist error
from `postgres_session_store.py`/`postgres_audit_log.py`, this is why.

**Docker build speed (cross-cutting, ahead of Phase 17, not itself a
phase — same treatment ADR 0011 got):** there was no root `.dockerignore`
at all until now, and every service `Dockerfile` builds with context
`../..` (repo root) — every `docker compose build` was shipping the
*entire* repo, including `.venv` (~1.6GB) and `.git`, to the Docker daemon
on every single build, before a single `COPY` ran. Added a root
`.dockerignore` (mirrors `.gitignore` plus `docs/`/`.claude/`, neither of
which any Dockerfile references) and `RUN --mount=type=cache,...` around
every `uv sync` (and reachy-hub's `apt-get`) so repeated builds reuse
previously downloaded wheels/packages instead of re-fetching from the
network every time. Cache mounts need BuildKit (`docker buildx` — was also
missing in this sandbox, installed the same way as the `docker compose`
plugin; see AGENTS.md's Dev setup section) — without it these Dockerfiles
now fail outright on the first `--mount`, not just slowly. Measured live in
this sandbox after installing `buildx`: a full cold build (cache pruned,
`docker builder prune -af`) of all three services took **73s**; a
one-line-change incremental rebuild of just `reachy-hub` (cache mounts hot)
took **21s**. No prior-to-this-change timing was captured to compare
against directly, but shipping 1.6GB of context on every build was
self-evidently the dominant cost, not apt/uv download time — see
AGENTS.md's Docker conventions section.

ADRs on record: 0001 (service boundaries), 0002 (agent session), 0003
(embodiment command API), 0004 (offline fallback), 0006 (response
routing), 0010 (calendar), 0011 (destructive-action consent — voice can
never confirm a destructive action, bulk-destructive actions are always
blocked, email sends are delay-queued with an undo window), 0012 (Call
Reachy WebRTC — push-to-talk, not continuous VAD), 0013 (remote
telepresence — shared-bearer-token auth, fail-closed; polled-JPEG WebRTC
camera transport; speak-through-robot bypasses companion-core entirely),
0014 (interruption intelligence — whether/how aggressively to deliver a
proactive notification), 0015 (daily briefing — reuses 0014's engine for
the detailed content, adds an unconditional greet gesture on top),
0016 (operator UI, owner authentication, runtime inference and utilization),
0017 (web chat, transcript/access boundaries, Telegram polling health).
Note: 0005, 0007-0009 don't exist as separate ADRs — those phases didn't
need one.

A cross-cutting safety refactor (ADR 0011) landed *ahead of* Phase 15, not
as a numbered phase itself — the user asked for it explicitly mid-session
("before moving to phase 15... implement a hard safety mechanism..."). If
something like that happens again, it doesn't get a phase number; it gets
an ADR and a mention in the relevant phase's README "Status" entry.

## Before you start work

1. Read AGENTS.md in full — it has the load-bearing conventions (testing,
   Docker, uv dependency gotchas, verification discipline) this file
   doesn't repeat.
2. Read README.md's Status section for the detailed record of what's done.
3. Run `git log --oneline -20` and `git status` — confirm nothing is
   uncommitted or in a weird state left over from a prior session.
4. Check `docs/plan.md`'s roadmap table (§6) for the next phase's
   deliverable/exit criterion before writing any code.
5. If continuing mid-phase (uncommitted work exists), read the most recent
   commit messages and diff to reconstruct intent before continuing — they
   were written to be detailed enough for exactly this.

## Environment setup gotchas (this sandbox specifically)

- `docker compose` and `docker buildx` were present during Phase 19
  verification. Check their versions first in a new session. If Compose is
  missing, install without root:
  ```
  mkdir -p ~/.docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
    -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose
  ```
- `docker buildx` was missing in an earlier sandbox, separately from
  Compose — see AGENTS.md's Dev setup section for the install command if
  the version check fails. Every `Dockerfile` now
  starts with `# syntax=docker/dockerfile:1` and uses
  `RUN --mount=type=cache,...`, both BuildKit-only — without `buildx`,
  `docker build`/`docker compose build` fall back to the legacy builder
  and fail outright (not slowly — a hard error on the first `--mount`).
  Confirmed in this sandbox: `docker info` already showed a containerd
  snapshotter, but `docker buildx` itself was still missing until
  installed; check `docker buildx version` first, it may already be
  present. Like `/tmp/espeak-extract`, this is a `~/.docker/cli-plugins/`
  install and may not survive across sessions — expect to redo it.
- `espeak-ng` is not preinstalled and apt may not have root. It's been
  extracted without root before, to `/tmp/espeak-extract/usr/bin/` — check
  if it's still there; if not, redo it:
  ```
  apt-get download espeak-ng
  dpkg-deb -x espeak-ng*.deb /tmp/espeak-extract
  ```
  Then prefix any command needing it: `PATH="/tmp/espeak-extract/usr/bin:$PATH" <cmd>`.
  `/tmp` is not guaranteed to survive across sessions/restarts — expect to
  redo this.
- `deploy/homelab/.env` is gitignored and does not exist until you
  `cp .env.example .env` and set a real `POSTGRES_PASSWORD`. It does not
  persist in git history — a new session needs to recreate it (or it may
  still be on disk from a prior session; check first).
- For fast local iteration on the email-send-delay path (ADR 0011's real
  ~10-minute default), set in `.env`: `EMAIL_SEND_DELAY_SECONDS=10` and
  `EMAIL_DISPATCH_INTERVAL_SECONDS=2`. Leave unset for anything meant to
  reflect real production behavior.
- Phase 19: set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and
  `SESSION_SECRET_KEY` for browser login. Existing bearer clients still use
  `REMOTE_UI_TOKEN`; the protected remote-control routes return 503 only
  when neither bearer nor owner-session access is configured. Core's
  `/debug/robots/...` proxy still needs the shared bearer token in both
  services because it does not use a browser cookie.
- The Phase 19 and Phase 20 temporary stacks and credentials were removed
  after testing.
  Only the existing `ovms` container remained running. The user's deployment
  `.env` and volumes were not replaced; `/hub/ui/` requires starting their
  configured stack before it is reachable.

## Current verification gotchas

- In this Codex sandbox, FastAPI TestClient can hang under socket
  restrictions. Running the test command with approved sandbox escalation
  resolves it. Docker and localhost HTTP/browser checks also need escalation.
- `espeak-ng` is available at `/tmp/espeak-extract/usr/bin/espeak-ng` in
  this session. The final full-suite command used
  `PATH="/tmp/espeak-extract/usr/bin:$PATH" .venv/bin/pytest services shared -q`.
- Chromium and Playwright are already cached: browser under
  `~/.cache/ms-playwright/`, JS package under
  `~/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`. These cache paths
  may change in later sessions. No browser dependency was added to the repo.
- `docker compose up -d` returns before Uvicorn startup completes. Wait
  for `/hub/health` before testing; immediate calls can get Caddy 502s.
- Signed cookie logout clears the browser cookie, not a server-side
  revocation list. The default deployment remains trusted homelab/VPN;
  see ADR 0016 for the exact authentication boundary and limitations.

## Live verification workflow

Use the isolated-stack guidance in [AGENTS.md](AGENTS.md#isolated-live-verification-and-schema-changes).
Prepare temporary credentials in a restricted local file and use a named
Compose project. Reuse the same project name, env file, and override files
for build/start/restart/cleanup. Wait for `/hub/health`, then test the UI,
API, real inference, usage, and persistence through Caddy. `down -v` is
appropriate only for that disposable test project, never for an existing
user deployment. Phase 20 used `phase20verify` and left `ovms` untouched.

The latest evidence above is from the Phase 21 implementation session.
Agent conventions, roadmap, ADRs, UI/service/deployment guides, and this
handover were updated alongside the implementation.

## Conventions this file won't repeat (see AGENTS.md for all of them)

- `--import-mode=importlib` + no `__init__.py` in service `tests/` dirs.
- Every new companion-core store needs to be injected into
  `services/companion-core/tests/test_app.py`'s `make_chain` **and** the
  reachy-hub test factories, including WebRTC and operator tests — see
  AGENTS.md's Phase 19 conventions for the complete list.
- `uv.lock`/`[tool.uv.sources]` gotchas for GPU-adjacent or CPU-only
  packages (torch, etc.) — read AGENTS.md's "uv dependency conventions"
  before adding any ML/heavy dependency.
- Commit messages end with
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` (or whatever
  the current system reminder specifies — check it fresh each session,
  attribution conventions can change).
