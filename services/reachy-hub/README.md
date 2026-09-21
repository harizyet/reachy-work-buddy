# reachy-hub

Runs in the homelab. Owns: sessions, Telegram, WebRTC, web UI, response
routing, authentication, robot registry.

Must not own: reasoning policy internals, raw motor control (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 4)

Implements the robot-registry / proxy slice: `POST /robots`, `GET /robots`,
`GET /robots/{robot_id}/state`, `GET /robots/{robot_id}/behaviours`,
`POST /robots/{robot_id}/behaviour/{name}`. Per ADR 0003 ("Sent by
companion-core (via reachy-hub) to reachy-embodiment's
POST /behaviour/{name}"), reachy-hub is the service that actually holds the
network path to each robot — companion-core never talks to
reachy-embodiment directly.

- `robot_registry.py` — a `RobotRegistry` Protocol with `PostgresRobotRegistry`
  (production; durable across restarts, see `postgres_registry.py`) and
  `InMemoryRobotRegistry` (tests).
- `embodiment_client.py` — HTTP client for one reachy-embodiment instance.
- A background task pings every registered robot's `POST /heartbeat` every
  `heartbeat_interval` seconds (default 2.0s), keeping reachy-embodiment's
  presence loop (Phase 3 / ADR 0004) out of `DISCONNECTED`. This interval
  must stay comfortably below reachy-embodiment's watchdog timeout (default
  5.0s) — equal defaults were tried first and caused spurious disconnects
  under real container-startup timing; see the comment in `app.py`.

Sessions, Telegram, WebRTC, web UI, and auth (reachy-hub's full ADR 0001
ownership) are later phases (5-7, 15) — not implemented yet.

## Run it

```
uv sync --all-packages
DATABASE_URL=postgresql://reachy:pw@localhost:5432/reachy_hub \
  uv run uvicorn reachy_hub.main:app --app-dir services/reachy-hub/src --reload
```

Or via the full stack — see [deploy/homelab](../../deploy/homelab/).

## Test

```
uv run --group dev pytest services/reachy-hub/tests
```

Tests use `InMemoryRobotRegistry` and chain against a real (in-process)
reachy-embodiment app via `httpx.ASGITransport` — no mocks, no real network,
no real Postgres required. `PostgresRobotRegistry` itself is exercised by
the live `docker compose` stack (see deploy/homelab/README.md), not by the
unit test suite.
