# Services and API reference

This is the implementation map. Binding ownership and behavior decisions
live in [ADRs](../README.md#architecture-decisions); request/response schemas
come from each running FastAPI application's `/docs` and `/openapi.json`
and the checked-in [shared models](../../shared/models/) /
[route contracts](../../shared/protocols/). API paths below are service-local;
Caddy prefixes hub with `/hub` and core with `/core`, subject to the
[access restrictions](../deployment.md#network-and-access-boundaries).
For startup/tests use [development](../development.md), and for worked
requests use [workflow examples](workflow-examples.md).

## companion-core

[Source](../../services/companion-core/src/companion_core/) owns reasoning,
intent handlers, tools, calendar/tasks/email, durable work memory, RAG,
consent, inference settings, and usage. It never drives raw joints or owns
browser/channel transport. Debug robot calls go through hub.

| Surface | Purpose |
|---|---|
| `POST /conversation` | Session/conversation IDs, opaque channel, text, input modality, optional `force_frontier`; returns reply, turn count, privacy |
| `POST /calendar/events` | Operator seeding, not agent calendar writes or external sync |
| `GET /calendar/events`, `/calendar/next`, `/calendar/free-busy`, `/calendar/reminders/due` | Read-only calendar; free/busy exposes blocks rather than event details |
| `GET /calendar/events` (`include_cancelled`, `occupying`), `GET/PUT/DELETE /calendar/feed`, `POST /calendar/feed/refresh`, `PUT/DELETE /calendar/overrides`, `GET /calendar/meeting-reminders` | [ADR 0035](../adr/0035-read-only-ics-calendar-and-meeting-reminders.md): the read-only ICS feed (`calendar/feed.py`, `ics.py`, `safe_fetch.py`, `classify.py`), events carrying `classification`, `status`, `all_day`, `event_key`, `remind`; the feed URL is write-only. The hub proxies them for the owner session as `/calendar-feed`, `/calendar-feed/refresh`, `/calendar-feed/overrides`, `/calendar-feed/reminders`, `/calendar-feed/events` |
| `GET`, `POST /notes`; `PUT`, `DELETE /notes/{id}` | Owner notes. A note has an optional `tag`, its folder path under All Notes (`Projects/Project StarWars/Finance`), normalised by `shared/models/note_tag.py` (422 when over 5 levels or 60 characters a level; `All Notes` alone or blank means none). `PUT` changes the tag only when the request names it (`null` clears it), so a client that does not know tags keeps each note's folder; the hub passes the same body. `q` also matches the tag. Folders are derived from the notes' tags: there is no folder endpoint. Migration 030. |
| `GET`, `POST /tasks`; `POST /tasks/{id}/complete`; `GET /tasks/search` | Capture, list, complete, search follow-ups. `POST /tasks`, `/notes`, `/documents` and `/reminders` (and the `POST /meetings` form) take an optional `sensitivity` (default `work-private`) and, except for reminders, `project_scope` (default none = unscoped); editing never changes them (Phase 44A, migration 026). |
| `GET /notepad-processing/config`; `GET`, `POST /notes/{id}/processing`; `POST /notepad-processing/jobs/{id}/retry`; `GET /notepad-proposals`; `POST /notepad-proposals/{id}/accept`, `/dismiss`; `GET /notes/{id}/meeting-links`; `PUT /notes/{id}/meeting-links/{meeting_id}` (core only when `NOTEPAD_PROCESSING_ENABLED`, else 404; hub proxies the same paths for the owner session with CSRF, never a bearer) | Phase 49 ([phase-49](../phase-49.md)): optional processing of a saved note. `POST …/processing` snapshots the note (and, with `include_meetings`, its confirmed linked transcripts) and queues a job; a bounded runner asks the local model for JSON and a deterministic validator keeps only proposals whose quoted evidence is really in a source. Proposals are not tasks: `accept` (optionally edited) creates the task or reminder once under an id derived from the proposal, with a provenance row and the existing receipt; `dismiss` creates nothing. Meeting links are suggestions (from the meeting's occurrence time) until the owner confirms them. Migration 029; `deploy/homelab/rollback-029.sql`. |
| `GET /meeting-analysis/config`; `GET`, `POST /meetings/{id}/analysis`; `POST /meeting-analysis/runs/{id}/retry`; `GET /meeting-analysis/items`; `POST /meeting-analysis/items/{id}/accept`, `/dismiss`; `GET /meeting-analysis/provenance/{record_id}` (core only when `MEETING_ANALYSIS_ENABLED`, else 404; hub proxies the same paths for the owner session with CSRF, never a bearer) | Phase 31 ([phase-31](../phase-31.md)): owner-requested analysis of a finished meeting. `POST …/analysis` snapshots the numbered transcript and queues a run; a bounded runner (Phase 49's) asks the local model per chunk for JSON and a deterministic validator keeps only decisions, open questions and action candidates whose evidence is a quote really inside the cited segment (timestamps, speaker label and text come from the snapshot, never the model); an action becomes a task only through `accept` (idempotent, derived task id, existing receipt), and the item row is the provenance. Only an action the owner has confirmed reaches the Phase 44 index (a model-generated `meeting_minutes` entry, locator `analysis:<id>`); decisions, open questions and pending actions are unreviewed and never do. Code in `companion_core/meeting_analysis/`; tables `meeting_analysis_runs`/`meeting_analysis_items` (migration `032`) |
| `GET`, `POST /memories`; `GET /memories/recall` | Durable targeted work-memory retrieval, separate from transcript |
| `POST /memories/{id}/request-forget`, `/forget/confirm`, `/restore` | Text-confirmed soft deletion and undo |
| `GET /brain/summary`, `/brain/nodes`, `/brain/nodes/{type}/{id}`, `/brain/edges` | Phase 47D read-only Brain view over the source adapters (owner principal from config, private/non-sensitive ceiling, whole-record withholding, keyset pagination, edges always empty today). reachy-hub proxies the same paths, owner session only, no-store `/brain/edges` returns `derived_from` edges (accepted task or reminder -> originating note, from the Phase 49 provenance row; both ends must be requested and visible; id `derived_from:<proposal id>`); `/brain/summary` counts the same edges. Readable whether or not `NOTEPAD_PROCESSING_ENABLED` is on. |
| `GET`, `POST /documents`; `GET /documents/search` | Operator ingestion and document/section retrieval |
| `GET`, `POST /emails/received`; `GET`, `POST /emails/drafts` | Seeded inbox and deterministic drafts, no production mailbox sync yet |
| `POST /emails/drafts/{id}/approve`, `/send`, `/cancel-send` | Text approval/send, delayed dispatch, cancellation |
| `GET /briefing` | Prioritized briefing items for hub's delivery engine |
| `GET/POST /stations`, `DELETE /stations/{id}` (core); `POST /audio/stop` (embodiment) | Phase 38.3: owner-saved TuneIn stations (only the TuneIn guide id is stored; the stream URL is resolved at play time by the hub's `alarm_audio.py`, SSRF-guarded per hop, direct MP3/AAC only); `/audio/stop` silences the robot speaker |
| `GET /sweep`, `POST /sweep/{index}`, `POST /sweep/home` (reachy-embodiment) | Phase 38.2 room-occupancy sweep: five fixed body-yaw stops, on by default, `PRESENCE_SWEEP_ENABLED=false` turns it off; a stop returns a JPEG; 409 when disabled, during a conversation or remote control. Used only by the hub's `occupancy.py` (face detection in memory, only a boolean leaves it) |
| `GET/POST /alarms`, `PATCH /alarms/{id}`, `GET /alarms/due`, `POST /alarms/{id}/delivery`, `DELETE /alarms/{id}` | Phase 38.1 ([ADR 0027](../adr/0027-alarms-and-presence-gated-delivery.md)): alarms stored in the planner store (table `alarms`, migration 015; `volume` 10-400 percent gain, migration 016, applied by the hub to the WAV before it is played); `due` claims each alarm once like `/reminders/due`; `DELETE` cancels a scheduled or finished alarm; migration 024 adds `repeat` (weekdays 0 = Monday … 6 = Sunday; empty rings once) and `enabled`: `POST` takes either `due_at` or a clock `time` ("HH:MM", persona time zone) plus `repeat`, `PATCH` changes only the fields sent (label, time, repeat, station, volume, enabled), `due` skips disabled alarms and re-arms a repeating alarm for its next day while returning the one that rang; `delivery` records what the hub did |
| `GET /receipts`, `GET /receipts/pending` (core) | Phase 39 ([ADR 0028](../adr/0028-persona-responses-and-action-receipts.md)): authoritative action receipts (table `action_receipts`, migration 018) recorded by deterministic handlers and alarm delivery; `pending` claims each notify-flagged receipt once and returns the Telegram `text` built from its fields; `list` is newest first, capped at 500. Simple acknowledgements are worded by `persona/render.py` per tone |
| `GET /planner/receipts` (hub) | Phase 39.6: owner-cookie proxy to core `/receipts` for the Activity tab; the hub `receipt_notify_loop` pushes pending receipts to Telegram |
| `DELETE /meetings/{id}`, `POST/DELETE /meetings/{id}/outputs/{summary\|minutes}`, `POST /meetings/{id}/outputs/{kind}/deep`, `context_meeting_id` on `POST /conversation` and `/messages` (core; hub proxies the same) | Phase 43 ([ADR 0032](../adr/0032-meeting-outputs-and-context.md)): delete a meeting and its recording; model-written summary and minutes stored with the tier that wrote them; a meeting attached to a chat turn (local model only unless the frontier model is chosen), with deterministic web search for outward-looking questions. Reply carries `context_meeting` and `web_search` sources. |
| `GET /deep-review/info`, `GET /deep-review/current`, `GET /deep-review/{id}`, `POST /meetings/{id}/corrections/deep-review` (core; hub proxies the same paths) | Phase 42C: a background review on the larger local model through the model manager; Reachy is unavailable while it runs; Telegram notices come from `deep_review.*` action receipts. See [Phase 42C](../phase-42.md#phase-42c-deep-local-review). |
| `GET /state`, `POST /tier/activate`, `POST /tier/restore`, `GET /transitions`, `GET /metrics`, `GET /health` (model-manager, 127.0.0.1:8090, host process) | Phase 42B ([ADR 0031](../adr/0031-three-tier-local-model-escalation.md)): owner-token-protected lifecycle control of the local vLLM tiers, both served as `reachy-local`; manual only. See [services/model-manager](../../services/model-manager/README.md). |
| `POST /speech` (hub operator route, owner login/token + CSRF) | `{text}` (1-3000 chars) → `audio/wav` in Reachy's own voice: the same local TTS and `spoken_text` cleaning the robot's replies use. The Android Talk screen plays replies with it and falls back to the phone's voice on `503`. |
| `POST /speech/stream` (same auth) | Same body and cleaning; the reply is split into sentences (`tts.speech_chunks`) and returned as raw 16-bit mono PCM (`audio/L16`, rate in `X-Sample-Rate`), each sentence sent as soon as it is made. The first sentence is synthesized before the response starts, so an engine failure is a clean `503`; a later failure ends the stream early. The Android Talk screen and voice mode use it (0.15.0). |
| `Meeting` record fields (core `GET /meetings*`, hub proxies) | Beyond the speech results: `aligned_segments` (a speaker per transcript segment, migration 022), `audio_gaps` ({spans, segments, seconds} of silent stretches, 023), `description` and `title_source` (025), `speaker_names`, `transcript_corrections`, `key_terms`, `summary` and `minutes` ({text, tier, generated_at}); `audio_path` never leaves core. |
| `PUT /meetings/{id}/title`, `POST /meetings/{id}/describe` (core; hub proxies both) | Migration 025 adds `description` and `title_source` ("default", "generated" or "owner"). `PUT` takes `{title?, description?}` and marks a changed title as the owner's, which automatic naming never replaces; `POST` (`{"model": "local"\|"cloud"}`) writes both again from the transcript. The worker's `description` stage names finished meetings (default-named ones get a title and a description, owner-titled ones only a description) with a two-minute retry when the model is unavailable. |
| `GET /meetings/{id}/audio` (core; hub proxies it with the same login, streaming and passing `Range` through) | The meeting recording with single byte-range support (`206`/`416`), for the web player and the app's download-then-play. |
| `GET/POST/DELETE /meeting-terms`, `PUT /meetings/{id}/terms`, `PUT /meetings/{id}/speakers`, `POST /meetings/{id}/corrections/suggest`, `PUT/DELETE /meetings/{id}/corrections/{n}`, `POST /meetings/{id}/corrections/replace` (core; hub proxies the same paths) | Phase 41 ([ADR 0030](../adr/0030-meeting-speaker-names-and-reviewed-corrections.md)): owner speaker names and reviewed corrections stored beside the raw transcript (migration 019). `suggest` takes `{"model": "local"|"cloud"}` (default local; cloud only when the owner picks it for that request, never by routing) and stores nothing; a correction exists after `PUT`; `replace` changes every whole-word, case-insensitive match across the transcript. `/meeting-terms` is the owner's global glossary and `/meetings/{id}/terms` the meeting's own list (migration 020); `suggest` matches transcript spans against both plus attendees and speaker names, and returns `confidence`, `source`, `terms_used` and `candidates_checked`. |
| `GET/POST /planner/alarms`, `PATCH/DELETE /planner/alarms/{id}`, `POST /planner/alarms/stop`, `GET/POST /planner/stations`, `GET /planner/stations/search?q=`, `DELETE /planner/stations/{id}` (hub) | Phase 38.6: owner-cookie/CSRF proxies to core `/alarms` and `/stations` for the Alarms tab; `search` queries TuneIn with the SSRF guard; `stop` calls the in-process `AlarmDeliverer.stop()` and returns `{"stopped": bool}` |
| `GET /coding-agents/completions/due` | Phase 29.6: newly-terminal or owner-awaiting coding-agent sessions, claimed once per session turn so reachy-hub's poll loop never double-notifies; same pure-query shape as `/calendar/reminders/due` |
| `GET`, `PUT /settings/llm`; `GET /llm/usage` | Internal settings/usage; operator callers use authenticated hub proxies |
| `GET /llm/local-stats` | Live vLLM health, served model and load, read from the configured local provider's `/health`, `/v1/models` and `/metrics`; a fixed set of numbers, `status` is `ok`, `unavailable` or `not_configured` |
| `GET`, `PUT /settings/persona` | Assistant name/system prompt/location/time zone/tone (`persona_config` table; `tone` is one of default, cheery, serious, formal, casual, playful, calm, migration 017, sent as a style-only system message after the system prompt); prepended as a system message on the generic LLM branch only |
| `GET`, `PUT /settings/websearch` | Web-search grounding policy/provider (`search_config` table); Phase 24a, see below |
| `/debug/robots/...` | Debug integration plumbing, not a stable agent-tool API |

Phase 29.6: `coding_agent_intent.py` adds two more deterministic branches —
"is my coding session done"/"what's my claude usage" — answered from a
live `GET /sessions`/`GET /sessions/{id}/usage` call to coding-agent-service
(`coding_agent_client.py`), never the LLM; an unreachable service reports
that plainly rather than guessing. Usage only ever reports dimensions a
provider actually measured (29.26), across recorded sessions including terminal
sessions. Natural session questions such as "are any of my Claude Code sessions
still running?" use the same deterministic status branch; usage takes precedence
when a question also mentions sessions. Replies label status as last recorded
and limit visibility to Reachy-managed sessions. Usage is not account-wide
subscription usage. Replies show the five newest sessions plus a count of older
ones, and add the Claude allowance windows (percent used, reset time in the
persona timezone) only when Claude Code has reported them; otherwise they say
allowance is unreported. Session history is durable (Postgres, 29.27).

Typed query shortcuts are parsed into structured commands before phrase matching
and dispatch directly to the same data handlers. Shared menu/action metadata
lives in `shared/protocols/commands.py`; core owns parsing and validation, and
hub registers that menu at Telegram polling startup. Search arguments are never
reinterpreted as other intents. See the [command list](../operator-guide.md#telegram-query-commands).

The generic conversation branch uses the configured LLM after deterministic
intent/consent handlers. It has no model tool executor. The configured
persona's system prompt is prepended ahead of that turn's history only on
this branch — deterministic intent replies (tasks/calendar/email/memory)
never pass through the LLM at all, so persona wording has no effect on them.
Phase 24a's `websearch/` adds one more, optional step on the same branch,
ahead of the persona's history: `websearch.policy.should_search` (a fixed
keyword/pattern heuristic under policy `auto`, or an unconditional call
under `always`) decides whether to search; the model itself never decides
this. `websearch/rotation.py` then picks one tier per turn: the enabled
hosted provider (`brave.py`, `exa.py`, `tavily.py`) with the lowest share
of its monthly limit used, failing over on error, and the SearXNG fallback
(`searxng.py`) last (Phase 24d). `websearch/debug_log.py` keeps the last 50
searches in memory for the owner's debug view (`GET /websearch/log`). Every generic
turn also gets `persona/context.py`'s owner-local date, time and location
message, and follow-ups reuse the session's search topic
(`ConversationStore.search_topic`) only when they refer back to it. Under
Auto, closings, greetings, thanks, self-identity questions and plain
statements never search (Phase 24e). The voice correctness set and its
runner are in `eval/`. VOICE-modality turns also get
`SPOKEN_REPLY_INSTRUCTION` (short plain replies), and reachy-hub strips
citation markers and markdown before synthesis (`tts.spoken_text`).
Retrieved titles/snippets/URLs are injected as a separate, clearly
delimited, lower-authority system message — `websearch.prompt.
build_grounding_messages` — never merged into the persona/rules message, so
adversarial text inside a result cannot be mistaken for an instruction. A
search failure on a search-warranted turn still lets the LLM call proceed,
with an explicit failure notice instead of silence. Provider API keys use
the same core-owned `SecretStore` as LLM provider keys
(`SecretContext("owner", f"websearch:{provider}", "api_key")`), never a
plaintext column. See [docs/phase-24a.md](../phase-24a.md).
`commands/parser.py` (Phase 24b, superseding Phase 22b's retired
`robot_power_intent.py` phrase matcher) is one such handler: only an
explicit `/reachy standby`/`wake`/`status` command — or a registered
channel alias — parsed into a structured `Command` on any channel calls
hub's `POST /robots/standby`/`resume` through `hub_client.py` — the same
direction every other robot-touching intent already reaches hub through
(never reachy-embodiment directly, per ADR 0001) — entirely bypassing the
model, matching every other deterministic-intent precedence guarantee
here. Free-form text expressing the same intent (e.g. "turn off Reachy")
is never itself authoritative; `command_suggestion.py`'s separate,
schema-validated, fail-closed classifier may offer it only as a
suggestion — see [docs/phase-24b.md](../phase-24b.md).
Same-session turns serialize; the latest 15 user/assistant messages
(`CONTEXT_MESSAGES`, [ADR 0006](../adr/0006-response-routing.md#carried-privacy-expires-with-the-models-context-2026-09-26))
provide bounded context, reset on restart. Work-memory recall queries persistent
records, never dumps that transcript. Calendar/email replies are
work-private; generated follow-ups retain the strongest prior context label.
A generated reply is labelled from the owner's question only, never from
the model's wording, and a work word makes that question work-private only
when it refers to the owner's own data ("my next meeting", "I have a
meeting"), not in a general question ("How do I schedule a meeting on
Outlook?"). Local time and date questions are answered from the clock
(`clock_intent.py`). Generic privacy classification and intent matching
remain keyword-based, not semantic understanding.

Memory records carry source, sensitivity, optional expiry, and soft-delete
time. Expiry is enforced on reads without a cleanup worker. Recall combines
the strongest returned sensitivity. RAG uses lazy local MiniLM embeddings
(384 dimensions), pgvector in production, and injected embeddings in tests.
Chunks preserve Markdown headings and approximately 800-character paragraph
packs; no PDF parser means no fabricated page citations. Pool setup must
commit extension creation, and vector parameters need the explicit SQL cast
already in `rag/postgres_store.py`.

`consent/` is the single action gate: bulk destructive actions are blocked,
voice cannot confirm, and undo remains available. The due-dispatch loop is
the only email sender call site. See [ADR 0011](../adr/0011-destructive-action-consent.md).
Production stores use versioned Postgres; tests inject in-memory implementations.
Core owns `secrets.py` (SecretStore and keyring) and the single Alembic
`migrations/` history. Hub/core stores check schema compatibility at connect;
see [upgrade procedures](../deployment.md#schema-upgrades-and-credential-keys).

LLM merge/default/failure semantics are defined once in
[ADR 0018](../adr/0018-hybrid-llm-routing.md). Both roles use the same compatible
HTTP client, with masked settings and sanitized attempt logging. Usage window
and entry limits are independent; missing token counts remain null.

### Conversation routing and the hybrid intent router

`POST /conversation` tries handlers in a fixed order in `app.py`: slash commands, the mixed read-and-write refusal (`mixed_intent.py`), a named-record reference (`record_reference.py`: a note or meeting named with "note"/"meeting", quotes or a bare title that resolves, `parse_tentative`), calendar and alarm handlers, the task handlers (`task_intent.py`; the Phase 49 inquiry in `notepad_processing/inquiry.py`), reminders, notes, memory, documents, email and coding-agent handlers, then the final branch: command suggestion, the 44H unclaimed-action boundary (`action_boundary.py`), the 44E selective answerer, **`intent_router.py`**, and ordinary chat. Details and rules: [ADR 0033](../adr/0033-llm-assisted-read-routing.md).

| Piece | Role |
|---|---|
| `intent_router.py` | `INTENT_ROUTER_ENABLED` (default false, read at startup into `app.state.intent_router_enabled`; Compose passes it to core only). `requires_records` (deterministic need-for-evidence), `infer` (local-only classifier call, strict `Decision` schema, never raises), `execute` (runs one read handler under the turn's access). `CANNOT_PLACE` is the fixed clarification |
| `mixed_intent.py` | `detect` / `reply`: a message that starts as a read and asks for a write is refused whole, naming the verb |
| `task_intent.py` | `normalise_question`, `time_scope` (today, tomorrow, this week, next week; anything else is a limitation), ownership and topic guards on the list matchers, `format_list_reply(tasks, scope)` |
| `record_reference.py` | `parse`, `parse_tentative` (title-only), `resolve`, `find` (substring search of notes and ready meetings under the caller's access), `without_titles` |
| Reply privacy | task, reminder and note handlers label a reply by the records it names and apply the channel ceiling; a shared speaker receives `notepad_inquiry.RESTRICTED` |

## reachy-hub

[Source](../../services/reachy-hub/src/reachy_hub/) owns sessions, channels,
response routing, authentication, robot registry/connectivity, STT/TTS,
WebRTC, and static UI. It does not own reasoning policy or motor control.

| Surface | Purpose |
|---|---|
| `POST /messages`; `GET /sessions/{user_id}` | Shared session across text channels; one active session per user |
| `GET`, `POST /chats`; `GET`, `DELETE /chats/{chat_id}?user_id=…` | Authenticated durable web chat records (`DELETE` removes a chat and its saved turns, for the owner's own chat only, with a `404` otherwise; core's own reasoning context is not touched); `POST /messages` accepts optional `chat_id` to archive a typed web turn. Shared session/context remains unchanged |
| `POST /voice/turn` | Caller-upload diagnostic: multipart WAV `audio` and owner `user_id`; STT → shared conversation → WAV TTS. Owner-gated by the work-route middleware before STT; not the robot workflow and no speaker-routing check |
| `POST /webrtc/offer` | Conversational push-to-talk call; voice modality cannot confirm actions |
| `PATCH /sessions/{user_id}/mode`, `/dnd`, `/privacy-context` | Authenticated updates to existing sessions |
| `GET /audit/{user_id}`, `/notifications/{user_id}`; `POST /notifications/{user_id}/flush` | Routing decisions, queued notifications, controlled flush |
| `POST /calendar/check-reminders/{user_id}`, `/briefing/{user_id}` | On-demand proactive routing, not an automatic schedule |
| *(internal, no route — a background task)* `coding_agent_notify_loop` | Phase 29.6: polls companion-core's `/coding-agents/completions/due` every `coding_agent_notify_interval` seconds (default 60) and pushes a Telegram message via the existing `push_to_telegram` helper for anything due. Unlike the calendar reminder row above, this is a genuine always-on loop, not on-demand — and deliberately skips `interruption_policy`'s occupied/DND/urgency routing, pushing immediately every time; revisit if routine completions start interrupting something they shouldn't |
| `GET`, `POST /coding-agents/projects`; `GET`, `POST /coding-agents/sessions`; `POST /coding-agents/sessions/{id}/stop`, `/refresh`; `GET /coding-agents/sessions/{id}/events`, `/usage`; `GET /coding-agents/allowance/{provider}`; `GET /coding-agents/terminal-sessions` | Phase 29.22: owner-cookie/CSRF (or bearer) proxies to coding-agent-service for the Coding agents tab; `owner_user_id` is set server-side, not by the browser |
| `POST`, `GET /robots` | HTTP robot registry |
| `GET /robots/{id}/state`, `/behaviours`; `POST /robots/{id}/behaviour/{name}`, `/speak` | Authenticated robot proxies and direct speak-through control |
| `GET`, `PUT /robots/{robot_id}/settings/motion` | Owner-authenticated proxy for robot-local conversational animation switches; changes only between conversations |
| `POST /robots/standby`, `/resume` | Phase 22b: authenticated remote power control — parks/de-torques (`standby`) or wakes (`resume`, `wake_up` query param) every registered robot; no `{id}` in the path, loops the registry like the existing gesture-trigger helper does |
| `POST /webrtc/telepresence/offer` | Authenticated remote media/control |
| `WS /robots/connect` | Robot-token-authenticated registration/heartbeat/reconnect; also `voice_start`/`voice_stop`/`voice_state` conversation control (Phase 24c) and `wake_arm` (Phase 24g, sent after every registration); other commands still HTTP |
| `GET /robot-voice`; `POST /robot-voice/start`, `/renew`, `/stop` | Phase 24c owner controls: robots with the voice capability, the current session, its lease and recent turns |
| `POST /robot-media/voice-turn` | Phase 24c robot upload of one WAV utterance, authenticated with the robot's own credential, generation and session; returns reply WAV or 204 with `X-Voice-Turn-Outcome`, which is `continue` when the hub holds an unfinished-sounding segment (24e; `X-Voice-Segment` numbers the held turn's further segments) |
| `POST /robot-media/voice-turn/finalize` | Phase 24e: same robot credential and fencing headers, no body; answers the held turn when the robot heard no more speech in the continuation window |
| `POST /robot-voice/wake` | Phase 24g owner control (also privacy mode: disarmed = on; `/privacy on\|off` and the spoken "turn on privacy mode" use it, see the [operator guide](../operator-guide.md#telegram-query-commands)): arm or disarm "Hey Reachy" for one robot (persisted, `robot_wake_arm`); returns the overview, whose robots carry `wake_capable`, `wake_armed` and content-free `wake_counts` |
| `POST /robot-media/wake-candidate` | Phase 24g robot upload of one wake candidate WAV with the robot credential, generation and `X-Wake-Arm`; 200 with the new session ID when admitted, 204 `rejected` otherwise, 409 for a stale arm or connection |
| `POST /auth/login`, `/auth/logout`; `GET /auth/me` | Owner-cookie lifecycle; login/logout require CSRF header |
| `GET /status` | Authenticated component probes, model config/usage, Telegram polling health, default user ID |
| `GET`, `PUT /settings/llm`; `GET /llm/usage` | Authenticated core proxies; usage defaults `limit=50`, `since_hours=24` |
| `GET /llm/local-stats` | Authenticated core proxy for the web Overview "Local model server (vLLM)" card (polled every 5 s) |
| `GET`, `PUT /settings/persona` | Authenticated core proxy for assistant name/system prompt |
| `GET`, `PUT /settings/websearch` | Authenticated core proxy for web-search grounding policy/provider (Phase 24a) |

Cookie mutations require CSRF; bearer clients remain supported on existing
work/robot APIs. Phase 23 binds work-data user IDs to OWNER_USER_ID and gates
conversation, session, audit, notification, reminder and briefing HTTP routes.
Accounts/OAuth specifically require the owner session. Static assets
and historical conversation APIs retain their existing access contract;
see [deployment](../deployment.md#owner-login) and
[ADR 0016](../adr/0016-operator-ui.md). `/auth/me` is cookie-only, not a way
for bearer clients to create a browser login.

`chat_store.py` owns `web_chats`/`web_chat_turns` (migration `012_web_chats`),
with a Postgres implementation in production and an injectable in-memory store
for tests. It records text before invocation and reply/search evidence afterward;
failed or interrupted requests remain uncertain rather than being replayed.
These records are presentation history, not restored reasoning context. See
[ADR 0017](../adr/0017-web-chat-channel.md#saved-web-records-amendment-2026-10-01).

### Owner recognition

The benchmark-capture routes in `reachy_hub/owner_recognition.py` use
`enrollment_store.py` and the hub-local AESGCM `keyring.py`. All require an
owner cookie session, not the automation bearer. Mutations require CSRF;
benchmark changes also require fresh password reauthentication. Export
requires fresh reauthentication.

| Route | Purpose |
|---|---|
| `GET /owner-recognition/status` | Enable state, sample lists and byte totals |
| `POST /owner-recognition/reauth` | Confirm the owner password for five minutes |
| `PUT /owner-recognition/benchmark/enabled` | Explicit benchmark capture opt-in |
| `POST /owner-recognition/benchmark/{voice,face}/samples` | Upload a sample while benchmark mode is enabled |
| `DELETE /owner-recognition/benchmark/{voice,face}/samples/{sample_id}` | Delete a sample |
| `GET /owner-recognition/benchmark/{voice,face}/export` | Decrypt a dataset into a zip with manifest |

See [storage configuration](../deployment.md#owner-recognition-benchmark-storage)
and [operator controls](../operator-guide.md#owner-recognition-benchmark-dataset).
These captures do not supply trust evidence; the separate speaker protocol,
trust engine and sensitivity authorizer are described in
[Phase 25](../phase-25.md#implementation-sequence) and
[ADR 0024](../adr/0024-owner-recognition-trust.md).

### Response routing

Response policy first chooses by mode, then enforces privacy, then records
an audit. Direct replies are returned on the inbound channel regardless of
proactive `delivery_channel` metadata. Reminder and briefing delivery reuse
the interruption policy and queue; Phone delivery is not a working push
integration. See [ADR 0006](../adr/0006-response-routing.md),
[ADR 0014](../adr/0014-interruption-intelligence.md), and
[ADR 0015](../adr/0015-daily-briefing.md).

Telegram stores learned chat IDs separately from channel-agnostic sessions.
Poll health lives in memory and resets on restart. STT/TTS are lazy local
faster-whisper/espeak providers; `STT_MODEL` picks the Whisper model
(default `base.en`). Robot and `/voice/turn` STT is primed with
"Reachy" and the persona's assistant name (Phase 24e). WebRTC orchestration is separate from SDP
and audio tracks; playback resamples to 48kHz mono because aiortc's Opus
encoder does not adapt when tracks with different formats are swapped.

Open-palm stop (`palm_stop.py`, `PALM_STOP_ENABLED`, off) classifies the
frames a robot uploads to `ROBOT_PALM_FRAME` while its reply plays, using
MediaPipe. Frames are accepted only for the reply currently playing.

Robot voice sessions ([ADR 0023](../adr/0023-robot-voice-conversation.md),
`robot_voice.py`) are process-local, one per robot. They are bound to the
robot's connection generation and ended by logout, lease lapse, idle timeout,
maximum length or disconnect. A turn is transcribed and sent to core as
`channel=reachy`, `input_modality=voice`. It is synthesized only when
`resolve_delivery_channel` → `apply_privacy_override` →
`robot_speech_withheld_reason` (DND/meeting) all permit the robot speaker.
Before that, `turn_completeness.py` decides from fixed rules whether the
transcript sounds unfinished; if so, and the robot advertises
`voice_turn_continuation`, the hub holds it for the robot's next segment or
finalize instead of answering
([ADR 0023 addendum](../adr/0023-robot-voice-conversation.md#addendum-adaptive-end-of-turn-2026-09-25-phase-24e)).

Wake-started sessions (Phase 24g, [ADR 0023 wake addendum](../adr/0023-robot-voice-conversation.md#addendum-wake-started-sessions-2026-09-27-phase-24g)): the owner's arm is persisted by
`wake_arm_store.py`/`postgres_wake_arm_store.py` and cached by the manager.
A candidate is transcribed in memory and judged by the fixed rules in
`wake_relevance.py`. An admitted one opens a session with no owner lease,
whose turn 1 reuses the admitted request instead of transcribing again.

The HTTP heartbeat interval is 2 seconds against embodiment's 5-second
watchdog. WS connections are process-local, generation-fenced, and require
one hub worker. `ROBOT_TOKENS` provisions hashed robot credentials in memory;
startup must provision them again. WS credentials differ from operator auth.

## reachy-embodiment

[Source](../../services/reachy-embodiment/src/reachy_embodiment/) owns semantic
behaviours, independent presence, watchdog/fallback, and the robot backend.
STT/TTS and work data stay in the homelab.

| Surface | Purpose |
|---|---|
| `GET /health`, `/state`, `/behaviours` | Service/backend state and behavior vocabulary |
| `POST /behaviour/{name}`, `/heartbeat` | Semantic behavior and proof of hub liveness |
| `GET`, `PUT /settings/motion` | Runtime conversational gesture/speech-wobble switches; local motion owner rejects active conversations |
| `GET /camera/frame`; `POST /audio/play` | Frame capture and audio playback used by telepresence |

`/gaze` and `/pose` remain reserved, unimplemented contracts. `/audio/play`
was implemented in Phase 16; the old Phase 8 README's contrary claim was stale.
`RobotBackend` selects simulation by default or `reachy_daemon` explicitly;
unknown settings fail startup. An unreachable daemon reports disconnected
and does not claim real hardware. Presence checks backend connectivity
periodically without querying it on every animation tick.

The independent presence thread schedules idle behaviours in idle/disconnected
states, times out without hub heartbeats, and recovers on renewed liveness.
The real backend logs/no-ops unmapped idle movements, so simulated scheduling
does not prove physical idle animation.

`voice.py` (Phase 24c) runs the robot side of a hub-started conversation. It
opens the microphone, lets Silero VAD (512 samples at 16 kHz) delimit one
bounded utterance, closes the microphone, uploads the utterance to the hub,
then plays any permitted reply. It is half-duplex, and cancelling stops daemon
playback. It is enabled only by `VOICE_CONVERSATION_ENABLED=true`, and has not
passed physical acceptance. Audio barge-in is not implemented. Phase 24g's
`wake.py` monitors for "Hey Reachy" while the hub has armed the robot: an
Edge Impulse runner scores the microphone locally, and a candidate (the
phrase plus the request) goes to the hub for admission. See the
[ADR 0023 wake addendum](../adr/0023-robot-voice-conversation.md#addendum-wake-started-sessions-2026-09-27-phase-24g). It is not physically accepted.
When the hub turns on open-palm stop for a session, `gesture.py`'s
`HubPalmStop` uploads downscaled camera frames to the hub during playback.
When the hub answers `stop`, playback stops and the loop returns to
listening in the same session.

`motion.py` (Phase 24f) is the single local motion owner. See the
[ADR 0003 amendment](../adr/0003-embodiment-command-api.md#phase-24f-motion-ownership-amendment-2026-09-25).
`CONVERSATION_MOTION_ENABLED` and `SPEECH_WOBBLE_ENABLED` are both off by
default. Phase 24g's `WAKE_ANIMATION_ENABLED` (the sleep pose between
conversations, a silent alert pose on a detection and home on admission,
all silent gotos) is on by default and moves only
while wake listening is armed. While either 24f switch is on, a voice conversation owns motion and
`POST /behaviour/{name}` answers 409. The motion itself is not physically
accepted.

`ReachyDaemonBackend` calls daemon HTTP under `/api`. Recorded moves use the
Pollen emotions dataset. Camera frames and the microphone share one
`reachy_mini` LOCAL media client. Audio playback is upload-then-play, and
`stop_audio` calls `/api/media/stop_sound`. `stop_motion` stops the move
it last started by UUID, `goto_home` sends one bounded `/move/goto` to the
wake-up end pose, and `set_speech_wobble` switches `/api/media/wobbling/*`.
Physical camera/audio acceptance is still outstanding. Read
[bring-up evidence](../verification/phase-22-bring-up.md) before treating the
simulator's successful move lifecycle as validated real motion.

## coding-agent-service (Phase 29, planned)

[Source](../../services/coding-agent-service/src/coding_agent_service/) owns
coding-agent process/container lifecycle, provider adapters, session state,
agent events and usage observations, behind the provider-neutral contract in
[docs/phase-29.md](../phase-29.md). companion-core (not yet wired) would own
the calling intent/authorization/notification policy; this service never
reasons about owner intent itself.

29.1 (contracts and session store) is implemented: `CodingAgentSupervisor`
creates a `CodingProject`, starts/resumes/stops a `CodingAgentSession`
against a provider registry, and records normalized `CodingAgentEvent`s,
against an in-memory store and a `SimulatedProvider`.

29.2 (container runner) is also implemented: `runtime.py`'s
`DockerCLIContainerRuntime` shells out to the `docker` CLI to start a
labeled, resource-limited, non-root container with no Docker-socket mount
and no `--privileged` (29.18's defaults are baked into how a
`ContainerSpec` becomes a `docker run` invocation, not left to each
caller), and can list/inspect containers purely from their
`reachy.project_id`/`reachy.session_id`/`reachy.provider` labels — verified
against a real local Docker daemon with a fresh runtime instance
rediscovering a container a previous instance started (opt-in
`CODING_AGENT_DOCKER_TEST=1`, same pattern as companion-core's real-Postgres
tests). `reconcile.py`'s `recover_sessions` runs at startup (when the store is
durable) and reconciles each non-terminal session against Docker and its
provider; a session whose container is gone with no final result becomes
`LOST` (never `COMPLETED`), and nothing changes if Docker is unreachable.
`postgres_store.py` stores records as JSONB beside a few query columns; the
schema is core's migration `013_coding_agent`, and the service needs
`DATABASE_URL`. The runtime is not
yet wired into `CodingAgentSupervisor.start_session` — no provider actually
launches a container yet; that starts with the real Claude Code adapter
(29.3).

29.19 (credentials) was also pulled forward: `credentials.py`'s
`EncryptedFileCredentialStore` keeps provider credentials (e.g. a future
Claude Code API key) AESGCM-encrypted at rest under a key from
`CODING_AGENT_SECRET_KEY_FILE` (own key material, separate from
companion-core's keyring), behind `PUT`/`GET`/`DELETE
/providers/{provider}/credential`; the secret value is never returned once
set, only `provider`/`kind`/`last_four`/`updated_at`. Reachable from the
operator UI (see reachy-hub and operator-ui below), not an env-file
afterthought.

29.3 (Claude Code provider) is implemented: `claude_provider.py`'s
`ClaudeCodeProvider` consumes exactly that stored `claude-code` credential,
and picks the env var Claude Code actually reads based on its
`CredentialKind` (confirmed by grepping the real installed `claude.exe`
binary, not guessed): `api_key` → `ANTHROPIC_API_KEY` (pay-per-use), or
`oauth_token` → `CLAUDE_CODE_OAUTH_TOKEN` — a Claude Pro/Max subscription's
long-lived token, generated interactively with `claude setup-token` on a
machine where the owner can sign in (this container cannot do that
itself), then pasted into the operator UI's credential card. Using the
wrong variable for the stored kind would silently fail to authenticate.
`docker/claude-code/Dockerfile` builds a real image (`node:20-slim` +
`npm install -g @anthropic-ai/claude-code`, confirmed live at claude-code
2.1.197; the `node` user is uid/gid 1000, matching
`DockerCLIContainerRuntime`'s default `--user`). `start_session` assigns a
UUID via `claude`'s own `--session-id` flag and starts the container
through the 29.2 runtime, so the provider session id is known immediately
rather than parsed out of output. `inspect_session` parses the container's
real `stream-json` stdout: a `{"type":"result",...}` line's `is_error`
decides `COMPLETED` vs `FAILED`, its `usage`/`total_cost_usd` feed
`collect_usage`, and a container that stopped without ever producing a
result line is `LOST`, never `COMPLETED` (29.8). It also opportunistically
reports `RATE_LIMITED` when the log shows a `429` `api_retry` line, ahead
of 29.12's full handling. `--dangerously-skip-permissions` is never passed
— a tool call needing approval simply has nothing to approve it headlessly
until 29.4 (hooks) exists. Verified end to end on the live homelab,
2026-10-01: first against the real image with an intentionally invalid
key, then — once the owner registered a real Claude Pro/Max subscription
credential through the operator UI and asked to test it — a real session
against the real Anthropic API completed successfully. That is the first
real completion this integration has produced.

**Read-only restriction for a `CLAUDE_CODE_OAUTH_TOKEN` (real Claude
Pro/Max subscription) credential:** a no-invocation block was added
2026-10-01 (the owner's concern: starting any real `claude` invocation
spends real subscription usage the instant the model answers, and this
integration had never completed a real task) and lifted the same day once
the owner had registered a real credential and asked to test it —
`_ensure_can_invoke` now only refuses when no credential is configured at
all, for either kind. What a subscription session keeps instead, live and
confirmed rather than dormant: `--permission-mode plan`, a
`--disallowedTools` list naming every tool claude-code 2.1.197 is known to
advertise except `Read`/`Grep`/`Glob`/`WebSearch`/`WebFetch` (confirmed
live to be what actually removes tools from a real init event's `tools`
array — `--allowedTools` alone did **not** restrict anything in the same
test), and `ContainerSpec.read_only_mount` → a real `:ro` bind mount,
confirmed by an actual blocked write both via `docker run` and via `docker
exec` into a live `claude` container. An API-key session is unaffected and
keeps full default permissions — the split is deliberate: a brand-new,
just-proven subscription path stays read-only, an already-established
pay-per-use path doesn't.

Getting the first real session running live also exposed three real
deployment gaps, now fixed: coding-agent-service's own container had
neither the `docker` CLI nor access to the host's Docker daemon (now has
both — the `docker-cli` package, client-only, and a mounted
`/var/run/docker.sock`; an explicit, owner-approved exception to 29.18's
"no socket" rule, which is about the containers *this service spawns* for
a session, not this orchestrator container itself, whose whole job is
controlling the host's Docker daemon), and `restricted-network` (the
default `CodingProject.allowed_network_profile`) was never actually
provisioned as a Docker network (now is, in
`deploy/homelab/docker-compose.yml`, with its name pinned so Compose's
`reachy-homelab_` project-prefixing doesn't break the literal `--network`
flag `DockerCLIContainerRuntime` passes).

No hook-based mid-task `WAITING_FOR_INPUT`/`WAITING_FOR_PERMISSION`
detection (29.4), and no companion-core/hub path to *start* a session from
the browser — see companion-core's and reachy-hub's own sections below for
what they do reach (status/usage questions and completion notifications,
not session management).

Deployed in `deploy/homelab/docker-compose.yml` (2026-10-01): its own
container, `CODING_AGENT_SERVICE_TOKEN` shared secret,
`CODING_AGENT_SECRET_KEY_FILE` for credential persistence across a
restart (see [deployment](../deployment.md#key-provisioning)), Docker CLI
plus host socket access, and a provisioned `restricted-network`. Live and
exercised on the owner's homelab — not just health-checked.

| Surface | Purpose |
|---|---|
| `GET /health` | Unauthenticated liveness check |
| `POST`, `GET /projects`; `GET /projects/{project_id}` | The explicit registry of projects a coding agent may touch; paths are never accepted free-form from a session request |
| `POST /sessions` | Start a session against a project's configured provider |
| `GET /sessions`; `GET /sessions/{session_id}` | List/inspect durable session records |
| `POST /sessions/{session_id}/resume`, `/input` | Owner-instruction relay into a `WAITING_FOR_INPUT`/`WAITING_FOR_PERMISSION`/`RATE_LIMITED` session only; rejected with 409 otherwise |
| `POST /sessions/{session_id}/stop` | Idempotent terminal stop |
| `POST /sessions/{session_id}/refresh` | Re-checks a non-terminal session against its provider/container right now (29.3); a background poller (`CODING_AGENT_POLL_INTERVAL_SECONDS`, default 30) now does this for running sessions; no hook bridge exists yet |
| `GET /sessions/{session_id}/events` | Normalized event log for that session |
| `GET /sessions/{session_id}/usage` | Capability-gated `UsageSnapshot`; absent dimensions are unknown, never assumed zero |
| `GET /providers/{provider}/allowance` | Account allowance windows (5-hour/weekly) last reported by that provider and not yet reset (29.26); empty when none reported |
| `GET /providers/{provider}/capabilities` | `ProviderCapabilities` so a caller never assumes a metric a provider doesn't expose |
| `GET /providers/credentials`; `GET`, `PUT`, `DELETE /providers/{provider}/credential` | Owner-entered provider credentials (29.19); `PUT`/`GET` never return the secret value, only `last_four` |

All routes but `/health` require the `X-Reachy-Coding-Agent-Service-Token`
header (`shared/protocols/coding_agent.py`'s `SERVICE_HEADER`), checked with
`secrets.compare_digest` — the same shared-secret pattern as accounts'
`SERVICE_HEADER`, deliberately a separate token (29.19: agent credentials
must not fall back to another service's secret). Wire models live in
`shared/models/coding_agent.py`, used directly by companion-core's own
client (below) as well as reachy-hub's.

`reachy-hub` proxies the credential routes under owner cookie+CSRF auth
(`reachy_hub/coding_agent.py`, `reachy_hub/coding_agent_client.py` — same
shape as `reachy_hub/accounts.py`), gated on `CODING_AGENT_SERVICE_TOKEN`
being configured; the operator UI's Settings · Accounts tab has a "Coding
agent credentials" card (`clients/operator-ui/coding_agents.js`) to
set/replace/remove the Claude Code or Codex credential. **companion-core**
also calls this service directly (`companion_core/coding_agent_client.py`
— the same direct-sibling-HTTP-call pattern as `hub_client.py` and the
meeting speech sidecars, per ADR 0001): a deterministic (non-LLM) intent
(`companion_core/coding_agent_intent.py`) answers an owner's "is my coding
session done"/"what's my claude usage" question from any channel, and
`GET /coding-agents/completions/due` (companion-core's own route, a pure
claim-once query like `/calendar/reminders/due`, claims kept in Postgres) is what lets reachy-hub
push a Telegram message when a session finishes — see reachy-hub's section
below for that loop. Session *management* — registering a project,
starting/resuming/stopping a session — still has no hub/companion-core
path; only status/usage reads and completion notifications do.

## Shadow semantic router (Phase 37)

Two parts, neither authoritative. [Source](../../deploy/homelab/semantic-router/) is a standalone sidecar, not a workspace member: ModernBERT-base x3
(18 routes) on ONNX Runtime CPU, internal-only at `http://semantic-router:8012` (`GET /health`, `POST /route {"text"}` returning `route`, `confidence`,
`member_routes`, `top3`, `latency_ms`). It stores and logs nothing and holds no tool, consent or credential logic. Started only with the `shadow-router`
Compose profile (see [deployment](../deployment.md#shadow-semantic-router)).

`companion_core/shadow_router/` (`validator.py`, `extractor.py`, `shadow.py`) is the shadow pipeline. `process_conversation_turn` labels the production
branch (`production_handler`) and, after the reply is final, hands a plain-data snapshot to a bounded background queue (disabled unless
`SHADOW_ROUTER_ENABLED=true`; wrapped so nothing from it reaches the turn). It records route, production handler, extraction state, validator status and
the proposed action to a JSONL file; in the default `offline` extract mode only the router is called live. `tools/shadow_router_extract.py`,
`shadow_router_report.py` and `shadow_router_grade.py` (sheet, purge, destroy) are the offline evaluation tools. Decision: [ADR 0026](../adr/0026-semantic-routing-and-argument-validation.md);
contract, flags and retention: [shadow-router](../shadow-router.md).

## Meeting transcription (Phase 27.2)

[Source](../../deploy/homelab/transcription/) is a standalone sidecar, not
a workspace member — faster-whisper (the same library reachy-hub's
conversational `stt.py` uses, but a separate process; ADR 0001's
sibling-import ban applies here too). Started only with the
`transcription` Compose profile (see
[deployment](../deployment.md#meeting-transcription)); not part of a bare
`docker compose up`. Internal-only at `http://transcription:8011`:
`GET /health` reports load status, `POST /transcribe` takes multipart
audio (wav/flac/mp3/m4a/etc — faster-whisper's bundled PyAV decodes it,
no system ffmpeg needed) and returns `{duration_s, process_s, rtf,
language, segments: [{start, end, text}]}` in seconds.
`companion_core.meetings.speech_clients.HTTPTranscriptionClient` calls
this whenever a meeting job reaches TRANSCRIBING
([ADR 0025](../adr/0025-speech-inference-service.md)); companion-core
never imports `reachy_hub.stt` to get this capability itself.

## Meeting diarization (Phase 27.3)

[Source](../../deploy/homelab/diarization/) is a standalone sidecar, not a
workspace member — Nemotron-3-Diarization (NeMo Sortformer) with its
per-chunk network step on OpenVINO, ported from local experimentation.
Started only with the `diarization` Compose profile (see
[deployment](../deployment.md#meeting-diarization)); not part of a bare
`docker compose up`. Internal-only at `http://diarization:8010`:
`GET /health` reports load/compile status, `POST /diarize` takes
multipart audio (wav/flac/ogg via libsndfile, m4a/mp3/aac/opus/webm via PyAV) at any rate/channels and returns
`{duration_s, process_s, rtf, num_speakers, segments: [{start, end,
speaker}]}` in seconds.
`companion_core.meetings.speech_clients.HTTPDiarizationClient` calls this
whenever a meeting job reaches DIARIZING (ADR 0025).

Per [ADR 0025](../adr/0025-speech-inference-service.md), both sidecars
above are transitional: the target is a unified `speech-service` covering
STT, diarization and compatible future speech inference, consumed by
companion-core through the same client interfaces
(`speech_clients.py`'s `TranscriptionClient`/`DiarizationClient`
protocols) rather than a hardcoded hostname — pointing both clients at a
future unified service instead of these two sidecars is meant to be a
constructor-argument change, not a `MeetingWorker` rewrite. Neither
sidecar's own API is expected to change shape when that consolidation
happens — only where it's hosted. The deployed short-clip path is recorded
in [foundation verification](../verification/phase-27-foundation-2026-09-30.md).
Both updated wrappers also have isolated real-model long-WAV checks in
[long-audio verification](../verification/phase-27-long-audio-2026-09-30.md).

Both endpoints use spooled upload files and reject busy inference with 503
before decoding; each model still runs one request at a time. Core uses
file-backed multipart requests with a configurable response timeout; see
[long-recording operations](../deployment.md#long-meeting-recordings).

## Document worker (Phase 50A)

[Source](../../services/document-worker/) is a workspace member holding only the adapter (FastAPI, no MinerU import in
tests); MinerU 4.0.12 is installed in its image from a hash-pinned lock
([requirements-mineru.txt](../../deploy/homelab/document-worker/requirements-mineru.txt)) so its dependency stack never enters
the workspace lock or another service. Compose profile `documents`, internal-only network `documents`, read-only
non-root container with no capabilities and no GPU (see [deployment](../deployment.md#document-worker)). Nothing calls it
yet. It is the only interface to the document backend ([ADR 0034](../adr/0034-source-evidence-and-derived-artifacts.md),
[phase-50](../phase-50.md)); the MinerU Unix socket, library paths and cache never leave the container. Routes are in
`shared/protocols/document_worker_api.py`, shapes in `shared/models/document_worker.py`; all but `GET /health` need
`Authorization: Bearer $DOCUMENT_WORKER_TOKEN` (unset token: 503).

Resources are addressed by **Reachy's document id**, not the backend reference, because identical bytes share one backend object:

| Route | Behaviour |
|---|---|
| `POST /documents` (multipart: `document_id`, `source_hash`, `tier`, `extension`, `file`) | Streams the file, enforces the byte limit, checks SHA-256 against `source_hash` and the magic bytes against the extension (pdf, png, jpg, docx), keeps a per-document working copy and queues the parse. Same id and hash is idempotent; same id with other bytes is 409. A page range (`1-DOCUMENT_WORKER_MAX_PAGES`) is sent for PDFs only. |
| `GET /documents/{id}/status` | `queued`, `processing`, `ready`, `partial` (some pages, or more pages than the limit) or `failed`, with `backend_ref`, page count and an error code. |
| `POST /documents/{id}/parse` `{tier, force}` | Parse at another tier (reuses cached work); `force` invalidates the bytes' cached parses first (reprocess). |
| `GET /documents/{id}/read` | Bounded page read with start/end locators and a continuation cursor; cursors and returned locators must belong to this document. |
| `GET /documents/{id}/locator` | Read around a locator; a locator of another document is `404`. |
| `POST /documents/{id}/search` `{query, limit}` | Ranks THIS document's own parsed pages (`ranking.py`: stemmed terms, TF-IDF over the document's pages, filler words ignored, weak partial matches dropped) and returns the best pages with a snippet each; a hit's page is the page that was scored. MinerU's library-wide search is not used (it returns one snippet per document across the whole library, which cannot say which pages answer a question); parsed pages are cached in memory (bounded) and the cache is dropped on reprocess and delete. `complete: false` when the document has more pages than the worker reads. |
| `DELETE /documents/{id}` | Forgets the working copy, cleans orphans, verifies, and reports `shared_hash_remaining` when another Reachy document still uses the same bytes. Idempotent; a backend failure keeps the record so it can be retried. |

Backend messages (which can contain paths) never reach a response: errors are `{"error": code}` and only the code is logged.
Health requires the engine ready **and** MinerU telemetry disabled (the worker disables it at start and re-checks).

**Backend supervision (deployed 2026-10-12).** The worker process can outlive MinerU's server (an OOM kill under the container's memory limit takes the doclib server or its managed parse server, not uvicorn). `DoclibEngine` now (1) restarts a dead doclib server in a background thread through the same `start()` used at boot, triggered by the health check Docker runs every 15 s or by any call failing with `server_not_running`/`engine_unavailable`, single-flight and at most once per 30 s; (2) restarts a running doclib server whose managed parse server MinerU has given up on (`restart_count >= max_restart_attempts`, not running; MinerU logs "failed 3 restarts, disabling" and never retries by itself), at most once per 5 minutes (`mineru server restart`); and (3) refuses `ensure_parse` and `invalidate` while the backend is not ready (502 `engine_error`, which core treats as transient and retries), so a request during a restart or the first ~25 s after boot is never recorded by MinerU as a failed parse of those bytes. A parse server that merely died is respawned by MinerU itself in about 35 s and is left alone. Record: [worker recovery](../verification/phase-50-worker-recovery-2026-10-12.md).

## Document library (Phase 50B, 50C)

Part of companion-core (`companion_core/document_library/`), behind `DOCUMENT_LIBRARY_ENABLED` (default off; routes 404 and nothing is built or read when off). Needs migration `031_documents`.
**Not the legacy `/documents` routes**: those (Phase 5) ingest pasted text into the chunk-RAG store and are untouched; the file-backed subsystem lives under `/document-library` and the two are deliberately not merged.
Routes (`shared/protocols/document_library_api.py`) are service-token protected like every core route; the hub does not proxy them yet:

| Route | Behaviour |
|---|---|
| `GET /document-library/config` | `{enabled}` |
| `POST /document-library/documents` (multipart `file`, optional `title`, `sensitivity`, `project_scope`, `processing_priority`) | Stores the original once in the source store, creates the record, and (if a worker is configured) submits it at once. Type is decided by content (pdf, png, jpg, docx) and must agree with the extension; limit `DOCUMENT_LIBRARY_MAX_UPLOAD_BYTES` (default 50 MiB, an operational default). No class given means `work-private`; content never sets or lowers it. |
| `GET /document-library/documents`, `GET .../{id}` | Catalogue and detail: policy, state, tier, pages, error code; never a path or the backend reference. |
| `PATCH .../{id}` | Title, project scope (explicit null clears), sensitivity, priority; state and hash are not editable. |
| `POST .../{id}/reprocess` `{tier?}` | Parses the retained original again for the same document (the worker drops only that tier's cached parse); a failed document can be retried this way. |
| `GET .../{id}/read`, `GET .../{id}/locator`, `POST .../{id}/search` | Bounded reads and search inside this one document, by Reachy id. Responses carry `title`, `source_hash` and `evidence_type: "derived_extraction"`; hits carry a page only when the text was found there. 409 until processed, 403 above the caller's sensitivity ceiling or outside its project scope (checked from the Reachy record before any worker call; the ceiling comes from the trusted header `X-Reachy-Access-Ceiling`, which only the hub sets from the authenticated channel and its trust policy: owner web or Android session `sensitive`, owner Telegram its existing trusted-owner ceiling, robot voice or a shared speaker lower; absent means `work-private`, an unknown value is 400). |
| `DELETE .../{id}` | Marks `deleting` (unusable at once), the worker forgets it and must confirm, then the record and, only if no other document has the same hash, the original go. Unconfirmed: 502, stays `deleting`, retried by the sync loop and at startup. |

**Lifecycle.** `uploaded` (original stored) to `queued`, `processing`, `ready` / `partial` / `failed` as the worker reports; `deleting` is terminal from outside. A sync loop (`DOCUMENT_LIBRARY_SYNC_SECONDS`, default 5, only when `DOCUMENT_WORKER_URL` is set; every `DOCUMENT_LIBRARY_RECONCILE_SECONDS`, default 300, it also checks READY documents against the worker, and a read that finds the worker empty returns the document to the loop) submits `uploaded` documents the worker has not been given, follows `queued`/`processing`/`partial` documents to the worker's state, gives a document back to a worker that lost it (404) from the authoritative original, and retries deletions. A worker that is down is transient (nothing fails); a refusal (for example `tier_not_enabled`) marks the document `failed` with the code. Submit, reprocess and delete share a per-document lock so a deletion cannot finish before a racing submission. Initial tier policy (full policy is 50D): Word documents Flash; PDFs and images Basic (they may be scans); interactive priority Standard.

**Summaries (50H).** `POST .../{id}/summaries` `{style: ordinary|executive|technical, force?}` (202) starts a summary in the background and `GET` lists them (newest first). A document is read page by page from the worker (up to `DOCUMENT_LIBRARY_SUMMARY_MAX_PAGES`, default 60; more is reported as `truncated`), grouped into windows of about 6,000 characters, noted group by group by the LOCAL model only (map), the notes merged in batches if there are many (reduce), and the style applied last, so no model call sees more than a bounded amount of text and each section keeps its page range. A document with almost no extracted text is not summarised (`failed`, `sparse_text`, with a pointer to a higher extraction level). The result is a derived interpretation (`evidence_type: derived_interpretation`) stored with the original's hash, the extraction tier, the model and prompt version, the document's class at the time (the effective class is the higher of that and the document's class now), and a stale flag set when the document is reprocessed; it is removed with the document, and a run interrupted by a restart is marked `failed` (`interrupted`). A current summary of a style is returned as it is unless `force`. Document text reaches the model only as the user turn under a guard that calls it untrusted data.

**Tier escalation (50D).** Advanced is an ordinary tier of the same worker and models (checked: it reuses Standard's models and is very slow on CPU, minutes per page); `next_tier` on a document names the next rung (flash, basic, standard, advanced) and `POST .../reprocess {tier}` asks for it. It is never chosen automatically.

**Extraction inspector.** `GET .../{id}/inspect/pages/{n}` returns one page as MinerU extracted it: its blocks (1-based number, type, and a bounding box as fractions of the page), MinerU's markdown for the page (figure references rewritten to `#page-N-block-M`), MinerU's HTML rendering of the page (a self-contained fragment with MinerU's own stylesheet and no scripts), the tier, the original's hash and `evidence_type: derived_extraction`. `GET .../inspect/pages/{n}/image` is MinerU's rendering of the original page and `.../blocks/{b}/image` MinerU's crop of one block (PDF and image files; Word files have no page picture and answer 404). `GET .../export?format=markdown|html|content_list|middle_json` downloads what MinerU extracted (the HTML is scriptless and self-contained; `middle_json` is MinerU's own structured result, schema `docvortex.middle`), and `GET .../original` downloads the stored original after its hash is re-verified, with no worker needed. Every route re-runs the same checks as reading (document exists and is not being deleted, the original still matches its hash, the channel's ceiling and project allow it, the document is processed) before the worker is asked; downloads are attachments with `nosniff`, `no-store`, a `sandbox` content-security-policy on HTML and the original, and a file name built from the title (never a path). The worker side reuses MinerU rather than reimplementing it: page and block pictures come from the doclib's own image rendering, the structured result is the middle JSON MinerU stored, loaded with its own helpers and rendered with its public `render` API (the standalone HTML page is never used because it pulls a math library from a public CDN; only its stylesheet is taken), and the markdown is the doclib's. The HTML is also rebuilt from an allowlist before it leaves the worker (`htmlsafe.py`: no scripts, frames, images, forms, links' addresses, event handlers, inline styles or URLs; the stylesheet loses `@import` and every `url()`), in addition to MinerU's own escaping and the browser sandbox. Anything naming MinerU's data directory is refused before it leaves, backend locators and file paths never appear in any response, and worker error codes distinguish a missing page (`page_not_found`) from a document the worker has lost (`not_found`). The web page's inspector shows the original page picture (with a block overlay) beside the extraction in a locked, scriptless iframe, with Markdown and block-table views, page navigation, the tier and status, the existing Improve reading action and the downloads.

**Chat document picker (persistent attachment per conversation).** A saved web chat can be attached to one document: `PUT /chats/{chat_id}/document` `{user_id, document_id|null}` (hub, owner session or the existing chat bearer, CSRF required) attaches, replaces (another id) or removes (null) it, after the hub confirms with core that the document exists. The attachment is kept in the chat's own archive as a state entry in `web_chat_turns` (its JSON column, so there is no schema change), is not a message, does not change the chat's updated time and is returned as `document` on `GET /chats/{id}` (`{id, title, available}`, where `available` is false when the document has since been deleted); each conversation has its own, a new one has none, and deleting the chat deletes it. For `POST /messages` with a `chat_id` the hub applies the chat's attachment as the `context_document_id` of the turn and **ignores any document id the client sends**, so a message can neither smuggle in another document nor lose the attachment; each saved turn records the document it was answered under and its page citations (`document`, `citations` on the turn). Everything else is the existing document-scoped conversation: core re-checks existence, deletion state, source integrity, class and project (the hub's sensitive ceiling for a typed owner web message) and processing state on every turn and answers with its fixed replies when the document is deleted, unreadable here or not ready; nothing is added to memory or the knowledge index and no retrieval is involved beyond the document's own pages. The web chat shows "Answering from: <title>" with Replace and Remove, a picker that lists the library (only ready documents can be chosen), a warning for an unavailable document, and under each answer "From pages N of <title>"; choosing a document lets go of a chosen meeting and the reverse (one source at a time). In a new, unsaved chat the choice is held in the page and saved the moment the chat is created, before its first message; before that, leaving the chat drops it.

<a id="chat-history-scope"></a>**Chat history scope (isolation of short-term conversation history).** Core keeps its short-term conversation (the model's recent messages, the carried privacy label, the pending alarm offer and the search thread) in memory under a *history key*. Voice, Telegram, the robot and any turn without a saved chat keep the key `session_id` (the shared conversation of ADR 0002). A turn sent from a saved web or Android chat (`POST /messages` with a `chat_id`) is keyed `session_id` + `history_scope`, where the **hub** derives `history_scope` from the stored chat record (it must belong to the signed-in owner, else 404/403) and its attachment: `chat:<chat id>` with no context, `chat:<id>:doc:<document id>` while a document is attached, `chat:<id>:mtg:<sha256 prefix of the meeting id>` for a chosen meeting (an attached document wins; the two are exclusive). Consequences: chat A never sees chat B's turns; a new chat starts empty; replacing or removing a document, or choosing a meeting, starts that context's own history (the old document's answers are not in the model's context under another document); returning to a context resumes its history; the unscoped session history never contains chat turns. `history_scope` and `prior_turns` exist only on core's `/conversation` request (core is service-token protected); the hub's `InboundMessage` has no such fields, so a client that sends them changes nothing. If core holds no history for a scope (it restarted, or the oldest of 64 scoped histories was dropped), the hub sends up to six of the chat's own saved exchanges recorded under that same context (`prior_turns`), core restores them labelled work-private and ignores `prior_turns` whenever history exists; a turn records the meeting it was sent under (`meeting_id`) for this. Deleting a chat calls `POST /conversation/forget` so core drops that chat's histories. Telemetry, shadow routing and candidate capture keep the session id (Phase 48 data unchanged). The history is not persisted anywhere new and nothing from a document enters memory or the knowledge index. A one-off question about a document with no saved chat (`POST /messages` with `context_document_id` and no `chat_id`, as the web and Android Documents screens send it) is scoped `docqa:<document id>`: its own history per document, never the shared session. Residual: a spoken Android turn has no chat and so shares the voice/session history, as before.

**Hub proxy (50J).** The hub exposes the same `/document-library/...` paths to the owner session only (cookie, CSRF on changes; the bearer token is refused) and sets `X-Reachy-Access-Ceiling: sensitive` itself; whatever a browser sends in that header is not forwarded. Core decides everything else.

**Document-scoped conversation (50E).** `POST /conversation` takes `context_document_id` (hub `POST /messages` passes it through, as it does `context_meeting_id`). The answer draws only on excerpts of that one document: the best-ranked pages of that document (the whole text when it is at most three pages and nothing ranks), read from the worker; if nothing relevant is found, the reply is fixed ("I couldn't find that in ...") and the model is not called. The excerpts are supplied as quoted, untrusted data with page labels; deterministic handlers and the action gate run before, and the document is never consulted for an action request. Unknown, deleting, unprocessed or not-permitted documents get fixed replies with no model or worker content call; the model is local-only unless the owner asks for the frontier model, and a `sensitive` document is never sent to it. Reply fields: `context_document` (title) and `citations` (document id, title, page, locator of the pages whose excerpts were supplied, never page numbers the model wrote); the reply's privacy is at least the document's class. The ceiling comes from `X-Reachy-Access-Ceiling` as for the routes, capped at public for a spoken turn; the hub sets `sensitive` only for typed `web` messages when it enforces owner authentication (owner web and Android), and nothing else raises it (Telegram keeps core's default until its trusted-owner ceiling is wired). `MessageResponse` carries `context_document` and `citations`.

Originals live in the content-addressed source store (`DOCUMENT_SOURCE_DIR`, `sha256/ab/cd/<hash>`, write-once, re-verified before use: a mismatch is 409 on reads and `failed` / `source_corrupt` on submission, never served or sent). Identical bytes uploaded twice are two documents with their own policy and one blob; `backend_ref` is an opaque pointer shared by identical bytes, and authorization always starts from the document id. `DocumentWorkerClient` is Reachy's only client for the [document worker](#document-worker-phase-50a).

## Shared contracts and clients

Runtime service packages never import one another. Contracts live in
`shared/models`, route constants in `shared/protocols`. Workspace members
are independent images even though development installs them together.

[web](../../clients/web/) (React, Phase 47) is the operator UI at `/web/`: Overview, Chat (with deletable history), Meetings, To-do, Reminders, Alarms, Activity, Notes, Coding agents, Settings, Accounts, Owner recognition, voice and the Brain view. `/ui/` redirects to it; the old plain HTML/JS [operator-ui](../../clients/operator-ui/) is kept at `/ui-legacy/` as the rollback path; [web-pwa](../../clients/web-pwa/) serves Call Reachy/telepresence at
`/app/`. Both mount under `/hub/` through Caddy. Browser API paths must stay
relative so direct and proxied deployments work. User workflows are in the
[operator guide](../operator-guide.md), not duplicated in client READMEs.


## Google Accounts

[ADR 0021](../adr/0021-google-accounts.md) owns account identity and security.
Core `accounts/` owns transactions, encrypted credentials, OAuth and fixed-origin
read adapters; hub `accounts.py` owns authenticated browser transport.
`shared/protocols/accounts.py` and `shared/models/accounts.py` own the contract.

Under `/settings/accounts/google`, hub exposes status, configure, connect,
callback, complete, `desktop/start`, `desktop/complete`, test, disconnect,
calendar selection/list/events/free-busy, and Gmail messages/read. Core
equivalents require the dedicated service header. `configure` accepts a
`client_type` of `web` (the original fixed-HTTPS-callback client) or
`desktop` (loopback PKCE via `tools/google_auth_helper.py`, for installs
without a stable public HTTPS hostname); see
[ADR 0021's addendum](../adr/0021-google-accounts.md#addendum-phase-23b-2026-09-24-desktop-oauth-client-transport).
`desktop/start` is owner-authenticated like `connect`; `desktop/complete` is
unauthenticated at the hub layer like `callback`, authorized instead by the
helper presenting the state/binding pair `desktop/start` returned. There is
no generic provider proxy, decrypt endpoint or Google write API.
Calendar/email composition feeds the existing conversation, briefing and
reminder logic while keeping local writes and delayed SMTP dispatch local.

See [user workflows](../operator-guide.md#connect-gmail-and-google-calendar),
[installation and limits](../deployment.md#google-application-setup), and
[verification](../verification/phase-23-accounts-2026-09-23.md).

## Meeting-minutes email (Phase 55)

companion-core `meeting_distribution/` and `email/` and routes `/meeting-email/*`, `/meetings/{id}/email/{prepare,suggestions}` ([ADR 0039](../adr/0039-supervised-meeting-minutes-email.md), [Phase 55](../phase-55.md)); constants in `shared/protocols/meeting_email_api.py`; the hub proxies them for the owner session only (cookie + CSRF, never the bearer) in `reachy_hub/meeting_email.py`. They exist only while `MEETING_EMAIL_ENABLED` is true. `GET /meeting-email/config` (feature and sender status), `GET/PUT/DELETE /meeting-email/sender` (write-only credential, never returned), `POST .../sender/verify` (signs in and quits: sends nothing), `PUT .../sender/enabled` (needs a verified connection), saved recipient `groups`, `POST /meetings/{id}/email/prepare`, `GET .../suggestions`, and per draft `GET/PUT /meeting-email/drafts/{id}`, `POST .../approve` (package hash + typed `SEND`), `.../queue`, `.../cancel-send`, `.../discard`, `.../resolve` (settle an unknown delivery), `GET .../attachments/{name}` (the exact bytes, `no-store`, `nosniff`). The older `POST /emails/drafts/*` routes and the conversational draft/approve/send keep working for plain text drafts only. States `draft, ready_for_review, approved, queued, sending, sent, cancelled, failed, unknown_delivery`; every state change is an event in `email_draft_events`.

## Identify Speakers (Phase 54)

companion-core `GET /meetings/{id}/speakers/identify` (each diarization label with the owner's decision, up to three deterministic samples plus alternates as time ranges of the recording, a `fingerprint`, name suggestions, `needs_review`, `stale_outputs`) and `PUT` (decisions `named`/`unknown`/`skipped`/`clear` per label, optional `contact_id`, `fingerprint` checked: 409 if the diarization changed); the older `PUT /meetings/{id}/speakers` writes the same record. Samples are played through `GET /meetings/{id}/audio`; nothing is generated or stored. `Meeting` gains `speaker_identity`, `stale_outputs`; `MeetingOutput` gains `speaker_basis`. Hub proxies behind the owner session (`MEETING_SPEAKERS_IDENTIFY`). [ADR 0038](../adr/0038-meeting-speaker-identification.md), [Phase 54](../phase-54.md).

## Multimodal meeting intelligence (Phase 53)

companion-core `companion_core/meeting_multimodal/` and routes under `/meetings/{id}/multimodal` and `/meeting-multimodal` ([ADR 0037](adr/0037-multimodal-meeting-evidence-and-slide-alignment.md), [Phase 53](phase-53.md)); constants in `shared/protocols/meeting_multimodal_api.py`; the hub proxies them for the owner session only and sets the access ceiling (`reachy_hub/meeting_multimodal.py`). Flag `MEETING_MULTIMODAL_ENABLED` (default off, needs the document library); schema `034_meeting_multimodal` (five tables, no foreign keys, `deploy/homelab/rollback-034.sql`). Web: the Documents tab and slide cards in the transcript (`clients/web/src/features/meetings`). Not on Android. Not built on Phase 31's frozen files, Phase 44 indexing or Phase 48/50F.

## Home dashboard (Phase 51)

companion-core `GET /home[?sections=]` and `POST /home/brief` ([ADR 0036](adr/0036-home-dashboard.md), [Phase 51](phase-51.md)); the hub proxies both for the owner session (`reachy_hub/home.py`, CSRF on the POST). Read-only; sections `schedule`, `tasks`, `reminders`, `reviews`, `weather`, each with its own `status`; records are filtered by the caller's ceiling and scope before counting. Weather: `companion_core/weather.py` (Open-Meteo, `WEATHER_*` settings). Existing `GET /briefing` and `POST /briefing/{user_id}` are unchanged.
