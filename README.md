# reachy-work-buddy

Office work companion built on Reachy Mini: a homelab reasoning/session
control plane plus a Reachy-side embodiment service, decoupled so the robot
stays expressive even when the homelab is unreachable.

- [AGENTS.md](AGENTS.md) — instructions for coding agents working in this repo.
- [docs/plan.md](docs/plan.md) — full technical plan, roadmap, release targets.
- [docs/adr/](docs/adr/) — binding architecture decisions.
- [docs/jarvis-baseline.md](docs/jarvis-baseline.md) — Phase 1 reference baseline from the upstream Jarvis project.
- [shared/models/](shared/models/) — cross-service data contracts (`AgentSession`, `AgentResponse`, `MemoryRecord`, `EmbodimentCommand`).
- [shared/protocols/](shared/protocols/) — HTTP route contracts shared between services.

## Features

What the system can actually do today (Phases 0-11; see Status below for
the engineering detail and live-verification evidence behind each item):

- **Talk to Reachy** — a semantic behaviour API and a local presence loop
  keep the robot animated and idle-expressive on its own, and falling back
  gracefully (not going dead) whenever the homelab is unreachable.
- **One conversation, any channel** — start on Reachy, continue on
  Telegram, and it's the same session: same `session_id`, same history,
  no re-introducing yourself.
- **Real voice conversations** — speak a question (as audio in), get a
  real transcription (local Whisper), a real reply, and a real synthesized
  voice reply back out, with no cloud STT/TTS key required.
- **Telegram as a first-class channel** — a real bot you can message
  directly, backed by the same session/routing machinery as every other
  channel.
- **Desk / Office / Silent / Remote modes** — tell it where you are and it
  changes *where replies go* (Reachy's speaker, your phone, a text
  channel) without touching what it says.
- **Privacy-aware routing** — sensitive or work-private content (salary,
  confidential info, calendar/schedule details) is never spoken aloud
  through Reachy's speaker, in any mode, even Desk — it's rerouted to a
  private text channel instead.
- **A calendar it can actually answer from** — ask "what's next" and get
  a real answer from real stored events; meeting reminders get checked and
  routed through the same privacy-aware policy as everything else.
- **Remembers your follow-ups** — say "remind me to X" and it's genuinely
  recorded; ask "what are my tasks" later (even after a restart) and get
  it back. Complete and search them conversationally too.
- **A full audit trail** — every routing decision (which channel, why,
  whether privacy overrode the default) is logged and queryable per user.
- **Runs for real** — one `docker compose up` brings up the whole stack
  (reasoning, hub, embodiment, Postgres, a reverse proxy) on your own
  homelab; every feature above has been verified against that actual
  deployed stack, not just unit tests.

## Architecture

The system is three independently-deployable services, not one monolith,
because each has a different failure mode, a different change cadence, and
a different place it needs to run:

```
             HOMELAB
┌───────────────────────────────┐
│         companion-core         │
│                                 │
│ reasoning, tools, memory,      │
│ RAG, calendar/email/tasks      │
└───────────────────────────────┘
        │
        │ HTTP (session_id + text only)
        ▼
┌───────────────────────────────┐
│           reachy-hub           │
│                                 │
│ sessions, channels,            │
│ robot registry, routing        │
└───────────────────────────────┘
        │
        │ HTTP (holds the network path to Reachy)
        ▼
           REACHY MINI
┌───────────────────────────────┐
│       reachy-embodiment        │
│                                 │
│ behaviours, presence,          │
│ idle/fallback, safety          │
└───────────────────────────────┘
        │
        ▼
  Reachy daemon
```

companion-core has no arrow of its own into reachy-embodiment — every
request flows straight down this chain, through reachy-hub, never around
it.

- **`reachy-embodiment`** (runs *on* the Reachy Mini, not in the homelab):
  owns everything physical — behaviours, gaze, idle animation, motion
  safety limits. It runs on the robot itself, and keeps a local presence
  loop and offline/fallback state machine (ADR 0004), specifically so the
  robot stays animated and doesn't go dead the moment the homelab's network
  is unreachable. A bug in reasoning should never be able to freeze a motor;
  a robot reboot should never require touching reasoning code.
- **`companion-core`** (homelab): owns reasoning — the LLM, tools, memory,
  RAG, calendar/email/tasks. It speaks only in `session_id` and text; it
  has no idea whether that text arrived over Reachy's mic, Telegram, or a
  phone call, and it never sends a command to a robot directly (ADR 0003).
  This is the piece most likely to change fastest (new tools, new
  reasoning strategies, swapped LLM providers) and the one making the
  priciest external calls — isolating it means iterating on reasoning can't
  destabilize the robot or the channel plumbing.
