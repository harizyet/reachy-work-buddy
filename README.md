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

What the system can actually do today (Phases 0-20; see Status below for
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
- **Chat in your browser** — the dashboard's Chat tab continues the same
  companion session as Telegram, even while Telegram polling is down.
  Mode/DND and active-channel indicators stay visible; the displayed
  transcript lasts only for the current tab view.
- **Owner dashboard** — log in at `/hub/ui/` to inspect component status,
  model calls/tokens/latency, and change mode, DND, or model settings.
- **Real configurable inference** — generic conversation replies can use
  a local OpenVINO Model Server or another compatible endpoint, with runtime
  configuration and persistent usage accounting. Existing tool/consent
  handlers keep their deterministic behavior.
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

Phases 0-20 are done:

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
  (at Phase 16, an unset token returned 503 on the remote-control surface
  rather than allowing unauthenticated access), gating `/robots/{id}/state`,
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
  though its protected API calls required the token at Phase 16; Phase 19
  adds owner-cookie access and replaces the browser token field).

- Docker build speed (cross-cutting, ahead of Phase 17, not itself a
  phase — same treatment ADR 0011 got): there was no root `.dockerignore`
  at all, and every service `Dockerfile` builds with context `../..` (repo
  root), so every `docker compose build` was shipping the entire repo —
  including `.venv`, ~1.6GB — to the Docker daemon as build context on
  every single build, before a single `COPY` ran. Added a root
  `.dockerignore` (mirrors `.gitignore`, plus `docs/`/`.claude/`, neither
  referenced by any Dockerfile) and `RUN --mount=type=cache,...` around
  every `uv sync` (and reachy-hub's `apt-get`), so repeated builds reuse
  previously downloaded packages instead of re-fetching them from the
  network each time — cache mounts need BuildKit (`# syntax=docker/
  dockerfile:1` + the `docker buildx` CLI plugin), which every Dockerfile
  now requires outright rather than silently degrading without it.
  Verified live: a full cold build (build cache pruned) of all three
  services took 73s; a one-line-change incremental rebuild of just
  reachy-hub, with cache mounts warm, took 21s. See AGENTS.md's Docker
  conventions section.

- Phase 17 (interruption intelligence, ADR 0014): a third pure policy
  function alongside `response_policy.py`'s two —
  `interruption_policy.is_occupied`/`decide_action`/`downgrade_for_presence`
  decide whether/how aggressively to deliver a proactive notification
  (today: calendar reminders), never *where* (that's still
  `resolve_delivery_channel`/`apply_privacy_override`, unchanged). Gates
  proactive notifications only — `/messages`/`/voice/turn` direct replies
  are never deferred. New session state: `AgentSession.dnd` (`PATCH
  /sessions/{user_id}/dnd`) and a settable `privacy_context` (`PATCH
  /sessions/{user_id}/privacy-context`, `MEETING` now usable, not just a
  dead enum value); both auto-flush a new Postgres-backed
  `notification_queue` (`GET`/`POST /notifications/{user_id}[/flush]`) the
  moment the occupied condition ends — no background poller, matching ADR
  0010's precedent. companion-core's `/calendar/reminders/due` now grades
  urgency by proximity (URGENT within 5 minutes, NORMAL otherwise) instead
  of hardcoding URGENT for everything, so the engine has real NORMAL/URGENT
  data to defer against. Verified live through the deployed Caddy stack: a
  reminder 10 minutes out with DND on came back `action="queue"`,
  nothing delivered, and showed up in `GET /notifications/hariz`; a second
  reminder 2 minutes out (graded URGENT) with DND still on came back
  `action="gesture"`, and the registered (simulated) robot's
  `/robots/desk-1/state` showed `last_behaviour: "important_notice"` —
  the real embodiment gesture actually fired, not just decided; turning
  DND back off auto-flushed the queued notification, set
  `last_interruption_at`, and the audit trail (`GET /audit/hariz`) showed
  the full `queue` -> `gesture` -> `interrupt` (flush) action history.

- Phase 18 (daily briefing, ADR 0015): `POST /briefing/{user_id}` combines
  calendar/tasks/email/reminders/project events into one prioritized list
  (`companion_core/briefing.py`'s `build_briefing`, exposed as `GET
  /briefing`) — no new storage, reuses the four stores Phases 10-12/14
  already built. Two independent acts: `Behaviour.GREETING` fires
  unconditionally on a reachable robot ("Reachy greets"), while the
  detailed text is routed through the exact same
  `resolve_delivery_channel`/`apply_privacy_override`/`decide_action`
  pipeline `check_reminders` (Phase 17) uses, forced `Privacy.WORK_PRIVATE`
  so it can never land on Reachy's speaker ("...privately delivered").
  Reminders and the day's calendar deliberately overlap (an imminent event
  is a subset of the schedule, not a separate source); the 5-minute
  urgency-proximity rule is shared, not duplicated, between
  `/calendar/reminders/due` and the briefing via
  `calendar/reminders.reminder_urgency`. Verified live through the deployed
  Caddy stack: an event 3 minutes out produced a briefing whose top item
  was that urgency-graded reminder, the registered (simulated) robot's
  `/robots/desk-1/state` immediately showed `last_behaviour: "greeting"`,
  and the response's `delivery_channel` was `telegram`, never `reachy`,
  despite Desk mode's default routing (Desk's base channel is Reachy, but
  the briefing is forced work-private); with DND on and an URGENT reminder
  present, the greeting still fired unconditionally but the detailed
  content came back `action: "gesture"` with `GET /audit/hariz` recording
  it — the occupied+URGENT carve-out from ADR 0014, reused rather than
  reimplemented.

- Phase 19: [Operator UI](clients/operator-ui/README.md) and
  [ADR 0016](docs/adr/0016-operator-ui.md). Adds single-owner password login
  with a signed HttpOnly cookie; bearer API access remains available.
  Telepresence uses that cookie, and mode/DND/privacy-context mutations now
  require authentication. The dashboard shows core/robot probes, Telegram
  configuration, LLM calls/tokens/errors/latency, session controls, activity,
  and queued notifications. Runtime provider settings are role-based,
  partially editable, masked in responses, and persisted in Postgres;
  only `local` / `local_only` is enabled in this phase. The generic reply
  branch now calls a real compatible provider, keeps user/assistant context,
  and records success/failure usage. Deterministic intent/consent handlers
  remain authoritative. Private context retains its label on generated
  follow-ups, and simultaneous turns in one session serialize.
  Verified with **278 passing tests**, Ruff, real Docker image builds,
  Postgres/Caddy, and Chromium at desktop and mobile widths: login/logout,
  mode/DND edits, live provider changes, key masking/partial updates,
  telepresence cookie access, and blocked `/core/settings/llm` bypass.
  The actual local OVMS `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` model
  returned a completion through the hub; its first measured call recorded
  60 input / 17 output tokens and about 1.5 seconds latency. Owner login,
  configuration, usage, and session settings persist through service
  recreation. Stopping core showed an unavailable component while hub and
  robot health remained visible. The verification stack used a separate Compose project and
  temporary credentials, leaving the existing OVMS container alone.

- Phase 20: [Web chat channel](docs/adr/0017-web-chat-channel.md). The
  operator UI's Chat tab reuses `Channel.WEB` / `POST /messages`, displays
  direct replies regardless of routing metadata, defaults to the configured
  Telegram user ID, and shows mode/DND/active channel. The visible transcript
  stays in the tab and clears on refresh/logout/user changes; no new history
  store or endpoint. Sends avoid duplicate pending submissions and automatic
  retries, preserve drafts after failures, and discard late logout results.
  Telegram status now reports the last successful poll, a sanitized error,
  and health requiring an error-free poll less than 60 seconds old.
  Verified with **287 passing Python tests**, clean Ruff/JS checks, a
  committed Chromium regression, and real Docker/Postgres/Caddy/OVMS browser
  flows at desktop and mobile widths. A web → Telegram-channel HTTP request
  → web conversation retained IDs/context and recalled “Teal.” A real
  invalid-token Bot API 401 marked Telegram unhealthy while chat still
  worked; the channel-continuity call was simulated through hub, not a real
  Telegram-account message. No core runtime, schema, or dependency change.

- Phase 21: [Hybrid LLM routing](docs/adr/0018-hybrid-llm-routing.md).
  Local-only, cloud-only, and local-with-error-fallback policies; a one-turn
  frontier override travels through the shared conversation path. Cloud
  settings, per-role utilization, and latest escalation reason/time are
  visible in the operator UI. An additive usage column preserves old data.
  **300 Python tests passed**, plus Chromium regression and real
  Docker/Postgres/Caddy/OVMS checks. OVMS backed both roles in live routing
  tests; the subsequent Together AI hosted-provider check verified manual
  override and error fallback (see HANDOVER.md for evidence).

See [docs/plan.md §6](docs/plan.md#6-implementation-roadmap) for the
phase-by-phase roadmap. Phases 0-21 are implemented, including hosted-cloud
verification. **Phases 22–23 are planned, not implemented:**

- Phase 22: original Jetson Nano/Reachy bring-up, real hardware backend,
  homelab and robot/companion-board Bash launchers with GUI access, and
  measured physical acceptance tests.
- Phase 23: production Gmail and Google Calendar connection settings in the
  operator UI, OAuth credential lifecycle, and read-only workflow integration.

See the [detailed plan and pass criteria](docs/phase-22-23.md). The first gate
is hardware/runtime inventory and service placement: current ADRs require
Reachy's fallback to survive a Jetson outage.

## Layout

```
services/companion-core/     reasoning/tools/memory, privacy, calendar, tasks, RAG, email, consent gate (Phases 5, 9-14, ADR 0011)
services/reachy-hub/         robot registry, sessions, routing, Telegram, voice/STT/TTS, WebRTC calls + telepresence, auth, audit, reminders (Phases 4-10, 15-16)
services/reachy-embodiment/  semantic behaviour API + presence loop + VAD + camera/audio-play (Phases 2-3, 8, 16)
clients/web-pwa/             "Call Reachy" + telepresence WebRTC PWA (Phases 15-16)
clients/operator-ui/         owner dashboard + web chat, status, LLM settings (Phases 19–20)
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

### Operator dashboard

After configuring the owner and starting the stack, open `/hub/ui/` through
Caddy for component status, LLM settings/usage, session mode/DND, and the
Chat tab. The configured Telegram user ID is selected by default so chat
continues the same session. See [web chat](deploy/homelab/README.md#web-chat-phase-20)
for transcript and access limits.
See [deployment setup](deploy/homelab/README.md#operator-dashboard-phase-19)
for `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SESSION_SECRET_KEY`, and the OVMS
host-networking override. The Phase 19 verification stack was temporary;
its test credentials are not a permanent deployment login.

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
