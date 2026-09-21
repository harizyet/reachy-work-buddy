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

Phase 0 (architecture freeze) and Phase 1 (Jarvis reference baseline, documented
via static source analysis — see [docs/jarvis-baseline.md](docs/jarvis-baseline.md))
are done. No services are implemented yet — see
[docs/plan.md §6](docs/plan.md#6-implementation-roadmap) for the phase-by-phase
roadmap. Next up: Phase 2, `reachy-embodiment`'s HTTP behaviour API skeleton.

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
uv sync
uv run python -c "from shared.models import AgentSession; print(AgentSession.model_json_schema())"
```
