# HANDOVER.md

Living document. A new Claude Code session starts with **zero memory** of
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

**Phases 0-18 are done** (see README.md's Status section for full detail
and live-verification evidence per phase). Last completed: **Phase 18,
"Daily briefing"** — `companion-core`'s new `briefing.py` (`build_briefing`,
exposed as `GET /briefing`) composes calendar/tasks/email/reminders/project
events (project events = recent `project_scope`'d episodic memory, the
honest existing stand-in — no dedicated "project events" store exists)
into one prioritized list, pure composition over the four stores Phases
10-12/14 already built, no new storage. `reachy-hub`'s new
`POST /briefing/{user_id}` is the one caller: it fires `Behaviour.GREETING`
unconditionally on a reachable robot ("Reachy greets"), then routes the
detailed text through the *exact* same `resolve_delivery_channel`/
`apply_privacy_override`/`decide_action`/`downgrade_for_presence` pipeline
Phase 17's `check_reminders` uses, forced `Privacy.WORK_PRIVATE` so it can
never land on Reachy's speaker ("...privately delivered") — reusing
Phase 17's interruption engine exactly the way ADR 0014's Consequences
section said this phase would. An imminent event legitimately appears
twice (once as an urgency-graded `REMINDER`, once as part of the full-day
`CALENDAR` schedule) — deliberate, not a bug; see
[docs/adr/0015](docs/adr/0015-daily-briefing.md). Verified live through the
deployed Caddy stack: an event 3 minutes out produced a briefing whose top
item was that urgent reminder, `/robots/desk-1/state` immediately showed
`last_behaviour: "greeting"`, `delivery_channel` was `telegram` (never
`reachy`, despite Desk mode); with DND on and that URGENT reminder still
present, the greeting still fired but the detailed delivery came back
`action: "gesture"`, recorded in `GET /audit/hariz` — the same
occupied+URGENT carve-out ADR 0014 already established, not new logic.

**Next up: Phase 19 — Operator UI** (added to docs/plan.md's roadmap table
in this session; not started, planned but deliberately not yet
implemented — the user asked to plan-and-record only this round). Full
plan is in this session's approved plan file
(`~/.claude/plans/declarative-wibbling-cascade.md` on the machine that
planned it — if that file isn't available to a new session, docs/plan.md's
Phase 19 row plus the summary below is enough to reconstruct it). Two load-
bearing findings from planning this phase, both worth re-checking before
writing code in case something changed in between:

- **There is still no real LLM anywhere in this codebase.**
  `companion_core/app.py`'s `/conversation` fallback reply is a literal
  placeholder string (`f"(turn {n} via {channel}) heard: {text}"`) — every
  existing calendar/task/memory/email "AI" behaviour is deterministic
  keyword matching (`*_intent.py`), never an LLM call. Phase 19 is
  scoped to include a real pluggable LLM client (an `OpenAICompatibleChatProvider`
  over httpx — one implementation covers both a cloud key and a local
  server like Ollama/LM Studio, since they share the same
  `/chat/completions` shape) precisely so the new "LLM utilization"
  dashboard has genuine data, not zeros. Only the existing intent-matching
  fallback branch changes; every deterministic intent path is untouched.