- **`reachy-hub`** (homelab): owns *how the user reaches the assistant* —
  sessions (ADR 0002), the robot registry (which robots exist and how to
  reach them), channels (Reachy, Telegram, phone, web — only Reachy exists
  today), and response routing (ADR 0006: which channel actually gets a
  reply, driven by the user's Desk/Office/Silent/Remote mode). It's the one
  service that has to know both "which network address is this robot at"
  and "which chat app did this message come from," specifically so neither
  companion-core nor reachy-embodiment has to.

The rule threading through all three, from
[ADR 0001](docs/adr/0001-service-boundaries.md): **cognition ≠ embodiment ≠
transport**. Every arrow above is plain HTTP — no shared process memory —
so any one service can be redeployed, restarted, or replaced without the
others noticing anything worse than a normal request or a graceful
degradation (this is exactly what Phase 3's offline-fallback and Phase 4-6's
live restart tests verify).

## Status

Phases 0-11 are done:

- Phase 0: architecture freeze (ADRs, shared schemas).
- Phase 1: Jarvis reference baseline — [docs/jarvis-baseline.md](docs/jarvis-baseline.md).
- Phase 2: `reachy-embodiment`'s semantic behaviour HTTP API.
- Phase 3: its local presence loop and offline/fallback state machine.
- Phase 4: homelab control plane — `companion-core` + `reachy-hub` + Postgres
  + Caddy, deployable via [deploy/homelab](deploy/homelab/) and verified with
  a real `docker compose up`. `reachy-hub` owns a Postgres-backed robot
  registry and proxies behaviour/state calls through to reachy-embodiment;
  `companion-core` reaches robots only through reachy-hub, never directly
  (ADR 0001, ADR 0003).
- Phase 5: unified cross-channel `AgentSession` — `reachy-hub` owns a
  Postgres-backed session per user (ADR 0002); `POST /messages` normalizes
  an inbound `(user_id, channel, text)` and forwards a channel-agnostic turn
  to companion-core's `POST /conversation`. Verified live, including
  through the deployed Caddy proxy: two independent clients on different
  channels (Reachy, Telegram) for the same user share one `session_id`/
  `conversation_id`, with `active_channel` switching and companion-core's
  own turn counter advancing across the switch.
- Phase 6: Desk/Office/Silent/Remote as a deterministic I/O policy (ADR
  0006). `reachy-hub`'s `response_policy.resolve_delivery_channel(mode,
  active_channel)` takes no response content as input — a structural, not
  just behavioural, guarantee that routing is decoupled from reasoning.
  Verified live: identical text sent on the same channel routed to
  `reachy`, then `phone`, then `web`, purely from `PATCH
  /sessions/{user_id}/mode` calls in between, with `session_id` unchanged
  throughout and the mode persisting across a `reachy-hub` restart.
- Phase 7: Telegram as the first external channel. A real long-polling bot
  (`reachy_hub/telegram_client.py`) feeds inbound messages through the same
  `handle_inbound_message` path `POST /messages` uses. Verified live with a
  real bot (`@reachy_buddy_bot`) and a real Telegram account: a session
  started via a simulated Reachy message, continued with a real Telegram
  message, produced the identical `session_id`/`conversation_id` with
  `active_channel` switched to `telegram` — the exit criterion, with no
  simulation involved on the Telegram side. Text only; voice notes wait for
  a follow-up now that Phase 8 has built real STT.
- Phase 8: modular speech stack. `reachy-hub` gained `POST /voice/turn`:
  real local STT (`faster-whisper`) transcribes a WAV, the text flows
  through the same `handle_inbound_message` path every channel uses, and
  real local TTS (`espeak-ng` — no cloud key available, same
  graceful-degradation pattern as Telegram) synthesizes the reply back to
  WAV. `reachy-embodiment` gained a real Silero VAD wrapper for the
  separate, latency-critical concern of live barge-in detection (not wired
  to hardware yet — no physical Reachy in this environment). Verified live
  at three levels: real STT/TTS round-tripping through real synthesized
  speech in automated tests, a running process hit with `curl` (including
  re-transcribing the WAV reply to confirm it's genuinely intelligible
  speech), and the actual Docker images on a real network through the
  deployed Caddy proxy. Getting a CPU-only `torch` build (rather than
  silently pulling ~4GB of unused CUDA packages) took real `uv`
  configuration fixes — see `AGENTS.md`.
- Phase 9: privacy/response router (ADR 0006 addendum). companion-core now
  proposes a `Privacy` classification per turn; `reachy-hub`'s
  `apply_privacy_override` — a *second* function alongside Phase 6's
  `resolve_delivery_channel`, not a modification of it — enforces that
  sensitive/work-private content can never be spoken aloud via Reachy,
  regardless of mode (including Desk, which Phase 6 otherwise always routes
  there). Every routing decision is recorded in a new Postgres-backed audit
  log (`GET /audit/{user_id}`). Verified live: a private payload stayed off
  Reachy in both Desk and Office mode, through a running process, the real
  deployed Caddy stack, and with audit entries surviving a `reachy-hub`
  restart. An existing Phase 6 test broke when this landed (its example
  text happened to match a new privacy keyword) — fixed the test's text,
  not the new behavior, since the new behavior was correct.
- Phase 10: read-only calendar (ADR 0010). companion-core gets its first
  database connection ever (previously entirely stateless) for a real,
  local `CalendarStore` — no external calendar credential was available,
  same graceful-degradation pattern as Telegram/TTS. `POST /conversation`
  now genuinely answers "what's next" from stored data, and `reachy-hub`'s
  new `POST /calendar/check-reminders/{user_id}` routes due meeting
  reminders through the *exact same* Phase 6/9 policy pipeline — no new
  routing logic, no scheduler (that's Phases 17-18's job). Verified live
  through the real deployed stack: a real event added, a real "what's
  next" answer returned, and a reminder for an imminent meeting correctly
  routed away from Reachy (Desk mode's default) because calendar content
  is work-private. Two more existing tests broke and were fixed the same
  way as Phase 9's — their example text collided with the new intent
  matcher/classifier, and the new behavior was correct both times.
- Phase 11: tasks/notes/reminders. companion-core gets a `TaskStore`
  (`tasks/`, same Postgres-backed pattern as calendar) — but unlike
  calendar's read-only-to-the-agent design, capturing a task genuinely
  *is* the agent action: `POST /conversation` recognizes "remind me to
  X"/"add task X" and calls `TaskStore.add_task` directly, no
  confirmation gate, since recording a task is low-stakes and easily
  undoable. "what are my tasks" / "complete task X" / "search tasks for
  X" round out capture/list/complete/search. Verified live: a follow-up
  recorded conversationally was retrieved in a later turn, via the direct
  API, and after a full `companion-core` restart, through both a real
  process and the deployed Caddy stack.

See [docs/plan.md §6](docs/plan.md#6-implementation-roadmap) for the
phase-by-phase roadmap. Next up: Phase 12, work memory (profile, working,
and episodic memory with provenance, sensitivity, and expiry).

## Layout

```
services/companion-core/     reasoning/tools/memory, privacy, calendar, tasks (Phases 5, 9-11)
services/reachy-hub/         robot registry, sessions, routing, Telegram, voice/STT/TTS, audit, reminders (Phases 4-10)
services/reachy-embodiment/  semantic behaviour API + presence loop + VAD (Phases 2-3, 8)
clients/web-pwa/             web/PWA client (unimplemented)
shared/models/                Pydantic data contracts shared across services
shared/protocols/             HTTP route constants shared across services
deploy/homelab/                Docker Compose: companion-core, reachy-hub, postgres, caddy
deploy/reachy/                  Reachy-side deployment (unimplemented)
docs/                            plan, ADRs
```

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — package/workspace manager used by every service here
- Docker + the Compose v2 plugin, only if you want to run the full stack
  (`docker compose version` should print a version; if it errors with
  "unknown command", see [AGENTS.md](AGENTS.md#dev-setup) for how to install
  the plugin without root)

### Install

```
git clone <this repo> && cd reachy-work-buddy
uv sync --all-packages
```

This creates `.venv/` with all three services (`companion-core`,
`reachy-hub`, `reachy-embodiment`) plus the shared `reachy-work-companion`
package installed together, since they're one `uv` workspace.

### Verify it worked

```
uv run --group dev pytest services shared
uv run --group dev ruff check services shared
uv run python -c "from shared.models import AgentSession; print(AgentSession.model_json_schema())"
```

All tests should pass without a real Postgres or Docker — they run against
in-memory/in-process fakes (see [AGENTS.md](AGENTS.md#testing-conventions)).

### Run a single service locally

Each service is a plain FastAPI app; `reachy-embodiment` needs nothing extra,
`reachy-hub` needs a reachable Postgres, `companion-core` needs `reachy-hub`'s
URL:

```
# terminal 1
uv run uvicorn reachy_embodiment.app:app --app-dir services/reachy-embodiment/src --port 8001 --reload

# terminal 2 (needs Postgres — e.g. `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pw postgres:16-alpine`)
DATABASE_URL=postgresql://postgres:pw@localhost:5432/postgres \
COMPANION_CORE_URL=http://localhost:8003 \
  uv run uvicorn reachy_hub.main:app --app-dir services/reachy-hub/src --port 8002 --reload

# terminal 3
REACHY_HUB_URL=http://localhost:8002 \
  uv run uvicorn companion_core.main:app --app-dir services/companion-core/src --port 8003 --reload
```

Each service's own README (e.g. [services/reachy-hub](services/reachy-hub/README.md))
has example `curl` calls once it's running.

### Run the whole stack (recommended)

```
cd deploy/homelab
cp .env.example .env   # set a real POSTGRES_PASSWORD
docker compose up -d --build
curl http://localhost:8080/hub/health
```

See [deploy/homelab/README.md](deploy/homelab/README.md) for the full set of
example requests (robot registration, triggering behaviours, sessions,
operating modes).
