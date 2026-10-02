# Handover

Current session snapshot: 2026-10-02. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) owns deployment limits and open acceptance.

## Current work

**Wake alert pose removed (2026-10-02, uncommitted, not deployed):** a raw
wake-detector hit no longer moves the head; only hub admission brings it to
home. Embodiment tests/ruff pass. Needs an embodiment rebuild and a physical
check of the delay between admission and head lift. Not done: a "visible
false activations / hour" metric in the 24g acceptance, and detector-threshold
tuning. `RestPose "alert"` remains in motion.py, unused by the monitor.

**Phase 29 is closed for the subscription-first scope (2026-10-02, deployed
to the homelab, uncommitted).** Characterization found that the agent's
`AskUserQuestion` tool call and `permission_denials` separate needs-owner from
done; hooks were not needed. Built: confirmed `WAITING_FOR_INPUT` /
`WAITING_FOR_PERMISSION`, intervention fields and `turn`, a per-session
`reachy-claude-state-*` volume so `--resume` works, `/coding_reply` (verbatim
relay), turn-keyed notification claims, Git observations, and the "Terminal
sessions (view only)" label. Details and the unexercised list:
[closure](docs/phase-29.md#characterization-results-and-closure-2026-10-02).
The agent image `reachy-coding-agent-claude` must be rebuilt on any other host
(`docker build` in `services/coding-agent-service/docker/claude-code`). Terminal
sessions stay view-only; CLI findings and open options (Remote Control spike,
`--bg` provider, idle push) are in
[phase-29](docs/phase-29.md#controlling-terminal-sessions-cli-findings-2026-10-02).
Left
behind by live testing: a `git-probe` project (path `/tmp/claude-1000/gitprobe`)
and two probe sessions in the homelab database. `test_robot_voice.py::
test_spoken_command_text_does_not_actuate_the_robot` fails on a clean tree too.

**Running-session poller (2026-10-02, deployed):** coding-agent-service
now inspects in-flight sessions every 30 s (`CODING_AGENT_POLL_INTERVAL_SECONDS`,
`0` disables) so finished containers reach `COMPLETED` and Telegram's completion
push fires. Verified with fixture runtimes and a lifespan test, not a real Claude
container. Still missing: the 29.4 hook bridge (WAITING_FOR_INPUT/PERMISSION,
hook-driven RATE_LIMITED, Stop/SessionEnd). A live probe (see phase-29 29.4 note) showed hooks surface in the stream with `--include-hook-events`, but a headless run that asks a question still ends as a plain success; do not build WAITING_* from hooks without observed evidence from subscription sessions (the API-key probe originally proposed here is deprioritized, see above). Poller deployed live and verified (probe session reached `completed` unprompted).

**Reachy sees terminal sessions (2026-10-02, built, not deployed):** the status
reply (`/coding_sessions`, "is my claude session done") now adds a read-only
"Terminal sessions" section via companion-core's new
`list_terminal_sessions` client call. Control (resume/send instruction, or
adopting a terminal session as a managed one) was offered and deliberately not
built. Rebuild core to activate; it needs `CLAUDE_PROJECTS_DIR` already
mounted in coding-agent-service.

**Durable coding-agent sessions and Claude allowance are deployed to the
homelab (2026-10-01, Phase 29.27/29.26).** Migration `013_coding_agent` applied
(pre-upgrade dump: `~/reachy-backups/reachy-before-013-20261001-223839.dump`);
migrate, core, hub and coding-agent-service rebuilt and running, health OK, the
allowance route enforces auth. No non-terminal sessions existed at startup, so
no live recovery was exercised. The rest of this entry predates the deploy.
**Coding agents tab (2026-10-01, built, not yet deployed/browser-tested):** new operator-UI tab after Meetings (`coding_monitor.js`) with owner-gated hub proxy routes `/coding-agents/*`; creates projects and sessions, shows allowance, sessions, events and usage. Tests/ruff pass; `node --test` cannot run here (no playwright). Needs a hub rebuild and a browser check. Send instruction/Respond are not in the tab. Deployed to reachy-homelab, with a read-only terminal-sessions list (needs CLAUDE_PROJECTS_DIR, set in .env). CAUTION: always pass `-p reachy-homelab --env-file .env` to docker compose; a bare run created a stray `homelab` project once. An accidental `ruff format` reformatted several coding-agent-service files (whitespace only); the repo does not enforce ruff format.
**Live allowance (2026-10-01, deployed, owner-tested via Telegram):** the
`claude setup-token` token is refused by `api.anthropic.com/api/oauth/usage`
(HTTP 403, inference-only scope), so the owner pastes a full-login
`.credentials.json` (from a separate `CLAUDE_CONFIG_DIR` login) into the
operator UI's "Claude account usage" card (credential name
`claude-code-account`, allowed in `reachy_hub.coding_agent`).
`ClaudeCodeProvider.live_allowance` refreshes it (rotating refresh token,
persisted before use, lock-guarded) and `GET /providers/{p}/allowance` prefers
it (`source: "live"`), falling back to CLI-reported windows on any error.
Refresh URL/client id were read from the pinned CLI binary. If the figures
vanish, check coding-agent-service logs for "Live allowance unavailable".

Operator UI reorganization is implemented locally, not deployed (2026-10-01).
Overview now contains monitoring; Settings consolidates configuration into six
feature tabs; Meetings has a searchable records sidebar; Chat has durable typed
web records and a conversation workspace. Records preserve the existing shared
assistant session rather than creating independent model contexts. Deployment
requires additive migration `012_web_chats` plus rebuilt images, not just a
static-file copy. See the [operator guide](docs/operator-guide.md#settings) and
[verification](docs/verification/operator-ui-2026-10-01.md). Browser, operator API,
real disposable-Postgres persistence and Ruff checks passed. The broader hub
suite has one pre-existing scripted voice-reply assertion failure, reproduced
against the original hub app. The disposable project was removed; production
services, databases and robot were untouched.


Telegram query shortcuts are implemented locally, not deployed (2026-10-01).
The [operator command list](docs/operator-guide.md#telegram-query-commands)
contains the new reads and `/help`. Core dispatches structured commands to
existing handlers; shared metadata supplies hub's startup menu registration.
96 command/conversation/Telegram fixture tests passed, including argument
isolation, private routing, and Telegram bot suffixes. No real Telegram messages,
model invocation, deployment, or robot actions were performed. Rebuild core and
hub to activate the shortcuts and menu on the running bot.


The reported Telegram session/usage reply bugs are fixed locally (2026-10-01),
not deployed: natural Claude Code session questions now reach the deterministic
handler, and usage reads include finished sessions. Replies explain the managed
session scope; status is labelled last recorded. (The in-memory history limitation
mentioned at the time is superseded by the durable store above.)
See [service reference](docs/reference/services.md) for the behavior. Regression
coverage uses the exact reported questions and an in-process service chain with
a simulated provider returning measured usage for a completed session. All 74
focused intent/service/conversation tests and Ruff passed. No live
Telegram message, model invocation, deployment or robot action was performed.


**First real Claude Code completion, live, with the owner's real
subscription (2026-10-01).** The owner registered a real Claude Pro/Max
subscription (`CLAUDE_CODE_OAUTH_TOKEN`) credential through the operator
UI and asked to actually test it. That required deliberately lifting the
no-invocation block added earlier the same session (see further down) —
`_ensure_can_invoke` now only refuses when no credential is configured at
all; a subscription session starts for real but stays read-only
(`--permission-mode plan`, a comprehensive `--disallowedTools` list, and a
real Docker `:ro` mount — previously dormant protection, now the live
protection); an API-key session is unaffected and keeps full permissions.

Turning the owner's "let's test it" into an actual successful run surfaced
three real infrastructure gaps, all found and fixed live, none related to
the guardrail itself:

1. **coding-agent-service's own container had no `docker` CLI at all** —
   every real container launch failed with `FileNotFoundError`. Fixed by
   installing the `docker-cli` package (client-only, no `dockerd`) in
   `services/coding-agent-service/Dockerfile`.
2. **No access to the host's Docker daemon even with the CLI installed** —
   fixed by mounting `/var/run/docker.sock` into the container. **This is
   a real, owner-approved security decision, not a casual default**: a
   container with that socket has host-root-equivalent reach. It's scoped
   to this one orchestrator container, not the session containers it
   spawns — 29.18's "no socket" rule is about those, not this service
   itself, whose entire job is controlling the host's Docker daemon.
3. **`restricted-network` (the default `CodingProject.allowed_network_profile`)
   was never actually provisioned** — `docker run --network
   restricted-network` failed with "network not found" even after the
   socket fix. Fixed by declaring it in
   `deploy/homelab/docker-compose.yml`'s top-level `networks:` with an
   explicit `name:` (Compose would otherwise silently prefix it to
   `reachy-homelab_restricted-network`, which the runtime's literal
   `--network` flag would never match).

With all three fixed, a real session — real `claude` CLI, real Anthropic
API, the owner's real subscription — **completed successfully**: "Hi!
There's nothing to plan here — just let me know what you'd like help
with." This is the first real completion this integration has ever
produced. Confirmed via `/sessions/{id}/usage` too (1581 input / 35 output
tokens, ~$0.08 equivalent — informational for a subscription, not a
charge). Test files updated to match (a subscription session now starts
200/read-only instead of being refused 403); two real-Docker tests re-run
against the actual fixed container. Redeployed live; `ruff` and the full
`services shared` suite (1013 passed) both still green afterward.

**Known follow-up, not yet done:** `DockerCLIContainerRuntime.start()`
doesn't clean up a container Docker creates-but-fails-to-fully-start
(e.g. the network-not-found failures above left a few `Created`-state
containers behind — manually `docker rm`'d this session, but nothing
automatic does this yet).

---

**Telegram status/usage questions and completion notifications
(2026-10-01, owner request: "the flow that needs to be working is that i
can use the telegram bot to ask or be informed if a session is complete or
to check the current usage").** Built before the OAuth-credential work
above, same session:

- `companion_core/coding_agent_intent.py` (deterministic, no LLM) answers
  "is my coding session done"/"what's my claude usage" in any channel,
  via a new `companion_core/coding_agent_client.py` (direct sibling HTTP
  call to coding-agent-service, same pattern as `hub_client.py`).
- `GET /coding-agents/completions/due` on companion-core — a pure,
  claim-once query (same shape as `/calendar/reminders/due`;
  `companion_core/coding_agent_notifications.py` does the claiming — in memory
  when this was written, now Postgres-backed under migration 013).
- A genuine new background loop in reachy-hub, `coding_agent_notify_loop`
  (60s interval), polls that and pushes a Telegram message via the
  existing `push_to_telegram` for anything due. Deliberately skips the
  full `interruption_policy` DND/occupied/urgency routing calendar
  reminders use — always pushes immediately, since "tell me when it's
  done" was the actual ask.
- Verified with a real asyncio task on a short interval against a fake
  Telegram API (not just the pieces in isolation) — see
  `services/reachy-hub/tests/test_coding_agent_notify.py`. Also verified
  live: created a real test session, confirmed reachy-hub's actual running
  loop claimed it via `/coding-agents/completions/due` (empty on
  re-query) without me triggering it manually.

See [docs/phase-29.md](docs/phase-29.md) (29.6/29.13 row) and
[service reference](docs/reference/services.md) for where this sits
relative to the rest of the phase. Still missing: input-needed/rate-limit
notifications (needs 29.4's hooks), and no DND-aware routing.

---

**coding-agent-service is now deployed and running live on this homelab**
(2026-10-01, by owner request "let's run the latest so we can start user
testing"): added to `deploy/homelab/docker-compose.yml` with its own
`CODING_AGENT_SERVICE_TOKEN` and `CODING_AGENT_SECRET_KEY_FILE` (a real
key generated this session at
`deploy/homelab/.env.coding-agent-secret-key.json`, 0600, gitignored, not
backed up elsewhere yet — do that before relying on any credential
surviving a lost volume), both appended to the real `deploy/homelab/.env`.
Built and started via `scripts/start-homelab.sh --build --no-browser`;
`reachy-hub` and `companion-core` were recreated to pick up the new env
vars (expected — not an error), everything else (postgres, caddy,
searxng, transcription, diarization) was left alone and confirmed
untouched. Verified: `/hub/health` and `/core/health` both `ok`, and
`/hub/providers/credentials` returns 401 (login required), confirming the
route actually reaches a real, token-configured coding-agent-service
through hub rather than 404/502/503. Also smoke-tested the full
project/session lifecycle directly against the live container (zero cost
— `provider: "simulated"`, not Claude): `POST /projects`, `POST
/sessions`, `GET /sessions/{id}/events` all worked exactly as the test
suite predicts, confirming the live deployment isn't just "built", it
actually runs. That data is in-memory only and is already gone on any
restart — no cleanup needed.

**What the owner can test right now:** log in to the operator UI and use
Settings · Accounts · Coding agent credentials — that's wired to the
browser and live. **What they cannot test yet:** starting a real Claude
Code session from the browser — there is no operator-UI or hub-proxied
path to register a `CodingProject` or start/poll a session, only raw
routes on coding-agent-service's own internal port (same `expose`-only,
no `ports:`, pattern every other homelab service uses — reachable from
the host only via `docker exec <container> ... /usr/local/bin/python3`
inside the Docker network, not a stable localhost URL). That gap (a
project/session UI, or at minimum a hub proxy plus a documented curl
recipe) is real follow-up work, not something this session built. See
[deployment](docs/deployment.md#key-provisioning) for the key-provisioning
procedure now documented there.

Phase 29 (coding agent supervisor) was added to the roadmap this session,
and its first stage, 29.1 (contracts and session store), is now
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
2. **Hard guardrail for a real subscription credential, owner request
   2026-10-01, revised same day.** First pass restricted the real
   container to read-only/limited tools; the owner clarified the actual
   intent was narrower and more direct: don't let a real Claude Pro/Max
   subscription spend credits at all yet, regardless of file/tool access —
   only allow reading existing projects/session status. Rebuilt
   accordingly: `start_session`/`resume_session`/`send_input` now raise
   `ProviderInvocationBlockedError` (routes.py maps it to HTTP 403) before
   touching Docker, the project store, or even decrypting the secret, for
   any `CLAUDE_CODE_OAUTH_TOKEN` credential. No container is created at
   all — confirmed via `runtime.list_by_session()` returning empty after a
   blocked call, both in the fixture suite and against the real Docker
   daemon. Listing/reading projects, sessions, events and usage is
   completely unaffected, since those never call this adapter's invoking
   methods. The original read-only layer (`ContainerSpec.read_only_mount`
   → a real `:ro` bind mount, confirmed twice by an actual blocked write
   including via `docker exec` into a live `claude` container; a
   `--disallowedTools` list — confirmed live to be what actually restricts
   tools, since `--allowedTools` alone did **not** restrict anything in the
   same test, despite its help text implying it should; `--permission-mode
   plan`) is kept in `_build`, not deleted, as dormant defense-in-depth for
   whenever the invocation block is deliberately lifted — it is currently
   unreachable in practice since the block above stops a subscription
   credential before `_build` ever runs, and a dedicated test exercises it
   directly against a real container so that dormant path stays proven.
   None of this is a runtime toggle; lifting the invocation block needs a
   deliberate future code change once the integration has actually
   completed a real task successfully with an API key. A pay-per-use API
   key session is unaffected throughout. See `claude_provider.py`'s module
   docstring for the full reasoning and exactly what was tested vs.
   assumed.

Nothing wires coding-agent-service's *session* lifecycle into
companion-core or reachy-hub yet (29.6/29.7 — only the credential routes
reach the browser so far), there is no hook-based mid-task
`WAITING_FOR_INPUT`/`WAITING_FOR_PERMISSION` detection (29.4), and it is
not in `deploy/homelab/docker-compose.yml` — all deliberately deferred to
their own stages per
[docs/phase-29.md](docs/phase-29.md#2929--implementation-sequence).
44 coding-agent-service tests exist (39 pass by default; the 5 real-Docker
ones are opt-in via `CODING_AGENT_DOCKER_TEST=1` and all pass given the
built image, including the guardrail checks above), plus 4 reachy-hub
tests (`test_coding_agent_credentials.py`) and one Playwright test
(`coding_agents.test.cjs`, run externally — Playwright/Chromium is not
installed in a default dev shell). Full `services shared` suite (996
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

0. Phase 29 is now live on the homelab (see Current work) —
   `CODING_AGENT_SECRET_KEY_FILE` is already set, so a credential entered
   through the operator UI now survives a restart. The actual next step is
   the owner logging in and using the Settings · Accounts · Coding agent
   credentials card for real: the subscription credential is already
   registered and invokes read-only sessions (the "cannot invoke" note that stood
   here was superseded 2026-10-01; an API key is optional, see the phase-29
   revision), and registering a project against a real test repository, since nothing in
   this codebase has a route to create a `CodingProject` from the operator
   UI yet — only `POST /projects` on coding-agent-service directly (no hub
   proxy for project/session management exists, just credentials). That
   gap — an operator-UI or at least a documented curl path to register a
   project and start/poll a session — is probably the most useful next
   build step, ahead of 29.4 (Claude hooks) or a 29.14 poller. The Postgres store (29.27)
   is built but needs deploying with migration 013 (see Current work).
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
