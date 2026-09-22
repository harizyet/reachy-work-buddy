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

**Phases 0-15 are done** (see README.md's Status section for full detail
and live-verification evidence per phase). Last completed: **Phase 15,
"Call Reachy"** — real WebRTC audio between a PWA (`clients/web-pwa/`) and
`reachy-hub`, committed as `5003116`.

**Next up: Phase 16 — Remote telepresence** (docs/plan.md row: "Camera/
status/manual behaviours/speak-through-robot via secure remote UI." Exit
criterion: "Overseas user can control basic Reachy functions without
Companion Core.") Not started.

ADRs on record: 0001 (service boundaries), 0002 (agent session), 0003
(embodiment command API), 0004 (offline fallback), 0006 (response
routing), 0010 (calendar), 0011 (destructive-action consent — voice can
never confirm a destructive action, bulk-destructive actions are always
blocked, email sends are delay-queued with an undo window), 0012 (Call
Reachy WebRTC — push-to-talk, not continuous VAD). Note: 0005, 0007-0009
don't exist as separate ADRs — those phases didn't need one.

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
