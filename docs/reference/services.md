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
| `GET`, `POST /tasks`; `POST /tasks/{id}/complete`; `GET /tasks/search` | Capture, list, complete, search follow-ups |
| `GET`, `POST /memories`; `GET /memories/recall` | Durable targeted work-memory retrieval, separate from transcript |
| `POST /memories/{id}/request-forget`, `/forget/confirm`, `/restore` | Text-confirmed soft deletion and undo |
| `GET`, `POST /documents`; `GET /documents/search` | Operator ingestion and document/section retrieval |
| `GET`, `POST /emails/received`; `GET`, `POST /emails/drafts` | Seeded inbox and deterministic drafts, no production mailbox sync yet |
| `POST /emails/drafts/{id}/approve`, `/send`, `/cancel-send` | Text approval/send, delayed dispatch, cancellation |
| `GET /briefing` | Prioritized briefing items for hub's delivery engine |
| `GET`, `PUT /settings/llm`; `GET /llm/usage` | Internal settings/usage; operator callers use authenticated hub proxies |
| `GET`, `PUT /settings/persona` | Assistant name/system prompt (`persona_config` table); prepended as a system message on the generic LLM branch only |
| `GET`, `PUT /settings/websearch` | Web-search grounding policy/provider (`search_config` table); Phase 24a, see below |
| `/debug/robots/...` | Debug integration plumbing, not a stable agent-tool API |

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
(`ConversationStore.search_topic`). VOICE-modality turns also get
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
Same-session turns serialize; the latest 39 user/assistant messages provide
bounded context, reset on restart. Work-memory recall queries persistent
records, never dumps that transcript. Calendar/email replies are
work-private; generated follow-ups retain the strongest prior context label.
Generic privacy classification and intent matching remain keyword-based, not
semantic understanding.

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

## reachy-hub

[Source](../../services/reachy-hub/src/reachy_hub/) owns sessions, channels,
response routing, authentication, robot registry/connectivity, STT/TTS,
WebRTC, and static UI. It does not own reasoning policy or motor control.

| Surface | Purpose |
|---|---|
| `POST /messages`; `GET /sessions/{user_id}` | Shared session across text channels; one active session per user |
| `POST /voice/turn` | Caller-upload diagnostic: multipart WAV `audio` and owner `user_id`; STT → shared conversation → WAV TTS. Owner-gated by the work-route middleware before STT; not the robot workflow and no speaker-routing check |
| `POST /webrtc/offer` | Conversational push-to-talk call; voice modality cannot confirm actions |
| `PATCH /sessions/{user_id}/mode`, `/dnd`, `/privacy-context` | Authenticated updates to existing sessions |
| `GET /audit/{user_id}`, `/notifications/{user_id}`; `POST /notifications/{user_id}/flush` | Routing decisions, queued notifications, controlled flush |
| `POST /calendar/check-reminders/{user_id}`, `/briefing/{user_id}` | On-demand proactive routing, not an automatic schedule |
| `POST`, `GET /robots` | HTTP robot registry |
| `GET /robots/{id}/state`, `/behaviours`; `POST /robots/{id}/behaviour/{name}`, `/speak` | Authenticated robot proxies and direct speak-through control |
| `POST /robots/standby`, `/resume` | Phase 22b: authenticated remote power control — parks/de-torques (`standby`) or wakes (`resume`, `wake_up` query param) every registered robot; no `{id}` in the path, loops the registry like the existing gesture-trigger helper does |
| `POST /webrtc/telepresence/offer` | Authenticated remote media/control |
| `WS /robots/connect` | Robot-token-authenticated registration/heartbeat/reconnect; also `voice_start`/`voice_stop`/`voice_state` conversation control (Phase 24c); other commands still HTTP |
| `GET /robot-voice`; `POST /robot-voice/start`, `/renew`, `/stop` | Phase 24c owner controls: robots with the voice capability, the current session, its lease and recent turns |
| `POST /robot-media/voice-turn` | Phase 24c robot upload of one WAV utterance, authenticated with the robot's own credential, generation and session; returns reply WAV or 204 with `X-Voice-Turn-Outcome` |
| `POST /auth/login`, `/auth/logout`; `GET /auth/me` | Owner-cookie lifecycle; login/logout require CSRF header |
| `GET /status` | Authenticated component probes, model config/usage, Telegram polling health, default user ID |
| `GET`, `PUT /settings/llm`; `GET /llm/usage` | Authenticated core proxies; usage defaults `limit=50`, `since_hours=24` |
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

Response policy first chooses by mode, then enforces privacy, then records
an audit. Direct replies are returned on the inbound channel regardless of
proactive `delivery_channel` metadata. Reminder and briefing delivery reuse
the interruption policy and queue; Phone delivery is not a working push
integration. See [ADR 0006](../adr/0006-response-routing.md),
[ADR 0014](../adr/0014-interruption-intelligence.md), and
[ADR 0015](../adr/0015-daily-briefing.md).

Telegram stores learned chat IDs separately from channel-agnostic sessions.
Poll health lives in memory and resets on restart. STT/TTS are lazy local
faster-whisper/espeak providers. WebRTC orchestration is separate from SDP
and audio tracks; playback resamples to 48kHz mono because aiortc's Opus
encoder does not adapt when tracks with different formats are swapped.

Robot voice sessions ([ADR 0023](../adr/0023-robot-voice-conversation.md),
`robot_voice.py`) are process-local, one per robot. They are bound to the
robot's connection generation and ended by logout, lease lapse, idle timeout,
maximum length or disconnect. A turn is transcribed and sent to core as
`channel=reachy`, `input_modality=voice`. It is synthesized only when
`resolve_delivery_channel` → `apply_privacy_override` →
`robot_speech_withheld_reason` (DND/meeting) all permit the robot speaker.

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
passed physical acceptance. Barge-in and wake words are not implemented.

`ReachyDaemonBackend` calls daemon HTTP under `/api`. Recorded moves use the
Pollen emotions dataset. Camera frames and the microphone share one
`reachy_mini` LOCAL media client. Audio playback is upload-then-play, and
`stop_audio` calls `/api/media/stop_sound`.
Physical camera/audio acceptance is still outstanding. Read
[bring-up evidence](../verification/phase-22-bring-up.md) before treating the
simulator's successful move lifecycle as validated real motion.

## Shared contracts and clients

Runtime service packages never import one another. Contracts live in
`shared/models`, route constants in `shared/protocols`. Workspace members
are independent images even though development installs them together.

[operator-ui](../../clients/operator-ui/) serves owner Overview/Chat at
`/ui/`; [web-pwa](../../clients/web-pwa/) serves Call Reachy/telepresence at
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
