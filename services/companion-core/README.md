# companion-core

Runs in the homelab. Owns: reasoning/tools, work memory, RAG, calendar/email/tasks,
proactive workflows.

Must not own: direct robot joints, UI transport (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 14)

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
— it stays exactly that; Phase 12 added a genuinely separate
`MemoryRecord`-backed store rather than promoting this transcript into one
(see Phase 12 below for why). Its only job
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

**Phase 12**: work memory. `memory/` — `MemoryStore` Protocol,
`PostgresMemoryStore` (production, same shared-Postgres-instance pattern as
`calendar/`/`tasks/`), `InMemoryMemoryStore` (tests). Every stored
`MemoryRecord` (`shared/models/memory.py`) carries provenance (`source`),
a `sensitivity` classification, and an optional `expires_at`, enforced at
read time only — no background cleanup job, same scope discipline used for
calendar reminders (Phase 10). `sensitivity` reuses `Privacy`
(`shared/models/response.py`, Phase 9) directly rather than the module's
original `Sensitivity` enum, which turned out to be a byte-for-byte
duplicate that had sat unused since Phase 0 until this phase gave the model
its first real implementation — consolidated while actually building this,
not a separate cleanup pass.

- Like Phase 11 tasks, capturing a memory genuinely is the agent action:
  `memory_intent.match_capture` recognizes "remember that X" and
  `POST /conversation` calls `MemoryStore.add_memory` directly, sensitivity
  classified via the existing `classify_privacy`.
- Recall ("do you remember X" / "what do you remember about X",
  `memory_intent.match_recall`) queries `MemoryStore.recall` — a targeted
  content search against durable storage — and *never* touches
  `conversation_store`. That's a structural guarantee, not just a
  behavioral one: the recall code path has no reference to the
  conversation transcript at all, which is what actually satisfies the
  exit criterion ("recalled later without transcript dumping") rather than
  merely producing a short reply that happens not to dump it today.
  `memory_intent.most_restrictive_privacy` sets the reply's `privacy` to
  the most restrictive sensitivity among the records returned — combining
  a sensitive fact with public ones in one reply is still a sensitive
  reply.
- `GET /memories`, `POST /memories`, `GET /memories/recall`,
  `DELETE /memories/{id}` — the direct API, e.g. for seeding profile facts
  up front rather than waiting for them to come up in conversation.
- **Verified live**: through the real deployed Caddy stack, a fact
  ("remember that my manager's email is alice@example.com") recorded
  conversationally, interleaved with an unrelated turn and a second
  unrelated fact ("I like green tea"), was recalled later with only the
  matching fact in the reply; the same record, same ID, survived a
  `companion-core` container restart via Postgres; `DELETE
  /memories/{id}` removed it and a second delete correctly 404'd.

**Phase 13**: RAG. `rag/` — `DocumentStore` Protocol, `PostgresDocumentStore`
(production, Postgres + the pgvector extension — docs/plan.md §8 names
pgvector as the starting vector store; `deploy/homelab`'s Postgres image
switched from `postgres:16-alpine` to `pgvector/pgvector:pg16`),
`InMemoryDocumentStore` (tests, plain Python cosine similarity, no
pgvector needed). No cloud embeddings key was available, so
`rag/embeddings.py` embeds locally with a small sentence-transformers
model (`all-MiniLM-L6-v2`, 384 dims, lazily loaded) — same
graceful-degradation-without-credentials pattern as Phase 8's local
STT/TTS.

- `rag/chunking.py` splits ingested content on markdown-style `#` headings
  for section provenance, then packs consecutive same-section paragraphs
  into ~800-char chunks; a document without headings just gets
  `section=None` chunks. No `page` field anywhere in this phase — nothing
  here parses PDFs, so a page number would be fabricated.
- Both store implementations take an injectable `embed_fn` (defaulting to
  the real model) specifically so unit tests don't have to load real
  ML weights — tests inject a deterministic fake bag-of-words embedder and
  get fast, repeatable cosine-similarity results; a `slow`-marked test
  pair (`test_real_embedding_model_*`) exercises the real model, same
  split as the presence/heartbeat loop tests AGENTS.md documents.
- `rag_intent.py` recognizes "search docs for X" / "what do the docs say
  about X" and `POST /conversation` answers from `DocumentStore.search`
  results. `rag_intent.format_answer` is what actually satisfies the exit
  criterion ("Answers identify their supporting document/section/page
  where available") — it always names the source document, and the
  section too when the retrieved chunk has one.
- `POST /documents` (operator/setup API, not an agent tool — nothing here
  crawls documents on its own), `GET /documents`, `GET /documents/search`
  — the direct API.
- **Verified live**, and two real-infrastructure-only bugs surfaced that
  every unit test missed (both fixed, see `rag/postgres_store.py`'s
  comments): an uncommitted `CREATE EXTENSION IF NOT EXISTS vector`
  inside the connection pool's per-connection `configure` callback left
  connections stuck in status INTRANS (fixed by running it once, on its
  own connection, before the pool opens); and a bare vector query
  parameter was sent as `double precision[]`, which pgvector's `<=>`
  operator doesn't accept against `vector` (fixed with an explicit
  `::vector` cast in the SQL). With both fixed: two documents ingested
  through Caddy, a time-off question correctly retrieved the Vacation
  Policy chunk (not the unrelated Expense Policy one) with its section
  named in the reply, and the same data survived a `companion-core`
  container restart via Postgres/pgvector.

