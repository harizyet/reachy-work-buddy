# companion-core

Runs in the homelab. Owns: reasoning/tools, work memory, RAG, calendar/email/tasks,
proactive workflows.

Must not own: direct robot joints, UI transport (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 11)

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

**Phase 9**: `POST /conversation` now also returns a `privacy` field,
computed by `privacy_classifier.classify_privacy` — a keyword-based
placeholder (same honesty-about-scope as the rest of the reasoning here;
Phase 10+ replaces the classification logic, not the response contract).
companion-core only *proposes* this; `reachy-hub`'s response router (ADR
0006) has final, enforced authority over what actually happens with it —
see `services/reachy-hub/README.md`.

**Phase 10 (ADR 0010)**: real calendar. `calendar/` — `CalendarStore`
Protocol, `PostgresCalendarStore` (production; no external calendar
credential was available, so this is the working default, same
graceful-degradation pattern as Telegram/TTS), `InMemoryCalendarStore`
(tests). **This is companion-core's first database connection** — every
earlier phase was entirely stateless beyond the in-memory conversation
transcript.

- `POST /calendar/events` — operator/setup API (there's no external sync,
  so this is how events get in at all), not an agent tool.
- `GET /calendar/next`, `GET /calendar/events`, `GET /calendar/free-busy`
  (time blocks only, no event details — a narrower privacy surface than
  `/calendar/events`), `GET /calendar/reminders/due` — the agent's
  read-only surface, per docs/plan.md's Phase 10 row ("Read-only
  next/list/free-busy first; later writes behind confirmation").
- `POST /conversation` recognizes "what's next"-style queries
  (`calendar_intent.py` — a keyword placeholder, same honesty-about-scope
  as `privacy_classifier.py`) and answers with genuinely stored calendar
  data instead of the generic echo placeholder. The reply's `privacy` is
  set to `work-private` unconditionally when this fires — determined by
  the source (calendar content), not inferred from the query text the way
  the generic placeholder-reply path has to.
- **Verified live**: a real `docker compose` run, through Caddy, added a
  real event and got a real "what's next" answer back; companion-core's
  calendar data survived a container restart via Postgres persistence
  (first time this service has had anything to lose).

**Phase 11**: tasks/notes/reminders. `tasks/` — `TaskStore` Protocol,
`PostgresTaskStore` (production, same shared-Postgres-instance pattern as
`calendar/`), `InMemoryTaskStore` (tests). **Unlike calendar, capturing a
task genuinely is the agent action** — "Agent can record... explicit
follow-ups" (Phase 11's exit criterion) means `POST /conversation` itself
calls `TaskStore.add_task` directly, no separate admin/confirmation gate,
since recording a task is low-stakes and easily undoable (unlike a
calendar write, still admin-only, or an email send, Phase 14, which will
need one).

- `task_intent.py` — capture/list/complete/search phrase matchers (same
  placeholder honesty as `calendar_intent.py`): "remind me to X" / "add
  task X" captures; "what are my tasks" lists open ones; "complete task X"
  / "done with X" marks the first open task whose text contains X as done;
  "search tasks for X" finds matches regardless of status.
- `GET /tasks`, `POST /tasks`, `POST /tasks/{id}/complete`,
  `GET /tasks/search` — the direct API, for anything that isn't going
  through a conversation turn (e.g. a future web UI).
- Unlike calendar, task content isn't forced to any particular `Privacy`
  level — docs/plan.md §4's routing table calls out calendar/email
  specifically as privacy-sensitive; tasks aren't, so replies go through
  the normal `classify_privacy(text)` path like the generic placeholder
  reply.
- **Verified live**: recorded a follow-up conversationally, retrieved it
  in a later turn and via the direct API, completed and searched it
  conversationally, and confirmed task data (including completed status)
  survives a `companion-core` restart — through both a real running
  process and the full deployed `docker compose`/Caddy stack.

## Run it

```
uv sync --all-packages
REACHY_HUB_URL=http://localhost:8001 \
DATABASE_URL=postgresql://reachy:pw@localhost:5432/reachy_hub \
  uv run uvicorn companion_core.main:app --app-dir services/companion-core/src --reload
```

Or via the full stack — see [deploy/homelab](../../deploy/homelab/).

## Test

```
uv run --group dev pytest services/companion-core/tests
```

Tests chain companion-core through real (in-process) reachy-hub and
reachy-embodiment apps via nested `httpx.ASGITransport` — no mocks, no real
network. `test_whats_next_answers_from_real_calendar_data` is the direct
proof of Phase 10's exit criterion;
`test_agent_can_record_and_retrieve_a_follow_up` is Phase 11's.
`test_calendar_store.py`/`test_calendar_intent.py` and
`test_task_store.py`/`test_task_intent.py` unit-test the stores and
matchers in isolation (wrapped in `asyncio.run` — no `pytest-asyncio`/anyio
plugin is installed anywhere in this codebase, so a raw `async def
test_...` would silently no-op rather than fail). `PostgresCalendarStore`
and `PostgresTaskStore` themselves are exercised live (see
deploy/homelab/README.md), not by the unit test suite.
