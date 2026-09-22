# reachy-hub

Runs in the homelab. Owns: sessions, Telegram, WebRTC, web UI, response
routing, authentication, robot registry.

Must not own: reasoning policy internals, raw motor control (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 10)

**Robot registry / proxy (Phase 4)**: `POST /robots`, `GET /robots`,
`GET /robots/{robot_id}/state`, `GET /robots/{robot_id}/behaviours`,
`POST /robots/{robot_id}/behaviour/{name}`. Per ADR 0003, reachy-hub holds
the network path to each robot — companion-core never talks to
reachy-embodiment directly.

- `robot_registry.py` / `postgres_registry.py` — `RobotRegistry` Protocol,
  `PostgresRobotRegistry` (production), `InMemoryRobotRegistry` (tests).
- `embodiment_client.py` — HTTP client for one reachy-embodiment instance.
- A background task pings every registered robot's `POST /heartbeat` every
  `heartbeat_interval` seconds (default 2.0s) — comfortably below
  reachy-embodiment's watchdog timeout (default 5.0s); equal defaults were
  tried first and caused spurious disconnects under real container-startup
  timing (see `app.py`).

**Sessions (Phase 5, ADR 0002)**: `POST /messages` normalizes an inbound
`(user_id, channel, text)` to a persistent `AgentSession` and forwards a
channel-agnostic turn to companion-core; `GET /sessions/{user_id}` exposes
session state directly. One active session per user (not per conversation)
is a deliberate V0.1 simplification — see `session_store.py`.

- `session_store.py` / `postgres_session_store.py` — `SessionStore`
  Protocol, `PostgresSessionStore` (production, durable across restarts),
  `InMemorySessionStore` (tests).
- `companion_core_client.py` — HTTP client for companion-core's
  `/conversation` endpoint.
- Switching channels (e.g. Reachy -> Telegram) updates `active_channel` and
  `last_active_at` but never creates a new `session_id` or
  `conversation_id` — verified live: same session survived both a channel
  switch and a `reachy-hub` process restart against real Postgres.

**Operating modes (Phase 6, ADR 0006)**: `PATCH /sessions/{user_id}/mode`
sets `interaction_mode` (Desk/Office/Silent/Remote); `POST /messages`
includes `delivery_channel`, computed by
`response_policy.resolve_delivery_channel(mode, active_channel)`.

- Desk -> Reachy, Office -> Phone, Remote -> Phone, Silent -> whichever
  text-capable channel is already active (falls back to the web client if
  the active channel is Reachy, which has no silent output path).
- The policy function takes no response content as a parameter — mode alone
  determines routing, which is what makes "mode changes output routing
  without prompt changes" a structural guarantee rather than a behavioural
  one. Verified live: identical text sent twice on the same channel routed
  to `reachy`, then `phone`, then (via a channel switch while silent)
  `web`, purely from `PATCH .../mode` calls in between.
- Content-based routing (privacy) is Phase 9's extension of this same
  policy — see below.

**Telegram (Phase 7)**: `telegram_client.py` is a thin Bot API wrapper
(long-polling `getUpdates`, not a webhook — no public HTTPS endpoint story
yet). Optional and off by default: no `TELEGRAM_BOT_TOKEN` means no client,
no polling task, no Postgres connection for the chat registry either —
graceful degradation to Reachy-only, like every other optional integration
here.

- Every inbound Telegram message resolves to a single configured
  `telegram_default_user_id` (`TELEGRAM_DEFAULT_USER_ID` env, default
  `"default-user"`) — this project is a personal assistant, not
  multi-tenant, so there's no per-Telegram-user identity mapping to build
  yet.
