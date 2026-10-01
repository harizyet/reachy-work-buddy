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
| `GET /coding-agents/completions/due` | Phase 29.6: newly-terminal coding-agent sessions, claimed once each so reachy-hub's poll loop never double-notifies; same pure-query shape as `/calendar/reminders/due` |
| `GET`, `PUT /settings/llm`; `GET /llm/usage` | Internal settings/usage; operator callers use authenticated hub proxies |
| `GET`, `PUT /settings/persona` | Assistant name/system prompt (`persona_config` table); prepended as a system message on the generic LLM branch only |
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
subscription usage or remaining allowance; the current in-memory session history
is lost on coding-agent-service restart.

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
| *(internal, no route — a background task)* `coding_agent_notify_loop` | Phase 29.6: polls companion-core's `/coding-agents/completions/due` every `coding_agent_notify_interval` seconds (default 60) and pushes a Telegram message via the existing `push_to_telegram` helper for anything due. Unlike the calendar reminder row above, this is a genuine always-on loop, not on-demand — and deliberately skips `interruption_policy`'s occupied/DND/urgency routing, pushing immediately every time; revisit if routine completions start interrupting something they shouldn't |
| `POST`, `GET /robots` | HTTP robot registry |
| `GET /robots/{id}/state`, `/behaviours`; `POST /robots/{id}/behaviour/{name}`, `/speak` | Authenticated robot proxies and direct speak-through control |
| `GET`, `PUT /robots/{robot_id}/settings/motion` | Owner-authenticated proxy for robot-local conversational animation switches; changes only between conversations |
| `POST /robots/standby`, `/resume` | Phase 22b: authenticated remote power control — parks/de-torques (`standby`) or wakes (`resume`, `wake_up` query param) every registered robot; no `{id}` in the path, loops the registry like the existing gesture-trigger helper does |
| `POST /webrtc/telepresence/offer` | Authenticated remote media/control |
| `WS /robots/connect` | Robot-token-authenticated registration/heartbeat/reconnect; also `voice_start`/`voice_stop`/`voice_state` conversation control (Phase 24c) and `wake_arm` (Phase 24g, sent after every registration); other commands still HTTP |
| `GET /robot-voice`; `POST /robot-voice/start`, `/renew`, `/stop` | Phase 24c owner controls: robots with the voice capability, the current session, its lease and recent turns |
| `POST /robot-media/voice-turn` | Phase 24c robot upload of one WAV utterance, authenticated with the robot's own credential, generation and session; returns reply WAV or 204 with `X-Voice-Turn-Outcome`, which is `continue` when the hub holds an unfinished-sounding segment (24e; `X-Voice-Segment` numbers the held turn's further segments) |
| `POST /robot-media/voice-turn/finalize` | Phase 24e: same robot credential and fencing headers, no body; answers the held turn when the robot heard no more speech in the continuation window |
| `POST /robot-voice/wake` | Phase 24g owner control: arm or disarm "Hey Reachy" for one robot (persisted, `robot_wake_arm`); returns the overview, whose robots carry `wake_capable`, `wake_armed` and content-free `wake_counts` |
| `POST /robot-media/wake-candidate` | Phase 24g robot upload of one wake candidate WAV with the robot credential, generation and `X-Wake-Arm`; 200 with the new session ID when admitted, 204 `rejected` otherwise, 409 for a stale arm or connection |
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
tests). `reconcile.py`'s `reconcile_sessions` marks a session `LOST` (never
`COMPLETED`) when its container is no longer running. The runtime is not
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
| `POST /sessions/{session_id}/refresh` | Re-checks a non-terminal session against its provider/container right now (29.3); no background poller or hook bridge exists yet to do this automatically |
| `GET /sessions/{session_id}/events` | Normalized event log for that session |
| `GET /sessions/{session_id}/usage` | Capability-gated `UsageSnapshot`; absent dimensions are unknown, never assumed zero |
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
claim-once query like `/calendar/reminders/due`) is what lets reachy-hub
push a Telegram message when a session finishes — see reachy-hub's section
below for that loop. Session *management* — registering a project,
starting/resuming/stopping a session — still has no hub/companion-core
path; only status/usage reads and completion notifications do.

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
multipart wav/flac/ogg audio at any rate/channels and returns
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
