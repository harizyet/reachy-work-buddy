# reachy-hub

Runs in the homelab. Owns: sessions, Telegram, WebRTC, web UI, response
routing, authentication, robot registry.

Must not own: reasoning policy internals, raw motor control (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 6)

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
- Content-based routing (privacy, urgency, active-meeting suppression) is
  Phase 9's extension of this same policy, not implemented yet — see
  ADR 0006's Consequences section for why that's deliberately deferred.

Telegram, WebRTC, web UI, and auth (reachy-hub's full ADR 0001 ownership)
are later phases (7, 15) — not implemented yet.

## Run it

```
uv sync --all-packages
DATABASE_URL=postgresql://reachy:pw@localhost:5432/reachy_hub \
COMPANION_CORE_URL=http://localhost:8000 \
  uv run uvicorn reachy_hub.main:app --app-dir services/reachy-hub/src --reload
```

Or via the full stack — see [deploy/homelab](../../deploy/homelab/).

## Test

```
uv run --group dev pytest services/reachy-hub/tests
```

Tests use `InMemoryRobotRegistry`/`InMemorySessionStore` and chain against
real (in-process) reachy-embodiment and companion-core apps via
`httpx.ASGITransport` — no mocks, no real network, no real Postgres
required. `test_two_test_clients_share_one_conversation_state_across_channels`
is the direct proof of Phase 5's exit criterion;
`test_mode_change_alone_changes_delivery_channel_without_touching_the_message_text`
is Phase 6's. `test_response_policy.py` unit-tests the routing function in
isolation, including asserting its parameter list has no content field.
`PostgresRobotRegistry` and `PostgresSessionStore` themselves are exercised
by the live `docker compose` stack (see deploy/homelab/README.md), not by
the unit test suite.
