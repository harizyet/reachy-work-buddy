# reachy-work-buddy

Office work companion built on Reachy Mini: a homelab reasoning/session
control plane plus a Reachy-side embodiment service, decoupled so the robot
stays expressive even when the homelab is unreachable.

- [AGENTS.md](AGENTS.md) — instructions for coding agents working in this repo.
- [docs/plan.md](docs/plan.md) — full technical plan, roadmap, release targets.
- [docs/adr/](docs/adr/) — binding architecture decisions.
- [docs/jarvis-baseline.md](docs/jarvis-baseline.md) — Phase 1 reference baseline from the upstream Jarvis project.
- [shared/models/](shared/models/) — cross-service data contracts (`AgentSession`, `AgentResponse`, `MemoryRecord`, `DocumentChunk`, `EmbodimentCommand`).
- [shared/protocols/](shared/protocols/) — HTTP route contracts shared between services.

## Features

What the system can actually do today (Phases 0-15; see Status below for
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
- **Remembers work facts, not just follow-ups** — say "remember that X"
  and recall it later with "do you remember X"; the reply surfaces only
  the matching fact, with provenance and a sensitivity classification
  attached, never a dump of the surrounding conversation.
- **Answers from your own documents** — ingest a document and ask about it
  conversationally; the answer always names which document (and section,
  when the document has headings) it came from, real semantic search, not
  a keyword grep.
- **Email drafting with a real approval gate** — draft a reply
  conversationally, and it genuinely cannot be sent until you explicitly
  approve it; a real SMTP send only happens after that, never before.
- **Destructive actions require text confirmation, never voice** —
  forgetting a memory (or anything destructive added later) only *asks*
  for confirmation; confirming it by voice is refused outright, by design,
  not by prompting. Bulk/mass-destructive actions ("delete everything")
  have no confirmation path at all — blocked unconditionally.
- **Every destructive action can be undone** — forgetting a memory is a
  soft delete you can restore; sending an email queues for ~10 minutes
  with a cancel window before it actually goes out.
- **Call Reachy over WebRTC** — a real-time private audio call from a
  browser/PWA, push-to-talk, with Reachy's real embodiment visibly
  listening, thinking, and speaking in step with the call — the reply
  audio only ever plays back to your earbuds, never through Reachy's own
  speaker.
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

Phases 0-15 are done:

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
- Phase 12: work memory. companion-core gets a `MemoryStore` (`memory/`,
  same Postgres-backed pattern as calendar/tasks) storing `MemoryRecord`s
  (profile/working/episodic) with provenance (`source`), a sensitivity
  classification (reusing `Privacy` from Phase 9 rather than a duplicate
  enum — the two were byte-for-byte identical), and an optional expiry
  enforced at read time, no background job (same scope discipline as
  calendar reminders). "remember that X" captures a fact conversationally,
  same agent-actionable pattern as Phase 11 tasks; "do you remember X" /
  "what do you remember about X" recalls it — a targeted `MemoryStore`
  query, structurally separate from the per-session conversation
  transcript, which is what actually satisfies the exit criterion
  ("recalled later without transcript dumping") rather than just being a
  claim about it. Verified live through the real deployed Caddy stack: a
  fact recorded conversationally, interleaved with unrelated turns and a
  second unrelated fact, was recalled later with only the matching fact in
  the reply — and it survived a `companion-core` restart via Postgres.
- Phase 13: RAG. companion-core gets a `DocumentStore` (`rag/`) — document
  ingestion (`rag/chunking.py` splits on markdown headings for section
  provenance and packs paragraphs into ~800-char chunks), local embeddings
  (`rag/embeddings.py`, a small sentence-transformers model — no cloud
  embeddings key was available, same graceful-degradation pattern as Phase
  8's local STT/TTS), and Postgres + pgvector for storage/similarity search
  (docs/plan.md §8 names pgvector as the starting vector store; the
  homelab Postgres image switched from `postgres:16-alpine` to
  `pgvector/pgvector:pg16`). "search docs for X" / "what do the docs say
  about X" answers conversationally from real semantic retrieval, and the
  reply always names the source document (and section, when the document
  has headings) — the exit criterion, "Answers identify their supporting
  document/section/page where available" (no `page`: nothing here ingests
  PDFs). Verified live through the real deployed Caddy stack: two
  documents ingested, a time-off question correctly retrieved the Vacation
  Policy chunk (not the Expense Policy one) with its section named, and
  the same data survived a `companion-core` restart via Postgres. Getting
  there took two real-infrastructure-only bugs a passing test suite never
  caught: an uncommitted `CREATE EXTENSION` left pool connections in
  status INTRANS, and a bare vector query parameter needed an explicit
  `::vector` cast or Postgres tried to match it against `double precision[]`
  instead.
- Phase 14: email. companion-core gets an `EmailStore` (`email/`) —
  received messages seeded through an operator API (no external inbox sync
  available, same no-external-sync honesty as calendar) and drafts with an
  approval-gated `status`. "draft email to X about Y" creates a draft
  conversationally; "approve draft X" moves it from `draft` to `approved`;
  "send draft X" only dispatches if it's already `approved`. The exit
  criterion ("No code path sends mail without approval gate") is a
  structural property: only one function anywhere in this codebase ever
  calls a sender (see ADR 0011 below for what it became), and it always
  checks approval status first — both the conversational path and the
  direct API go through it, nothing bypasses it. No cloud email API key
  was available, so sending speaks real SMTP directly (`email/sender.py`)
  to a local Mailpit container in the homelab stack — a real SMTP protocol
  handshake, but no personal mailbox involved. Verified live through the
  real deployed Caddy stack: sending before approval was refused with
  nothing dispatched (confirmed against Mailpit's own message list, not
  just the HTTP response), approving then sending produced a real SMTP
  message that actually arrived in Mailpit, sending an already-sent draft
  again correctly 404/409'd, and the draft's data survived a
  `companion-core` restart via Postgres.
- ADR 0011 (destructive-action consent — a cross-cutting safety refactor
  inserted ahead of Phase 15, not itself a numbered phase): explicit
  instruction that, ahead of any future real Gmail/Outlook/live-calendar
  connector, destructive actions need a hard, structural safety mechanism.
  Two rules, enforced in one place (`companion_core/consent/gate.py`): a
  destructive action can never be requested at bulk/mass scope (`delete
  the whole mailbox` has no path to confirmation, ever — proven by a
  direct unit test, not a documented intention), and a destructive-action
  confirmation can never come from voice, regardless of what the audio
  transcribes to. `InputModality` (typed vs. spoken — distinct from
  `Channel`, which means "which device") is threaded end to end from
  reachy-hub's `/voice/turn` through to companion-core so that signal
  actually survives the trip. Memory forgetting became this codebase's
  first real user of the gate — "forget X" only requests a confirmation,
  "yes forget X" (text-only) is what actually forgets it, and forgetting
  is now a soft delete (`restore X` always works, any modality, no gate —
  undoing must never be harder than the action it undoes). Email approval
  and the send-trigger both now require text too, and "send draft X" no
  longer dispatches immediately: it queues a real send ~10 minutes out, a
  background loop is what actually dispatches once due, and "cancel send
  X" (any modality) reverts it before then. Verified live through the real
  deployed Caddy stack: a spoken ("voice") confirmation attempt through
  `/voice/turn` was refused while the equivalent typed confirmation
  succeeded; a queued email send was cancelled with nothing reaching
  Mailpit, and a separate queued send was left to actually dispatch once
  its window passed, producing a real SMTP message in Mailpit. See
  [docs/adr/0011](docs/adr/0011-destructive-action-consent.md) for the
  full design.

- Phase 15 ("Call Reachy", ADR 0012): real WebRTC audio between
  `clients/web-pwa/` (previously scaffolding-only) and reachy-hub's new
  `POST /webrtc/offer` (`webrtc.py`, `aiortc`). Push-to-talk, not
  continuous VAD — a "control" `RTCDataChannel` carries `start_talk`/
  `end_talk` around a hold-to-talk button, chosen deliberately over
  building new real-time VAD infrastructure this codebase doesn't have;
  the turn itself reuses the exact same whole-utterance STT/TTS pipeline
  and `handle_inbound_message` path every other channel uses
  (`channel=web`, `input_modality=voice` — the same ADR 0011 rule as
  `/voice/turn`: a WebRTC call can't confirm a destructive action either).
  Each turn drives the target robot's real `listening`/`thinking`/
  `speaking` behaviours (already in `Behaviour`'s vocabulary since ADR
  0003 — no reachy-embodiment changes needed) in step with the actual
  reply audio, which only ever flows over the peer connection — Reachy has
  no speaker output wired to hardware in this environment, so "no room
  audio" holds by construction. Verified live through the real deployed
  Caddy stack: a real (non-browser) `aiortc` Python client negotiated a
  real call, sent real synthesized speech, and received real non-silent
  reply audio back, with the real embodiment observed transitioning
  through listening/thinking/speaking over the same call — a real
  `replaceTrack`-vs-Opus-resampler bug (aiortc locks its encoder to the
  first frame's format) surfaced and got fixed along the way, something a
  mocked transport would never have caught. See
  [docs/adr/0012](docs/adr/0012-call-reachy-webrtc.md) for the full design
  and its one known, untested-here limitation (a browser on a different
  machine than the Docker host needs reachy-hub's WebRTC media reachable
  directly — Caddy only proxies the signaling POST, not the RTP audio).

- Phase 16 (remote telepresence, ADR 0013): reachy-hub's first real
  authentication — a shared bearer token (`REMOTE_UI_TOKEN`), fail-closed
  (an unset token 503s the whole remote-control surface rather than
  allowing unauthenticated access), gating `/robots/{id}/state`,
  `/behaviours`, `/behaviour/{name}` (ungated since Phase 4) plus two new
  routes. `POST /robots/{id}/speak` synthesizes text with the same local
  `tts.py` `/voice/turn` uses and plays it through the robot via a new
  `reachy-embodiment` `POST /audio/play` — no `companion_core_client` call
  anywhere in that path. `POST /webrtc/telepresence/offer`
  (`webrtc.negotiate_telepresence`) streams the robot's camera to the
  browser: a new `GET /camera/frame` on reachy-embodiment (polled JPEG,
  `SimulatedRobotBackend.capture_frame` — no physical camera exists in
  this environment, same standing limitation as every embodiment phase)
  wrapped into a real `CameraPollTrack` WebRTC video track. Also finally
  puts the long-unused `EmbodimentState.REMOTE` (added Phase 3, never set
  by anything until now) to work. New page:
  `clients/web-pwa/telepresence.html`. Verified live through the real
  deployed Caddy stack: unauthenticated and wrong-token requests to
  `/robots/desk-1/state` both got real 401s, a real token got a real 200;
  `POST /speak` produced a real synthesized WAV played through the
  (simulated) robot; a real `GET /camera/frame` returned real JPEG bytes;
  a real (non-browser) `aiortc` client negotiated
  `/webrtc/telepresence/offer` and received a real, non-empty 320x240
  video frame over the peer connection, with the robot's state
  transitioning to `remote` while connected and back to `idle` after the
  connection closed; and, with the `companion-core` container stopped
  (`docker compose stop companion-core`), `POST /messages` correctly 502'd
  while `/speak`, `/robots/{id}/state`, and `/behaviour/{name}` all kept
  working — the exit criterion ("control basic Reachy functions without
  Companion Core"), proven against a real stopped container, not asserted.
  A real Docker-build-only bug surfaced and got fixed along the way:
  reachy-embodiment's own image lacked `python-multipart` (needed by
  `UploadFile`/`File()`) — invisible in the test suite because
  `uv sync --all-packages`'s one shared dev venv let reachy-hub's copy of
  that dependency cover it silently, but not in reachy-embodiment's own
  `--package reachy-embodiment` Docker image. See
  [docs/adr/0013](docs/adr/0013-remote-telepresence.md) for the full design
  and its known limitations (no TLS termination at Caddy, the telepresence
  page shell itself is still served unauthenticated by `StaticFiles` even
  though every API call it makes requires the token).

See [docs/plan.md §6](docs/plan.md#6-implementation-roadmap) for the
phase-by-phase roadmap. Next up: Phase 17, interruption intelligence.

## Layout

```
services/companion-core/     reasoning/tools/memory, privacy, calendar, tasks, RAG, email, consent gate (Phases 5, 9-14, ADR 0011)
services/reachy-hub/         robot registry, sessions, routing, Telegram, voice/STT/TTS, WebRTC calls + telepresence, auth, audit, reminders (Phases 4-10, 15-16)
services/reachy-embodiment/  semantic behaviour API + presence loop + VAD + camera/audio-play (Phases 2-3, 8, 16)
clients/web-pwa/             "Call Reachy" + telepresence WebRTC PWA (Phases 15-16)
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
