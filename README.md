# reachy-work-buddy

Office work companion built on Reachy Mini: a homelab reasoning/session
control plane plus a Reachy-side embodiment service, decoupled so the robot
stays expressive even when the homelab is unreachable.

- [AGENTS.md](AGENTS.md) — instructions for coding agents working in this repo.
- [docs/plan.md](docs/plan.md) — full technical plan, roadmap, release targets.
- [docs/adr/](docs/adr/) — binding architecture decisions.
- [docs/jarvis-baseline.md](docs/jarvis-baseline.md) — Phase 1 reference baseline from the upstream Jarvis project.
- [shared/models/](shared/models/) — cross-service data contracts (`AgentSession`, `AgentResponse`, `MemoryRecord`, `EmbodimentCommand`).
- [shared/protocols/](shared/protocols/) — HTTP route contracts shared between services.

## Status

Phases 0-5 are done:

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

See [docs/plan.md §6](docs/plan.md#6-implementation-roadmap) for the
phase-by-phase roadmap. Next up: Phase 6, Desk/Office/Silent/Remote
operating modes as deterministic output routing.

## Layout

```
services/companion-core/     reasoning/tools/memory (Phase 5: conversation endpoint, placeholder reasoning)
services/reachy-hub/         robot registry + sessions, proxy to reachy-embodiment (Phases 4-5)
services/reachy-embodiment/  semantic behaviour API + presence loop (Phases 2-3)
clients/web-pwa/             web/PWA client (unimplemented)
shared/models/                Pydantic data contracts shared across services
shared/protocols/             HTTP route constants shared across services
deploy/homelab/                Docker Compose: companion-core, reachy-hub, postgres, caddy
deploy/reachy/                  Reachy-side deployment (unimplemented)
docs/                            plan, ADRs
```

## Dev setup

```
uv sync --all-packages
uv run python -c "from shared.models import AgentSession; print(AgentSession.model_json_schema())"
uv run --group dev pytest services shared
uv run --group dev ruff check services shared
```

Or run the whole stack for real — see [deploy/homelab](deploy/homelab/).
