# reachy-work-buddy

Office work companion built on Reachy Mini: a homelab reasoning/session
control plane plus a Reachy-side embodiment service, decoupled so the robot
stays expressive even when the homelab is unreachable.

- [docs/plan.md](docs/plan.md) — full technical plan, roadmap, release targets.
- [docs/adr/](docs/adr/) — binding architecture decisions.
- [docs/jarvis-baseline.md](docs/jarvis-baseline.md) — Phase 1 reference baseline from the upstream Jarvis project.
- [shared/models/](shared/models/) — cross-service data contracts (`AgentSession`, `AgentResponse`, `MemoryRecord`, `EmbodimentCommand`).
- [shared/protocols/](shared/protocols/) — HTTP route contracts shared between services.

## Status

Phase 0 (architecture freeze), Phase 1 (Jarvis reference baseline, documented
via static source analysis — see [docs/jarvis-baseline.md](docs/jarvis-baseline.md)),
and Phase 2 (`reachy-embodiment`'s semantic behaviour HTTP API, running
against a simulated backend — see [services/reachy-embodiment](services/reachy-embodiment/))
are done. See [docs/plan.md §6](docs/plan.md#6-implementation-roadmap) for the
phase-by-phase roadmap. Next up: Phase 3, the offline/local presence and
fallback state machine.

## Layout

```
services/            companion-core, reachy-hub, reachy-embodiment (unimplemented)
clients/web-pwa/     web/PWA client (unimplemented)
shared/models/       Pydantic data contracts shared across services
shared/protocols/    HTTP route constants shared across services
deploy/homelab/      Docker Compose deployment (unimplemented)
deploy/reachy/       Reachy-side deployment (unimplemented)
docs/                plan, ADRs
```

## Dev setup

```
uv sync --all-packages
uv run python -c "from shared.models import AgentSession; print(AgentSession.model_json_schema())"
uv run --group dev pytest services/reachy-embodiment/tests
```