- **Today's only browser auth is a shared `REMOTE_UI_TOKEN` pasted into a
  text field** (`reachy_hub/app.py`'s `require_remote_auth`,
  `clients/web-pwa/telepresence.js`'s token input + `localStorage`). Phase
  19 adds a real single-owner login (username/password, stdlib
  `pbkdf2_hmac` hashing — no new dependency for that part — plus a signed
  session cookie via `itsdangerous`, the one new third-party dependency
  this phase needs). `require_remote_auth` is *extended*, not replaced:
  bearer token still works, session cookie is a second accepted path, so
  nothing depending on `REMOTE_UI_TOKEN` today breaks. Session-mutation
  routes that are currently wide open (`PATCH /sessions/{user_id}/mode`,
  `/dnd`, `/privacy-context`) get gated behind this for the first time —
  expect to touch a lot of existing `test_app.py` call sites when that
  lands, the same kind of bulk test update Phase 16 already did once for
  `/robots/*`.

New static dashboard planned at `clients/operator-ui/` (plain HTML/JS, no
framework — matches `clients/web-pwa/`'s existing convention), served by
`reachy-hub` at `/ui`. New companion-core storage planned: `llm_settings`
(single row, api key never returned unmasked, stored plaintext — no
encryption-at-rest precedent exists in this codebase to build on, and
inventing one was explicitly scoped out) and `llm_usage_log`. New
reachy-hub storage planned: `users`. All three are net-new Postgres tables
— same "needs `docker compose down -v` against a pre-Phase-19 volume"
caveat as every prior phase's schema addition once this actually lands.

**Postgres schema-addition caveat (no migration framework yet, same as ADR
0010's precedent):** Phase 17 added `dnd`/`last_interruption_at` columns to
`sessions`, an `action` column to `audit_log`, and a whole new
`notification_queue` table. `CREATE TABLE IF NOT EXISTS` does not retrofit
columns onto an already-running dev Postgres volume — a session continuing
against a pre-Phase-17 volume needs `docker compose down -v` before the new
columns/table exist. Confirmed clean in this sandbox because the volume
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
the detailed content, adds an unconditional greet gesture on top).
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

- `docker compose` (v2 plugin) is not preinstalled here. Install without
  root:
  ```
  mkdir -p ~/.docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
    -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose
  ```
- `docker buildx` is *also* not preinstalled here, separately from
  compose above — discovered while optimizing build speed (see AGENTS.md's
  Dev setup section for the install command). Every `Dockerfile` now
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
- Phase 16: `REMOTE_UI_TOKEN` in `.env` enables the remote-control surface
  (`/robots/*`, `/webrtc/telepresence/offer`, `/robots/*/speak`) — unset
  means every one of those 503s. Needed on **both** `reachy-hub` and
  `companion-core` (companion-core's `/debug/robots/...` proxy needs the
  same shared value — see `hub_client.py`).

## Known pre-existing issues (not yet fixed, found during later-phase live testing)

- **Telegram poll loop starts even with an unset token.**
  `docker-compose.yml`'s `TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:-}`
  always sets the container's env var to an empty string when unset in
  `.env` (Compose substitution, not "leave unset"). reachy-hub's
  `owns_telegram_client = telegram_client is None and telegram_bot_token
  is not None` treats `""` as "a token was provided" (empty string is not
  `None`), so it starts polling `https://api.telegram.org/bot/getUpdates`
  and fails/retries forever, logging warnings. Harmless (doesn't block
  anything, doesn't affect other features) but noisy in `docker compose
  logs reachy-hub`. Found live-testing Phase 15, not yet fixed — low
  priority, but worth a one-line fix (`os.environ.get("TELEGRAM_BOT_TOKEN")
  or None`, or check `not telegram_bot_token` instead of `is not None`)
  next time you're touching `reachy_hub/app.py`'s Telegram setup.

## Live verification workflow (established pattern, every phase)

Tests passing is necessary but not sufficient — see AGENTS.md's
"Verifying claims" section for why (several real bugs only ever surfaced
running live infrastructure, not from the test suite). Every phase in this
project has been verified via:
```
cd deploy/homelab
cp .env.example .env   # if not already present; set a real POSTGRES_PASSWORD
docker compose up -d --build
# ... exercise the feature via curl / a real client, through Caddy on :8080 ...
docker compose down -v   # clean up when done — do this every time
```
Background the `docker compose up -d --build` call if it might exceed a
tool timeout (it regularly does when pulling new base images/deps), and
wait for the completion notification rather than polling.

## Conventions this file won't repeat (see AGENTS.md for all of them)

- `--import-mode=importlib` + no `__init__.py` in service `tests/` dirs.
- Every new companion-core store needs to be injected into
  `services/companion-core/tests/test_app.py`'s `make_chain` **and** the
  three reachy-hub test wrapper files (`test_app.py`, `test_telegram.py`,
  `test_voice.py`) — this has bitten every phase that added a new store;
  it'll bite the next one too if forgotten.
- `uv.lock`/`[tool.uv.sources]` gotchas for GPU-adjacent or CPU-only
  packages (torch, etc.) — read AGENTS.md's "uv dependency conventions"
  before adding any ML/heavy dependency.
- Commit messages end with
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` (or whatever
  the current system reminder specifies — check it fresh each session,
  attribution conventions can change).