- `telegram_chat_registry.py` / `postgres_telegram_chat_registry.py` learns
  the Telegram `chat_id` to reply to the first time that user messages the
  bot (bots can't originate a chat) and persists it — separate from
  `AgentSession` because it's channel-specific delivery plumbing, not part
  of ADR 0002's channel-agnostic session.
- Text only. Voice notes are silently skipped (not stubbed) — the Telegram
  poll loop doesn't call into `stt.py` yet, even though Phase 8 built real
  STT. Wiring `message.voice` through `stt.py` is a natural, small follow-up
  but wasn't part of Phase 8's own exit criterion (which is about the Reachy
  voice channel, not Telegram voice notes) — noted here rather than left
  implicit, since it's now genuinely close to done rather than blocked on
  missing infrastructure.
- The poll loop **always replies on the channel the message arrived on**,
  regardless of `delivery_channel` — see ADR 0006's Consequences section
  for why that gate would otherwise silently drop the first reply to any
  fresh session (which defaults to Desk mode, whose `delivery_channel` is
  always `reachy`). This is a real design correction made while building
  this integration, not a hypothetical.
- **Verified live**, not just against a fake Bot API: a real bot
  (`@reachy_buddy_bot`), a real Telegram account sending a real message,
  and a session GET showing the identical `session_id`/`conversation_id`
  as a preceding "start on Reachy" call, with `active_channel` switched to
  `telegram` — the Phase 7 exit criterion end to end.

**Speech stack (Phase 8)**: `POST /voice/turn` accepts a WAV recording
(multipart `audio` field + `user_id`), transcribes it (`stt.py`,
`FasterWhisperSTT` — local, no API key), routes the text through the exact
same `handle_inbound_message` path every other channel uses (channel
`reachy`), and synthesizes the reply back to WAV (`tts.py`, `EspeakTTS` — a
real local engine, since no cloud TTS key is available; same
graceful-degradation-without-credentials pattern as Telegram). Per
docs/plan.md §8's deployment table, STT/TTS run here in the homelab, not on
reachy-embodiment — unlike Jarvis's on-device design.

- Both providers are constructed **lazily**, on first use, not at app
  startup — loading a Whisper model is real work every test/instance
  shouldn't pay for just by importing this module.
- `reachy-embodiment` gets its own real Silero VAD wrapper
  (`audio/vad.py`, adapted from the Jarvis baseline) for the separate,
  latency-critical concern of live barge-in detection — not wired to a
  live audio stream yet (no physical Reachy microphone in this project's
  dev/test environment), same honest scoping already used for `/gaze`,
  `/pose`, `/audio/play`.
- A real design bug was found and fixed while building this: the Telegram
  poll loop (Phase 7) originally only replied when `delivery_channel`
  matched the inbound channel — which would silently drop the very first
  reply to any fresh session, since a new session defaults to Desk mode
  (`delivery_channel` always `reachy`). See ADR 0006's Consequences section.
- Getting the CPU-only `torch` build for `silero-vad` right (rather than
  silently pulling ~4GB of unused CUDA packages) took two real fixes to
  `uv` configuration — see `AGENTS.md`'s "uv dependency conventions" for
  what actually worked and why the obvious approach didn't.
- **Verified live** at three levels: automated tests with real (not
  mocked) STT/TTS round-tripping through real synthesized speech; a real
  running process hit with `curl` and a synthesized WAV question,
  including re-transcribing the WAV reply to confirm it's genuinely
  intelligible synthesized speech, not silence or noise; and the actual
  `reachy-hub`/`companion-core` Docker images, on a real Docker network and
  through the deployed Caddy reverse proxy, doing the same round trip.

**Privacy/response router (Phase 9, ADR 0006 addendum)**: companion-core
now proposes a `Privacy` classification per turn (`privacy_classifier.py` —
a placeholder keyword classifier, same honesty-about-scope as the rest of
companion-core's reasoning); `response_policy.apply_privacy_override`
enforces it, as a **second function**, not a modification of
`resolve_delivery_channel` (whose narrow, content-free signature stays
exactly as Phase 6 left it — that's a tested structural guarantee, not
just a convention). A `work-private` or `sensitive` response can never be
delivered via Reachy's speaker, regardless of mode — including Desk, which
Phase 6 otherwise always routes to Reachy.

- `MessageResponse` now includes `privacy`; every routing decision is
  recorded via `audit_log.py` (`PostgresAuditLog` / `InMemoryAuditLog`,
  same Protocol pattern as everything else) and exposed at
  `GET /audit/{user_id}` — the "audit events" half of Phase 9's deliverable.
- Urgency-driven behavior (phone alert + Reachy gesture) and active-meeting
  suppression, both in docs §4's routing table, are **not** implemented —
  they need push-notification/queueing infrastructure this phase's exit
  criterion didn't require.
- A real interaction was found while building this, not invented for the
  test: an existing Phase 6 test used calendar-flavored example text, and
  started failing once this classifier landed — "calendar" is one of the
  placeholder's own work-private keywords, so Desk mode correctly stopped
  routing it to Reachy. The test's example text was fixed (Phase 6's test
  is about mode-only routing and needs genuinely public content); the new
  behavior was correct.
- **Verified live** at three levels: automated tests exercising the real
  classifier -> real override -> real audit-log chain; a running process
  hit with `curl` showing a sensitive payload staying off Reachy in both
  Desk and Office mode, with the audit log correctly marking only the Desk
  case as `overridden: true` (Office already wouldn't have used Reachy);
  and the same sequence through the real deployed Caddy stack, with the
  audit entries surviving a `reachy-hub` restart via Postgres.

**Calendar reminder routing (Phase 10, ADR 0010)**: `POST
/calendar/check-reminders/{user_id}` pulls due reminders from
companion-core (`companion_core_client.due_reminders`) and runs each
through the *exact same* `resolve_delivery_channel` + `apply_privacy_override`
+ `audit_log` pipeline `POST /messages` uses — no new routing logic, no
background scheduler. If the resolved channel is Telegram and a `chat_id`
is already known, the reminder is actually delivered; otherwise the routing
decision is still computed, audited, and returned (`delivered: false`,
which is not an error — it means no live delivery path exists for that
channel yet, e.g. Phone/Remote).

- No proactive/background polling — this is a pure on-demand query. A
  scheduler that calls it periodically is Phases 17-18's job, not this
  one's; "meeting reminders route appropriately" is proven by the routing
  decision being correct when invoked, not by it happening automatically.
- **Verified live**: an event starting in 5 minutes, checked through the
  real deployed Caddy stack, correctly routed away from Reachy (Desk mode's
  default) because calendar content is `work-private` — with
  `overridden: true` in the audit trail, same as any other privacy
  override.

WebRTC, web UI, and auth (reachy-hub's full ADR 0001 ownership) are later
phases (15) — not implemented yet.

## Run it

```
uv sync --all-packages
DATABASE_URL=postgresql://reachy:pw@localhost:5432/reachy_hub \
COMPANION_CORE_URL=http://localhost:8000 \
TELEGRAM_BOT_TOKEN=123456:your-token \
  uv run uvicorn reachy_hub.main:app --app-dir services/reachy-hub/src --reload
```

`TELEGRAM_BOT_TOKEN` is entirely optional — omit it to run without Telegram.
`espeak-ng` must be on `PATH` for `/voice/turn` to work outside Docker (the
`Dockerfile` installs it via `apt`); `sudo apt install espeak-ng` for local
dev, or extract it without root the way this project's own dev environment
did (see `AGENTS.md`).

```
curl -X POST http://localhost:8001/voice/turn \
  -F "user_id=hariz" \
  -F "audio=@question.wav;type=audio/wav" \
  -o reply.wav
# -D - to see the X-Transcript / X-Reply-Text headers too.
```

Or via the full stack — see [deploy/homelab](../../deploy/homelab/).

## Test

```
uv run --group dev pytest services/reachy-hub/tests
```

Tests use `InMemoryRobotRegistry`/`InMemorySessionStore`/`InMemoryAuditLog`
and chain against real (in-process) reachy-embodiment and companion-core
apps via `httpx.ASGITransport` — no mocks, no real network, no real
Postgres required. `test_two_test_clients_share_one_conversation_state_across_channels`
is the direct proof of Phase 5's exit criterion;
`test_mode_change_alone_changes_delivery_channel_without_touching_the_message_text`
is Phase 6's; `test_telegram.py::test_start_on_reachy_continue_in_telegram`
is Phase 7's (against `httpx.MockTransport` standing in for the real
Telegram Bot API); `test_voice.py`'s tests are Phase 8's, chaining a real
`espeak-ng` process for TTS and a real `faster-whisper` model for STT
(`tiny.en`, for speed) through the same `/voice/turn` -> session ->
companion-core path a real Reachy would use;
`test_private_content_is_never_spoken_via_reachy_even_in_desk_mode` and
`test_private_test_payload_cannot_be_spoken_in_office_mode` are Phase 9's.
`test_response_policy.py` unit-tests both routing functions in isolation,
including asserting `resolve_delivery_channel`'s parameter list still has
no content field after Phase 9 added a *second* function alongside it.
`test_check_reminders_routes_through_the_same_policy_as_messages` is Phase
10's. `PostgresRobotRegistry`, `PostgresSessionStore`, `PostgresAuditLog`,
`PostgresCalendarStore` (companion-core's, exercised through this chain),
and the real Telegram Bot API itself are exercised live (real Postgres, a
real bot, a real Telegram account — see deploy/homelab/README.md), not by
the unit test suite.

Tests touching real models/subprocesses are marked `@pytest.mark.slow` and
skip cleanly if `espeak-ng` isn't on `PATH`:

```
uv run --group dev pytest services/reachy-hub/tests -m "not slow"   # fast loop
uv run --group dev pytest services/reachy-hub/tests -m slow         # real STT/TTS
```