**Phase 14**: email. `email/` — `EmailStore` Protocol, `PostgresEmailStore`
(production, same shared-Postgres-instance pattern as `calendar/`/
`tasks/`/`memory/`, two tables: received messages and drafts),
`InMemoryEmailStore` (tests). No external email credential was available,
so "read" means listing `EmailMessage`s seeded through `POST
/emails/received` (operator/setup API, same no-external-sync honesty as
calendar) — and "summarize"/"draft" don't attempt real writing either
(there's no LLM in this codebase yet); a draft's body is the user's text
verbatim, the same way "remember that X" (Phase 12) stores X verbatim.

- `email/models.py`'s `EmailDraft.status` (`draft` -> `approved` -> `sent`,
  or `rejected`) is the mechanism behind the exit criterion ("No code path
  sends mail without approval gate"), and `email/workflow.py`'s
  `send_approved_draft` is what makes it structural rather than a claim:
  it is the *only* function anywhere in this codebase that calls an
  `EmailSender`, and it always checks `status == APPROVED` first, raising
  `DraftNotApprovedError` otherwise — no sender call happens before that
  check, not "happens not to" but *cannot*, since there is exactly one
  call site and it's gated. Both `POST /emails/drafts/{id}/send` and the
  conversational "send draft X" path go through this one function.
- `email_intent.py` — same placeholder-matcher honesty as the other
  `*_intent.py` modules: "draft email to X about Y" creates a draft
  (Prepare tier, docs/plan.md §9 — no confirmation needed just to create
  a preview); "approve draft X" / "send draft X" match against pending/any
  drafts by recipient or subject substring.
- No cloud email API key was available either, so the real sender
  (`email/sender.py`) speaks plain SMTP directly via `aiosmtplib` — in
  `deploy/homelab`, to a local Mailpit container (a real SMTP protocol
  handshake, but no personal mailbox), not a cloud provider.
- Both store and sender are injectable at `create_app(email_store=...,
  email_send_fn=...)`, same pattern as `rag_store`'s `embed_fn` — tests
  inject a fake `send_fn` that records calls to a list instead of opening
  a real network connection, and assert that list stays empty whenever the
  gate should have blocked dispatch (`test_email_workflow.py`), not just
  that the right exception was raised.
- `POST /emails/received`, `GET /emails/received`, `POST /emails/drafts`,
  `GET /emails/drafts`, `POST /emails/drafts/{id}/approve`,
  `POST /emails/drafts/{id}/send` — the direct API.
- **Verified live**: through the real deployed Caddy stack, a draft
  created conversationally could not be sent before approval — confirmed
  against Mailpit's own message list staying empty, not just the HTTP
  reply — then, once approved, produced a real SMTP message that actually
  arrived in Mailpit; a second send attempt on the now-sent draft
  correctly 409'd; and the draft's data (including its `sent`/`approved`
  timestamps) survived a `companion-core` container restart via Postgres.

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
`test_agent_can_record_and_retrieve_a_follow_up` is Phase 11's;
`test_agent_can_remember_and_recall_a_work_fact_without_transcript_dumping`
is Phase 12's;
`test_agent_answers_conversationally_with_document_and_section_provenance`
is Phase 13's; `test_agent_cannot_send_email_without_approval` and
`test_email_direct_api_approval_gate` are Phase 14's — both check the
fake `send_fn`'s call list, not just HTTP status codes or reply text.
`test_calendar_store.py`/`test_calendar_intent.py`,
`test_task_store.py`/`test_task_intent.py`,
`test_memory_store.py`/`test_memory_intent.py`,
`test_rag_store.py`/`test_rag_intent.py`/`test_chunking.py`, and
`test_email_store.py`/`test_email_intent.py`/`test_email_workflow.py`
unit-test the stores, matchers, and (for email) the approval-gate workflow
in isolation (wrapped in `asyncio.run` — no `pytest-asyncio`/anyio plugin
is installed anywhere in this codebase, so a raw `async def test_...`
would silently no-op rather than fail).
`PostgresCalendarStore`, `PostgresTaskStore`, `PostgresMemoryStore`,
`PostgresDocumentStore`, and `PostgresEmailStore` themselves are exercised
live (see deploy/homelab/README.md), not by the unit test suite —
`test_rag_store.py` does have two `slow`-marked tests that load the real
embedding model, still in-process/no-Postgres, distinct from the
Postgres-only live verification.
