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

**Phases 0-20 are done.** Last completed: **Phase 20 — Web chat channel**.
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
- No new schema, dependency, or core runtime changes. Phase 21 routing is
  deliberately still unimplemented.

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
  boundaries. `LLMConfig` stores `local`, reserved `cloud: null`, and
  `routing.mode: local_only` as one JSONB row in `llm_config`. Partial PUT
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

**Next up: Phase 21 — Hybrid local/cloud LLM routing.** The plan is at
`~/.claude/plans/phase-21-hybrid-llm-routing.md` (if unavailable, use
`docs/plan.md`'s Phase 21 row). Populate the reserved cloud role, expand
routing modes, and introduce role-based routing without changing the
JSONB table. “Local is insufficient” means an outright provider failure
or an explicit user choice, not an automatic LLM quality judge. A planned
per-message `force_frontier` override must be threaded through the shared
conversation path; do not invent a web-only reasoning path.

Current configuration still permits only `local` and `local_only`, with
`cloud: null`. Phase 19/20 ADRs and implemented code supersede the earlier
planning files. Neither phase requires deleting a current Phase 18 volume:
Phase 19 added new tables; Phase 20 added no schema. Earlier missing-column
caveats remain relevant only to older volumes.

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

The latest evidence above is from the Phase 20 implementation session.
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
