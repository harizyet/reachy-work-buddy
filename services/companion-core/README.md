# companion-core

Runs in the homelab. Owns: reasoning/tools, work memory, RAG, calendar/email/tasks,
proactive workflows.

Must not own: direct robot joints, UI transport (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 5)

**Phase 4**: `/debug/robots/{robot_id}/state` and
`/debug/robots/{robot_id}/behaviour/{name}` — a stand-in for what will
eventually be an agent tool call, proving companion-core -> reachy-hub ->
reachy-embodiment end to end. Don't build on `/debug/*` as a stable API; it
goes away once real tool-calling lands (Phase 10+).

**Phase 5 (ADR 0002)**: `POST /conversation` is the real, stable contract
reachy-hub calls per turn. companion-core receives only a `session_id`,
`conversation_id`, a channel label, and text — never anything
channel-specific beyond that opaque label. `conversation.py`'s
`ConversationStore` is an in-memory per-session transcript, not real memory
(Phase 12 replaces it with a `MemoryRecord`-backed store); its only job
right now is proving companion-core is genuinely stateful and
channel-agnostic. The reply text itself
(`"(turn N via <channel>) heard: <text>"`) is placeholder reasoning — Phase
10+ replaces the body of that handler with a real agent, not the request/
response shape.

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
reachy-embodiment apps via nested `httpx.ASGITransport` — no mocks, no real
network.
