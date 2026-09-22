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

**Phases 0-19 are done.** Last completed: **Phase 19 — Operator UI**.
See [ADR 0016](docs/adr/0016-operator-ui.md), the README Status entry, and
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
  still reports Telegram **configured**, not healthy; poll health is Phase 20.

**Verification:** 278 tests passed including the real speech/WebRTC tests;
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

**Next up: Phase 20 — Web chat channel.** Phase 21 is still planned.
The earlier Phase 19 plan is at
`~/.claude/plans/declarative-wibbling-cascade.md`; ADR 0016 and implemented
code now supersede its planning assumptions. In particular, Phase 19 adds
only new tables, so **an up-to-date Phase 18 database does not need a volume
reset**. Do not destroy user data to add these tables. Earlier phases'
missing-column caveats remain relevant to older volumes.

**Also planned (not started): Phase 20 — Web Chat Channel and Phase 21 —
Hybrid Local/Cloud LLM Routing**, both recorded in docs/plan.md's roadmap;
Phase 19's prerequisites are now implemented. Full plans:
`~/.claude/plans/phase-20-web-chat-channel.md` and
`~/.claude/plans/phase-21-hybrid-llm-routing.md` (on the machine that
planned them — docs/plan.md's Phase 20/21 rows plus this summary are
enough to reconstruct both if those files aren't available to a new
session). The one finding worth flagging up front: **Phase 20 turned out
to be mostly a frontend task**, not a backend one — `shared/models/session.py`
already has `Channel.WEB` and `reachy-hub`'s `POST /messages` is already
fully channel-agnostic (the reply text always comes back in the HTTP
response regardless of `delivery_channel`, which only ever governs
*proactive* pushes, not direct replies — see `app.py`'s own comment on
this at the Telegram poll loop). So "talk to the buddy through the
browser" needs a chat UI page and a real Telegram-health signal
(`app.state.telegram_last_poll_at`/`_error`, tracked in the existing
`telegram_poll_loop`) feeding Phase 19's `/status`, not new conversational
backend logic. Phase 21 defines "local model is insufficient" two ways
only — the local call failed outright, or the user manually says so (the
`LLMConfig.routing.mode` setting plus a per-message `force_frontier`
override, threaded through the same way `input_modality`/ADR 0011
already is) —
deliberately **not** an automatic quality judgment, which would need
another LLM-as-judge call and is out of scope, matching this codebase's
existing discipline of honest, non-speculative classifiers
(`privacy_classifier.py`, `calendar_intent.py`).

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
0016 (operator UI, owner authentication, runtime inference and utilization).
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
- The Phase 19 temporary stack and credentials were removed after testing.
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
user deployment. Phase 19 used `phase19verify` and left `ovms` untouched.

The 278-test and live-browser evidence above is from the implementation
session. The follow-up documentation pass corrected agent conventions,
authenticated API examples, stale status headings, schema-upgrade guidance,
and ADR cross-references; it made no runtime changes or new live-test claims.

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
