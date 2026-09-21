# deploy/homelab

Docker Compose deployment for `companion-core`, `reachy-hub`, PostgreSQL,
and a Caddy reverse proxy. Kubernetes is explicitly out of scope for initial
releases (see docs/plan.md §1 non-goals).

`reachy-embodiment` is also included in this compose file, purely so the
full chain (companion-core -> reachy-hub -> reachy-embodiment) can be
smoke-tested locally with one `docker compose up`. In a real deployment
reachy-embodiment runs on the Reachy Mini itself (see
[deploy/reachy](../reachy/)), not in this homelab stack.

Redis is not included — nothing in the system needs it yet (see
docs/plan.md §8: listed as "optional").

Verified with a real `docker compose up --build` run against this exact
file (Docker Compose v2, Postgres 16, Caddy 2): all five containers start,
the robot registry survives a `reachy-hub` container restart (Postgres
persistence), and a request routed through Caddy
(`POST /core/debug/robots/desk-1/behaviour/greeting`) reaches
reachy-embodiment and changes its reported state — end to end, through the
actual reverse proxy, not just localhost port-forwarding.

## Run it

```
cp .env.example .env   # set a real POSTGRES_PASSWORD
docker compose up -d --build
```

```
curl http://localhost:8080/hub/health
curl http://localhost:8080/core/health

curl -X POST http://localhost:8080/hub/robots \
  -H 'Content-Type: application/json' \
  -d '{"robot_id": "desk-1", "base_url": "http://reachy-embodiment:8000"}'

curl http://localhost:8080/core/debug/robots/desk-1/state
curl -X POST http://localhost:8080/core/debug/robots/desk-1/behaviour/greeting
```

No robot is auto-registered — `POST /hub/robots` above is a manual step.
Automatic registration (e.g. reachy-embodiment announcing itself to
reachy-hub on startup) isn't built yet; it's a natural fit for whichever
later phase adds real robot provisioning.

## Caddy

`Caddyfile` does path-based routing only (`/hub/*` -> reachy-hub, `/core/*`
-> companion-core). It does **not** implement authentication yet — see
docs/plan.md §9. Do not expose this port to the public Internet as
configured here; auth/TLS for real remote access is Phase 16 (remote
telepresence) territory.

## Known limitation

The Postgres migration in `reachy_hub/postgres_registry.py` is a single
`CREATE TABLE IF NOT EXISTS` run at connect time — fine for the one table
Phase 4 needs, but not a real migration tool. Revisit once companion-core or
reachy-hub need a second table (Phase 5's `AgentSession` is the likely
trigger).
