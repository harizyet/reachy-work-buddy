# reachy-hub

Runs in the homelab. Owns: sessions, Telegram, WebRTC, web UI, response
routing, authentication, robot registry.

Must not own: reasoning policy internals, raw motor control (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 5)

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

Telegram, WebRTC, web UI, and auth (reachy-hub's full ADR 0001 ownership)
are later phases (6-7, 15) — not implemented yet.

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
is the direct proof of Phase 5's exit criterion. `PostgresRobotRegistry` and
`PostgresSessionStore` themselves are exercised by the live `docker compose`
stack (see deploy/homelab/README.md), not by the unit test suite.
