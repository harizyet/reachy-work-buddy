# companion-core

Runs in the homelab. Owns: reasoning/tools, work memory, RAG, calendar/email/tasks,
proactive workflows.

Must not own: direct robot joints, UI transport (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 4)

Minimal service proving the Phase 4 exit criterion end to end: companion-core
-> reachy-hub -> reachy-embodiment. `hub_client.py` wraps reachy-hub's robot
API; companion-core never talks to reachy-embodiment directly (ADR 0001,
ADR 0003).

The `/debug/robots/{robot_id}/state` and
`/debug/robots/{robot_id}/behaviour/{name}` routes are a stand-in for what
will eventually be an agent tool call — real reasoning, tool-calling,
memory, and RAG are Phases 10-14 and are not implemented yet. Don't build on
`/debug/*` as a stable API; it goes away once real tool-calling lands.

## Run it

```
uv sync --all-packages
REACHY_HUB_URL=http://localhost:8001 \
  uv run uvicorn companion_core.main:app --app-dir services/companion-core/src --reload
```

Or via the full stack — see [deploy/homelab](../../deploy/homelab/).

## Test

```
uv run --group dev pytest services/companion-core/tests
```

Tests chain companion-core through real (in-process) reachy-hub and
reachy-embodiment apps via nested `httpx.ASGITransport` — the full Phase 4
call chain, exercised with no mocks and no real network.
