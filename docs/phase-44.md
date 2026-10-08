# Phase 44: Reachy Brain, semantic knowledge and context layer

Status: **proposed. Reconciled with the code and architectural decisions D1 to D7 recorded 2026-10-08; no implementation code yet, 44A awaits review of sections 4 to 7.** Depends on Phases 12 (memory), 13 (documents), 27/41/43 (meetings) and 42 (model tiers). Phase 33 (adversarial testing) requirements apply to retrieval and ingestion.

Phase 44 puts one retrieval and context layer above the stores Reachy already has, so a question can draw on memories, documents, meetings and planner data together. The stores stay authoritative; the index is a derived, rebuildable view. Retrieved text is untrusted data and cannot authorize anything ([ADR 0001](adr/0001-service-boundaries.md): LLM suggestion is not permission; [ADR 0011](adr/0011-destructive-action-consent.md); [ADR 0018](adr/0018-hybrid-llm-routing.md)). The full proposal (objective, invariants, stages 44A to 44H, evaluation, acceptance scenario, definition of done) was supplied by the owner on 2026-10-08; the proposal text is not kept in the repository, so this page is the record: sections 1 to 3 hold what the code looks like and the scope, sections 4 to 9 the design. The proposal's stage letters (44A to 44H) are kept.

## 1. What exists (verified against the code, 2026-10-08)

| Store | Where | Record | Search today | Sensitivity | Project scope | Time fields |
|---|---|---|---|---|---|---|
| Memory (12) | `memory/store.py`, `memory/postgres_store.py`, table `memories`, model `shared/models/memory.py` | `MemoryRecord`: `id`, `type` (profile/working/episodic), `content`, `source` (free text, e.g. `"conversation"`), `confidence`, `sensitivity` (`Privacy`) | `recall(query)`: substring (`ILIKE '%q%'`) over the whole phrase, no ranking, no embedding. Side effect: stamps `last_accessed` | per record | `project_scope` (free text, nullable) | `created_at`, `last_accessed`, `expires_at`, `forgotten_at` |
| Documents (13) | `rag/*`, table `document_chunks` (`VECTOR(384)`, no index), `shared/models/rag.py` | `DocumentChunk`: `id`, `document_id`, `document_title`, `section`, `content`, `source`, `chunk_index` | `search(query, top_k=3)`: cosine over all chunks (sequential scan), all-MiniLM-L6-v2 | **none** | **none** | `created_at` |
| Meetings (27/41/43) | `meetings/*`, table `meetings` (JSONB columns), model `meetings/models.py` | `Meeting` with `transcript_segments` (`{start,end,text}`), `aligned_segments`, `speaker_names`, `transcript_corrections` (overlay keyed by segment index), `summary`/`minutes` (`MeetingOutput`: text, `tier`, `generated_at`), `participants`, `key_terms`, `context` | none in the store. Phase 43 `outputs.relevant_lines` is keyword overlap over one attached meeting, in memory | none; the reply is labelled `WORK_PRIVATE` in `app.py` | `project_scope` (free text) | `started_at`, `created_at`, `updated_at` |
| Notes, reminders (planner) | `planner/*`, tables `notes`, `reminders` | `Note`: `title`, `body`; `Reminder`: `text`, `due_at`, `status` | `list_notes(query)` only | none | none | `created_at`, `updated_at` |
| Tasks | `tasks/*`, table `tasks` | `Task`: `text`, `status`, `completed_at` | list only | none | none | `created_at`, `completed_at` |
| Conversation | `conversation.py` (in-memory per session), durable `web_chats`/`web_chat_turns` | turns | n/a | per-reply `Privacy` carry (`reply_privacy`) | none | per turn |

Other facts that shape the design:

- **Every id is a free `TEXT` uuid, unique only inside its own table.** There is no global id and no cross-store foreign key.
- **There is no requesting identity in core.** Core is single-owner (planner and tasks say so; memory and documents have no user column). `identity` in the proposed `retrieve_context(...)` has nothing to filter on in core today. Identity and trust ([ADR 0024](adr/0024-owner-recognition-trust.md), `shared/models/trust.py`) live in the hub; sensitivity (`Privacy`) is the only access label the stores carry.
- **`Privacy` has three values** (`public`, `work-private`, `sensitive`) and is already reused by memory. It is the only sensitivity vocabulary; do not add another.
- **Documents carry no sensitivity, scope or deletion.** `POST /documents` and `GET /documents/search` are operator/setup APIs; the only conversational path is the `search docs for ...` prefix matcher in `rag_intent.py`, which returns the top chunk verbatim. No delete exists. There is no `page` field (nothing ingests PDFs).
- **Memory has soft delete and expiry** (`forgotten_at`, `expires_at`). The index must honour both, and a forgotten memory must leave the index promptly (ADR 0011 undo means `restore` must bring it back).
- **Meeting text is layered.** What a reader sees is `current_text(meeting, i)` (raw segment plus accepted correction) with `display_name` for speakers, via `outputs.transcript_lines`. Raw `transcript_segments` is the evidence and is never rewritten ([ADR 0030](adr/0030-meeting-speaker-names-and-reviewed-corrections.md)). Indexing must read through the overlay and cite the segment index so evidence stays recoverable.
- **Generated outputs are not evidence.** `summary`/`minutes` are model-written and carry `tier`; Phase 43 already labels them "may contain mistakes". They must index as a different `kind` with lower confidence than transcript segments.
- **Meeting speech stays local** ([ADR 0032](adr/0032-meeting-outputs-and-context.md) decision 4): with a meeting attached, `app.py` forces `LOCAL_ONLY` unless the owner picked the frontier model for that message. The context builder must carry this as a per-item rule, not a per-call flag.
- **Citations already exist in two shapes.** `shared.models.response.Citation` (`source`, `section`, `page`) for RAG; `[S1]` markers plus a Sources list for web results (Phase 43 note: the 7B often omits markers, the list is always shown). Phase 44 should extend `Citation`, not add a third shape.
- **Phase 43's meeting retrieval** is `outputs.relevant_lines` and `build_context`, called inline in `/conversation` (`app.py` around the `context_meeting_id` branch). It handles one explicitly attached meeting only. Nothing queries meetings the owner did not attach.
- **Embeddings:** 384-dim MiniLM, loaded lazily, CPU. pgvector is installed (`baseline.sql`); only `document_chunks` uses it, with no ANN index.
- **Existing tests and benchmarks:** stores use injected `embed_fn` fakes in tests; a real-model test is `slow`. A benchmark precedent exists at `services/companion-core/benchmarks/meeting_corrections`.

## 2. Decisions (owner, 2026-10-08)

These supersede the earlier recommendations in this page's first version where they differ (identity, Ossie scope, freshness, retrieval activation, entity timing).

| # | Decision |
|---|---|
| D1 | **Ossie: structural export only in 44A**, pinned to a verified spec version. Import deferred. Two boundaries: an Ossie adapter (analytical schemas, fields, joins, metrics the pinned spec supports) and a Reachy knowledge ontology (people, projects, decisions, evidence, relationships, temporal knowledge) that is independent of Ossie. No compatibility claim for knowledge-graph semantics the spec cannot express. Versioned adapter interface; a round-trip test only when import is supported. |
| D2 | **Explicit sensitivity at the authoritative source.** Add `sensitivity` where missing; existing and new unclassified records are `work-private`. Derived knowledge inherits source restrictions and is never silently downgraded. |
| D3 | **Transactional outbox, asynchronous indexing worker, periodic reconciliation.** Deleting, forgetting or revoking access takes effect at retrieval time even when indexing is behind. Idempotent, restart-safe. |
| D4 | **Selective, intent-driven retrieval**, not every turn. Explicit attachments and knowledge queries trigger it. Phase 43 behaviour is the benchmark baseline. The Phase 37 shadow router is not promoted without its own evaluation. |
| D5 | **Entities and relationships stay in Phase 44 as planned extensions**, implemented only if the hybrid benchmark shows a need. Extension contracts are defined now; no graph database. Source timestamps and current-state filtering from the start; explicit `superseded_by` reasoning deferred. |
| D6 | **`AccessContext`** replaces both `identity` and a bare sensitivity ceiling in the retrieval contract: authenticated principal, sensitivity ceiling, project scope, processing-destination restrictions. Built by trusted application code, never from model output or request bodies. |
| D7 | **Composite source references** `(source_type, source_id, locator)` plus source version/revision where available. |
| D8 | **`project_scope` is added** (nullable) to documents, notes and tasks in migration 026. `NULL` means *unscoped*, never public and never "every project". While Reachy is single-owner, an unscoped record is owner-accessible subject to its sensitivity; once project-scoped access control exists, unscoped records need an explicit access policy. Scope is never inferred (not by migration, not from model output). |
| D9 | **The entity gate is an investigation trigger, not an implementation trigger.** B1 recall@5 below 0.80 on the relationship or cross-source category (at least 10 frozen cases each) starts an investigation. B2 is built only if error analysis shows unresolved entities or aliases are a material cause, simpler remedies (lexical aliases, query rewriting, ranking) were evaluated first, and the evidence says relationship expansion would solve what remains. B2 is then a separate owner decision. Report Wilson intervals; do not read small differences as conclusive. |
| D10 | **Migration 026 ships with 44A, independent of the index**, with its own acceptance gate (section 9). Migration 027 stays in 44B. |
| D11 | **Retrieval has three states behind two flags, default disabled** (section 8). Shadow mode never touches live context, responses or actions and obeys the same access and retention rules. Promotion needs explicit owner approval after benchmark and security acceptance. |

**Non-negotiable for 44B:** retrieval-time source revalidation. Every candidate is re-checked against its authoritative store at retrieval (exists, visible, current sensitivity and scope), and its text comes from the store. The outbox keeps the index fresh; revalidation is what stops a stale entry surviving a forget, deletion or reclassification. 44B is not accepted without it.

## 3. Scope

### Committed (44A to 44E)

| Stage | Delivers |
|---|---|
| 44A | Contract models (section 4), source sensitivity/scope migration 026, pinned Ossie structural export, and the benchmark fixtures and harness (section 7) with the two Phase 43 baselines, all with tests. No index, no worker, no retrieval. Actual retrieval benchmarking starts with 44B/44D. |
| 44B | Index table and outbox (migration 027), indexing worker, reconciliation, source adapters for memory, documents, meetings, notes, tasks and reminders, source-state resolution at retrieval. **Built locally 2026-10-08; see section 11b.** |
| 44D | Hybrid retrieval (lexical, pgvector, metadata and temporal filters) with `AccessContext` enforcement, run against the benchmark. Intent-driven activation (section 8). |
| 44E | ([implementation plan](phase-44e-plan.md), under review) Context builder: budget, dedup, sensitivity and destination filtering, provenance, current-versus-historical labelling, source diversity. Same structured bundle for FAST, DEEP and CLOUD. |
| 44F | Conversational memory capture through a **candidate and review mechanism** (section 3.1): casual conversation never becomes authoritative memory on its own. Plan only; no code before the revised plan is reviewed. |
| 44H (security subset) | Adversarial and leakage tests for everything above. Runs with 44D/44E, not after. |

(The proposal's stage letters are kept; 44C is conditional, below.)

### Conditional (only after the investigation and owner decision in section 7.4)

44C entities, aliases, resolution and relationships; 44F2 extraction of facts, decisions and topics from meetings and documents (needs 44C; it reuses 44F's candidate and review mechanism and is never automatic).

### 3.1 44F: conversational memory capture (roadmap, 2026-10-08; plan only)

**Rule: casual conversation must not silently become authoritative memory.** Today a memory is written only by an explicit owner act: a parsed "remember ..." phrase on the `memory.capture` handler (it stores the owner's own words with `source="conversation"`) or `POST /memories`. 44F keeps that and adds a way to *propose* memories from ordinary conversation, where every proposal is a **candidate** that does nothing until the owner accepts it.

**Candidates are not memory.** A candidate lives in its own table (`memory_candidates`, a later migration). It is excluded from `recall`, from the knowledge index, from retrieval, from context bundles, from the model prompt and from Ossie export. The only thing that ever reads candidates is the review surface.

| Field | Meaning |
|---|---|
| `text` | The proposed memory, short, in the owner's words where possible. |
| `provenance` | Conversation id, turn index and channel, plus whether it came from a rule or a model (name and version). A pointer, not a copy of the transcript. |
| `proposed_type`, `proposed_scope` | Profile, working or episodic; a project scope only if the conversation named one. |
| `sensitivity` | Classified at proposal time; the stricter of the classifier and any context label wins; anything that looks sensitive is `sensitive` and local-only. Unknown is `work-private`, never `public`. The owner can raise or lower it at review, and the decision is recorded. |
| `confidence` | Recorded for sorting the queue; it never accepts anything. |
| `status` | `pending`, `accepted`, `edited-accepted`, `rejected`, `expired`, `suppressed`. |
| `created_at`, `expires_at` | Pending candidates expire on their own (proposed default 14 days) and are then deleted, keeping only a count. |
| `supersedes` | If an existing memory covers the same ground, the review shows "would replace" or "conflicts with", never overwrites. |

**Owner controls (all in 44F's scope).** Capture is off by default (`MEMORY_CANDIDATES_ENABLED=false`) and has its own pause: privacy mode, a shared or non-private channel, and any turn classified `sensitive` generate no candidates at all. A review queue lists candidates with their provenance, proposed classification and expiry. The owner can accept, edit then accept, reject, or reject with "do not propose this again" (a suppression rule). "Delete all candidates" and "forget everything proposed from this conversation" exist. Review is reachable from the web UI and from text-only commands; there is no spoken accept, and nothing is accepted by default, by timeout, by silence or by confidence. Destructive confirmation stays text-only (ADR 0011).

**What accepting does.** Accept calls the existing `add_memory` path with the final text, type, scope and sensitivity the owner confirmed, `source="candidate:<id>"`, and an expiry (a default for working and episodic memories; none for profile only if the owner says so). The acceptance is logged as a receipt like other memory writes. The candidate keeps its provenance link for as long as the memory exists, so "why do you know this?" has an answer, and forgetting the memory forgets the link.

**How candidates are proposed.** Local-only. First deterministic patterns ("I prefer", "my X is Y", "from now on") on the final owner utterance, after the reply is sent, off the critical path, rate-limited, never from assistant text or from retrieved or attached content (so an injected instruction in a document or meeting cannot create a candidate). A model-based extractor runs only if it is evaluated first on a labelled set of conversations and the owner approves it; it uses the local 7B only, never a cloud model, and its output goes through the same candidate path. Neither can call an action, change a gate or write memory.

**Gates for 44F.** Zero candidates from privacy mode, shared channels, sensitive turns, assistant text or injected content (adversarial cases); zero memories created without an explicit accept (checked by comparing the memory table before and after a long scripted conversation); candidate precision and the number of candidates per hour measured on owner-reviewed conversations, with the owner deciding if the noise is acceptable; expiry, suppression, delete-all and provenance verified; retention of candidates documented. Needs the owner's review of this section before any code. 44F does not depend on 44C and does not start before 44E is accepted.

### Deferred

Ossie import and round trip; explicit `superseded_by` reasoning, `disputed`/`unverified` classification (44G); conversation history as a source; external connectors; any graph database; autonomous retrieval on every turn; changing the model router.

## 4. Revised 44A contract

Python/pydantic in `companion_core/semantic/` (not `shared/models` until a second service needs it, the Meeting and Task precedent). Names are proposals for review.

```python
class SourceRef(BaseModel, frozen=True):
    source_type: Literal["memory", "document", "meeting", "note", "task", "reminder"]
    source_id: str                 # the store's own id
    locator: str | None = None     # meeting: segment index or "summary"/"minutes"; document: chunk_index
    source_version: str | None = None   # see section 5.3; None when the source cannot supply one

class Provenance(BaseModel, frozen=True):
    ref: SourceRef
    title: str | None = None       # document title, meeting title
    section: str | None = None     # document section
    page: int | None = None        # always None until a source can supply one
    speaker: str | None = None     # meeting display name
    start_seconds: float | None = None
    authority: Literal["source", "model_generated"]   # meeting summary/minutes are model_generated

class KnowledgeItem(BaseModel, frozen=True):
    ref: SourceRef                 # identity of the item; its string form is the index key
    kind: Literal["memory", "document_chunk", "meeting_segment", "meeting_summary",
                  "meeting_minutes", "note", "task", "reminder"]
    text: str                      # always read from the source at resolution, never from the index
    provenance: Provenance
    sensitivity: Privacy           # shared.models.response.Privacy; max(index copy, source now)
    local_only: bool               # meeting-derived items: true (ADR 0032)
    project_scope: str | None
    confidence: float              # memory.confidence; 1.0 for source text; lower for model_generated
    observed_at: datetime | None   # source time: meeting started_at/created_at, created_at otherwise
    valid_from: datetime | None
    valid_until: datetime | None   # memory expires_at maps here; other sources None
    extensions: dict[str, Any] = {}   # namespaced ("entity.refs"), reserved for 44C/44F; never read by core retrieval

class AccessContext(BaseModel, frozen=True):
    principal: str                 # authenticated owner id from the hub
    sensitivity_ceiling: Privacy
    project_scopes: frozenset[str] | None   # None = no scope restriction; set = only these plus unscoped
    destinations: frozenset[Literal["local", "deep_local", "cloud"]]
    channel_private: bool          # False on shared speakers (ADR 0006)

class ContextBundle(BaseModel, frozen=True):
    items: list[KnowledgeItem]
    dropped: dict[str, int]        # reason -> count (forgotten, expired, over_ceiling, out_of_scope, destination, budget)
    max_sensitivity: Privacy       # of items actually included
    local_only: bool               # True if any included item is local_only; caller must route locally
    token_estimate: int

async def retrieve_context(query: str, access: AccessContext, source_filters: SourceFilters | None = None,
                           token_budget: int | None = None, *, temporal: Literal["current", "include_historical"] = "current") -> ContextBundle
```

Rules:

1. **AccessContext is issued, not supplied.** A factory in trusted core code (`access_for_owner(...)`) builds it from hub-authenticated request context and the channel's privacy; destinations come from the routing mode and the owner's per-message frontier choice (the only way `cloud` enters `destinations` while meeting items are in play). It is never a field of a request model, tool schema or model output; a test asserts this by walking every pydantic request model and OpenAPI schema. It is frozen; there is no mutator, and widening means constructing a new one in trusted code.
2. **Nothing is shown without passing three filters at retrieval:** the source still exists and is visible (not forgotten, expired, deleted, cancelled), the item's current sensitivity is within `sensitivity_ceiling` (`max` of the index copy and the source now, so an index entry can never downgrade), and its scope and destination are permitted. Failures are counted in `dropped`, never returned.
3. **`local_only` propagates up.** The bundle reports it; the caller uses it to force the local route, extending ADR 0032 decision 4 from "an attached meeting" to "any included meeting-derived item". The builder does not choose models.
4. **`text` is resolved from the source.** The index stores match material only, so a stale index can surface a candidate but never stale text.
5. **Entity extension point.** Candidate generation is a `CandidateSource` protocol (`async def candidates(query, access, filters) -> list[Candidate]`). Lexical and vector search are the first two; entity/relationship expansion, if built, is a third that returns refs plus a reason. `extensions` and the protocol are the only places 44C touches the contract. No entity tables are created in 44A to 44E.
6. **Time.** `temporal="current"` excludes items past `valid_until`; `include_historical` returns them labelled. `observed_at` orders and recency-weights results. No `superseded_by` field exists yet; adding it later is additive.

Reserved, not implemented (documented only so the shapes are agreed): `EntityRecord(id, kind, canonical_name, aliases, refs)` and `RelationshipRecord(id, subject_id, predicate, object_id, evidence: list[SourceRef], confidence, observed_at, valid_from, valid_until)`. Evidence is a list of `SourceRef`, so extracted knowledge always points back to immutable source text.

### Ossie boundary (D1)

`semantic/ossie/export.py` produces one Ossie document describing Reachy's stores: each queryable table as a `dataset` (`name`, `source`), its columns as `fields` (`name`, `expression`), and a small set of `metrics`. Joins are emitted only for real keys that exist (there are almost none; `document_chunks.document_id` has no parent table). Reachy-only concepts (sensitivity, confidence, validity, evidence) go in `custom_extensions` with `vendor_name` such as `REACHY`, `data` a JSON string, and are documented as opaque to other tools. The adapter pins one spec version string, validates its output against the schema vendored at a pinned upstream commit (after checking the Apache 2.0 NOTICE obligations), and fails closed on an unknown version. Test: golden file plus schema validation. The ontology package does not import the adapter, only the reverse.

## 5. Migration implications

The next revision is `026`; `SCHEMA_REVISION` in `shared/database.py` must change with each, and each follows the [schema upgrade procedure](deployment.md#schema-upgrades-and-credential-keys) (dump, stop writers, migrate, rebuild core together). Both are additive; nothing is dropped or rewritten.

### 5.1 Migration 026, `source_sensitivity` (44A)

| Table | Change |
|---|---|
| `document_chunks` | `sensitivity TEXT NOT NULL DEFAULT 'work-private'`, `project_scope TEXT` |
| `notes`, `tasks`, `reminders` | `sensitivity TEXT NOT NULL DEFAULT 'work-private'`; `project_scope TEXT` on notes and tasks |
| `meetings` | `sensitivity TEXT NOT NULL DEFAULT 'work-private'` (it already has `project_scope`) |
| `memories` | none (already has both) |

`NULL` `project_scope` means unscoped (D8): it is not public and not "every project". The migration never sets a scope; every existing row gets `project_scope = NULL` and `sensitivity = 'work-private'`. Existing rows take the default, which is the conservative backfill. A check constraint limits values to the three `Privacy` strings. Code changes that follow: models and both store implementations (in-memory and Postgres) gain the field; `POST /documents` and note/task creation accept an optional `sensitivity` (and scope); an edit never lowers sensitivity implicitly; no UI is required in this phase, but the existing operator and Android clients must keep working when the field is absent. Open assumption to confirm: `project_scope` on documents, notes and tasks is added in the same migration because `AccessContext.project_scopes` has nothing to filter on otherwise. Documents are classified per chunk row because no `documents` table exists; ingest sets all chunks of a document identically.

`classify_privacy(text)` (a heuristic) may suggest a value at capture, as memory capture does today, but a suggestion is never lower than the default for an item the owner did not classify. This is decided here so that "unclassified means public" cannot creep in via the heuristic: the classifier may only raise, not lower.

### 5.2 Migration 027, `knowledge_index` (44B)

```
knowledge_items
  ref_key TEXT PRIMARY KEY            -- "source_type:source_id#locator"
  source_type, source_id, locator, kind
  source_version TEXT NOT NULL        -- hash, see 5.3
  match_text TEXT NOT NULL            -- what was embedded/searched; not returned to callers
  tsv TSVECTOR                        -- generated, GIN index
  embedding VECTOR(384)               -- HNSW index (cosine); NULL until embedded
  embedding_model TEXT NOT NULL
  sensitivity TEXT NOT NULL, project_scope TEXT, local_only BOOLEAN NOT NULL
  observed_at, valid_from, valid_until TIMESTAMPTZ
  indexed_at TIMESTAMPTZ NOT NULL

knowledge_outbox
  id BIGSERIAL PRIMARY KEY
  source_type, source_id, op TEXT      -- 'upsert' | 'delete'
  enqueued_at, attempts INT, next_attempt_at, locked_until, last_error, done_at
  UNIQUE (source_type, source_id) WHERE done_at IS NULL    -- coalesces repeated edits
```

The `vector` extension and the 384-dimension convention already exist; only `document_chunks` uses vectors today. Existing `document_chunks.embedding` is reused for documents so chunks are not embedded twice (decision for 44B: either index references it or copies it; copying is simpler and the table is rebuildable).

### 5.3 Source versions

A version is a hash of exactly what the index depends on: the visible text (after overlays), sensitivity, scope, validity and visibility state. This avoids adding `updated_at` columns: memories and tasks have none, notes and meetings do. `meetings.updated_at` is bumped by every overlay write I checked (speaker names, corrections, key terms, outputs, title, status), so it is a valid cheap coarse version for reconciliation scans, with per-segment hashes used inside the worker.

## 6. Outbox, worker and reconciliation design (44B)

```
store write (one transaction)
  ├─ source row change
  └─ INSERT knowledge_outbox (source_type, source_id, 'upsert')   -- ON CONFLICT DO NOTHING while pending
        │
        ▼
indexing worker (core background task, like MeetingWorker)
  claim: SELECT ... FOR UPDATE SKIP LOCKED, set locked_until
  read the CURRENT source state (not the event payload)
  compute source_version; skip if the index already has it
  upsert match_text/tsv/embedding/metadata, or delete the rows if the source is gone/forgotten
  mark done_at; on error: attempts+1, exponential next_attempt_at, last_error; poison after N attempts (visible in health)
        │
        ▼
periodic reconciliation (startup, then hourly; bounded batches)
  per source type: list (source_id, coarse version) from the source and the index
  enqueue missing or stale; delete index rows with no source; flag embedding_model mismatches
  report counts (missing, stale, orphaned) for the health endpoint and logs
```

Properties:

- **Same-transaction enqueue.** Each Postgres store method that changes indexed state calls one shared helper with its own connection, so a rolled-back change leaves no event and a committed change cannot lose one. The in-memory stores take an optional injected in-memory outbox so unit tests keep the existing injected-store convention.
- **Idempotent and order-insensitive.** The event only says "look at this source"; the worker reads current state, so replays, duplicates and out-of-order processing converge. Pending events coalesce per source. Meeting overlays (a correction typed on one line) re-embed only segments whose hash changed.
- **Restart recovery.** Leases expire (`locked_until`), so a crashed worker's claim is retried; `done_at IS NULL` rows survive restarts.
- **Immediate exclusion without waiting for the worker.** Two mechanisms, both required: (a) the mutating delete, forget and cancel paths also remove the index rows for that source synchronously in the same transaction (a keyed delete, no embedding, so it is cheap); (b) every retrieval resolves its candidates against the source adapters in one batched query per source type and drops anything missing, forgotten, expired or over the ceiling (`ContextBundle.dropped`). Restoring a forgotten memory enqueues an upsert; until the worker runs it is simply not retrievable, which fails safe.
- **Backpressure.** Embedding runs in a thread executor in small batches, behind the same CPU the voice path uses; the worker yields while a conversation turn is in flight. This is a measured requirement in the 44B gate, not an assumption.
- **No new route** is added for indexing. A read-only status (queue depth, oldest pending age, failed count, last reconciliation) is exposed through the existing health/diagnostics surface only if 44B needs it.

## 7. Benchmark methodology (fixed before 44D)

Location and style follow `services/companion-core/benchmarks/meeting_corrections` (`cases.json`, `run.py`, README, dated record under `docs/verification/`).

### 7.1 Corpus and cases

A committed **synthetic** corpus written for the benchmark (a few meetings as segment lists with speakers and one correction overlay, documents with headings, memories of each type including an expired and a forgotten one, notes, tasks, one older superseded fact, and documents containing injected instructions). No real recording or private data is committed. Cases are written before any tuning and split into a **tuning set** and a **frozen holdout** that is scored once per decision point (the shadow-router holdout precedent).

Each case: `id`, `category`, `question`, `access` (an AccessContext fixture), `expected_refs` (set of `SourceRef` that must be retrieved), `forbidden_refs` (must not appear), `expected_facts` (strings for the answer check), and `notes`. Categories from the proposal: single-source, cross-source, relationship (entity resolution across sources), temporal (current versus older), contradiction, provenance, security (injection, cross-project, over-ceiling, cloud destination, forgotten and expired sources), and a negative class (questions with no answer in the corpus, which should return nothing relevant).

### 7.2 Systems compared

| System | Description |
|---|---|
| `B0` | Today: `MemoryStore.recall` substring, `DocumentStore.search` top-k, Phase 43 `relevant_lines` for an attached meeting, planner `list_notes(query)` |
| `B1` | Hybrid baseline: lexical plus vector plus metadata, scope, temporal and `AccessContext` filters, no entities |
| `B2` | `B1` plus entity resolution and relationship expansion; exists only if the gate in 7.4 is met |

### 7.3 Metrics

Retrieval-only (no model): recall@k and precision@k at k=3,5,10, MRR, source-attribution accuracy (right `source_type` and `source_id`), citation correctness (right locator: segment, section, chunk), temporal accuracy (current preferred over older), negative-case false-positive rate, context token count, and latency p50/p95 for retrieval and for context build (reported with sample counts and host load, per the measurement caution in HANDOVER).

Answer-level (a fixed local model, temperature 0, same prompt for all systems): fact presence by exact normalised string match against `expected_facts`, and cited-source correctness derived from the retrieval metadata, never from model-written citations. Retrieval quality and model quality are reported separately; an answer-level run is optional per stage.

Security, hard gates: **unauthorized leakage = 0 and injection-driven action = 0** across all cases, tested at the retrieval and bundle level (forbidden refs absent; `local_only` set whenever a meeting item is included; no action path reachable from retrieved text). A single failure blocks the stage regardless of recall.

Because the corpus is small, report counts with Wilson 95% intervals, not bare percentages, and state that results measure the approach on a synthetic corpus, not real-world accuracy. Add genuine cases from real use as they surface (owner-approved, redacted).

### 7.4 Gates (proposed thresholds, for owner confirmation)

- **44D done:** `B1` beats `B0` on recall@5 in the cross-source and temporal categories on the holdout, matches `B0` on single-source, passes the security hard gates, and meets a latency budget to be set from the first measurement (retrieval p95 and context-build p95 are recorded, not guessed here).
- **Investigate entities (44C/B2) when** on the holdout `B1` has recall@5 below 0.80 on the relationship or cross-source category with at least 10 frozen cases. This opens an investigation only. B2 is proposed only if (a) error analysis shows unresolved entities or aliases are a material cause of the misses (not chunking, embedding quality, ranking or missing data), (b) simpler remedies (lexical aliases, query rewriting, ranking changes) were evaluated and the remaining gap is documented, and (c) the evidence suggests relationship expansion would close it. Building B2 is then a separate owner decision. At 10 cases per category 0.80 is coarse: report Wilson 95% intervals and do not treat small differences as conclusive.
- **44E done:** the same `ContextBundle` drives FAST, DEEP and CLOUD fixtures with no retrieval logic inside providers; token budget respected exactly; destination and ceiling filters verified by the security cases.

## 8. Retrieval activation (D4)

Retrieval is a read-only step that adds a delimited, data-not-instructions block to the generic chat branch, like Phase 43. Two flags give three operating states; both default to off, and there is no further feature-management machinery:

| State | Flags | Behaviour |
|---|---|---|
| Disabled | `KNOWLEDGE_RETRIEVAL_ENABLED=false` | Existing behaviour unchanged. No retrieval runs. |
| Shadow | `KNOWLEDGE_RETRIEVAL_ENABLED=false`, `KNOWLEDGE_RETRIEVAL_SHADOW=true` | Candidates are retrieved and evaluated for measurement only. They are never added to model context, replies, consent or actions. The shadow path builds the same `AccessContext`, applies the same revalidation and filters, and keeps only what the shadow-router retention rule allows (aggregates and refs, no retrieved text kept beyond the run, files destroyed after evaluation). |
| Enabled | `KNOWLEDGE_RETRIEVAL_ENABLED=true` | Results may influence answers, subject to access controls. Needs explicit owner approval after benchmark and security acceptance. |

Triggers, all deterministic:

1. **Explicit context:** an attached meeting (existing flow, always pinned into the result set) and, later, owner-selected documents.
2. **Explicit commands and existing prefixes:** `search docs for`, memory recall, and notes search keep working and may route through the shared retriever once it exists.
3. **Knowledge-question rule:** a deterministic matcher in the style of `should_search_for_meeting_question` for phrasings such as "what did we decide about X", "what do my notes say about X". Questions about the time, weather, chit-chat or an action request do not match. The rule is evaluated on the benchmark's negative class so its false-trigger rate is measured.

A lightweight classifier may replace item 3 only after its own evaluation; Phase 37's shadow router and its trial data are not reused or promoted for this. Deterministic handlers, consent gates and the action boundary are unchanged: a retrieval block adds context to a model reply and never authorizes or triggers an action (ADR 0001, 0011). Prompt placement (system versus user role) and the exact delimiter are settled in 44E with the injection cases as the test.

## 9. Acceptance gates by stage

| Stage | Gate |
|---|---|
| 44A contracts | Contract models import without side effects, are frozen, and `AccessContext` is absent from every request model and OpenAPI schema (tested); unit tests for filtering helpers |
| 44A Ossie | Export validates against the schema vendored at the pinned commit and matches its golden file; unknown version fails closed; ontology package does not import the adapter |
| 44A migration 026 (separate gate, deployable alone) | Fresh install and upgrade from 025 on a disposable pgvector database; conservative backfill verified on seeded rows (`work-private`, `NULL` scope, nothing inferred); existing CRUD and HTTP APIs for memory, documents, notes, tasks, reminders and meetings unchanged for clients that omit the new fields; positional/explicit-column SQL in each store audited and covered by tests; legacy adoption path still passes; recovery documented and verified with a dump taken before upgrade and a restore into a disposable database; backward behaviour of an old core image against the new schema recorded (the schema-revision check refuses it, so core, hub and migrate are rebuilt together). **Applying it to the live homelab needs a separate owner approval, a verified backup, and the repository deployment procedure.** |
| 44B | **Retrieval-time source revalidation implemented and tested (non-negotiable).** Index and outbox migration 027 verified on disposable Postgres; crash-and-restart test (kill the worker mid-batch, nothing lost or duplicated); reconciliation repairs a deliberately damaged index; forget, delete and expiry are excluded immediately with the worker stopped; embedding load measured against a concurrent voice turn |
| 44D | Section 7.4 gate; no new endpoint beyond what the owner approves |
| 44E | Section 7.4 gate; injection and destination cases pass |
| 44F | Section 3.1 gates: no candidate from privacy mode, shared channels, sensitive turns, assistant text or injected content; no memory without an explicit accept; candidate noise and precision reviewed by the owner |
| 44H subset | Zero leakage and zero injection-driven actions across the security category; imported semantic data is not accepted anywhere (import deferred) |
| Phase | Real-process check on the homelab stack (not only mocks) before any "works end to end" claim, labelled separately from simulator and fixture evidence |

## 10. Open items for the owner

Resolved 2026-10-08: `project_scope` added (D8), entity gate refined (D9), migration 026 with 44A (D10), retrieval default off with shadow mode (D11). Remaining before 44B: approval to apply migration 026 to the homelab (separate, after a verified backup), the benchmark latency budget once measured, and the index freshness load limits from the 44B measurement.

## 11. 44A implementation and acceptance record (2026-10-08)

Status: **committed (`bdc9efd`) and deployed to the homelab 2026-10-08 (migration 026 applied; [record](verification/phase-44a-deployment-2026-10-08.md)); the robot acceptance gate is pending.** Applying it needs the owner's separate approval of a date, a verified dump and the prepared [runbook](deployment.md#applying-migration-026-phase-44a---runbook-prepared-and-not-executed). The stale voice-test fixture was fixed in its own commit (`0c146f0`). 44A is closed for development. Dated evidence: [Phase 44A verification](verification/phase-44a-2026-10-08.md).

| Part | Where |
|---|---|
| Contracts and access rules | `companion_core/semantic/model.py`, `access.py` |
| Migration 026, `SCHEMA_REVISION = "026_source_sensitivity"` | `migrations/versions/026_source_sensitivity.py`, [`shared/database.py`](../shared/database.py) |
| Store and API changes | models and in-memory/Postgres stores for documents, notes, tasks, reminders, meetings; optional `sensitivity`/`project_scope` on core `POST /documents`, `/tasks`, `/notes`, `/reminders` and the `POST /meetings` form. An edit (`PUT` task or note) that carries either field is refused with 422. |
| Hub | `POST /planner/tasks`, `/planner/notes`, `/planner/reminders` and `POST /meetings` forward the fields; the hub's edit routes refuse them like core's. The hub has no document route: documents are classified through core's operator/setup API only (tested). The web and Android clients do not send the fields yet, so what they create is `work-private` and unscoped. |
| Ossie structural export | `companion_core/semantic/ossie/` (`mapping.py`, `export.py`, `validation.py`, vendored schema, `LICENSE`, `NOTICE`, `SOURCE.md`). `jsonschema` is now a runtime dependency of companion-core (in `uv.lock`; the `--no-dev` image install resolves it), so validation works wherever an export is produced. Nothing exposes an export over HTTP yet. |
| Benchmark | `services/companion-core/benchmarks/knowledge_retrieval/` ([README](../services/companion-core/benchmarks/knowledge_retrieval/README.md)): corpus, 25 development and 44 frozen holdout cases, `kbench` harness, baselines `b0` and `b0-oracle`, recorded reports in `results/`, holdout log |
| Tests | `test_semantic_contract.py`, `test_ossie_export.py`, `test_source_sensitivity.py` (Postgres checks opt-in), `test_knowledge_benchmark.py`, hub `test_classification_is_forwarded_on_create_and_refused_on_edit` and `test_documents_are_core_only_by_design` |

Pinned to Apache Ossie commit `8dd6732da354f22ca71f16d82626a46039ecdcd9` (spec `0.2.0.dev0`, draft). From the pinned schema: an expression is `{"dialects": [{"dialect", "expression"}]}`; relationships are foreign keys between datasets; `is_time` is only a role flag; extensions are `{vendor_name, data}` with `data` a JSON string. The upstream repository also has ontology converters, but they convert ontologies *into* this dataset model, which supports D1 rather than changing it. The export emits no relationships (the stores declare no foreign keys), has no import module, lists no meeting transcript, audio or generated-text fields, and carries no `ai_context`.

### Benchmark composition

| | |
|---|---|
| Corpus | 13 memories (1 forgotten, 1 expired, 1 superseded, 1 sensitive, 3 that conflict with another source), 5 documents (an archived older version, a sensitive postmortem, a vendor note with a planted instruction), 4 meetings (140-segment weekly sync, a spoken instruction, a sensitive HR check-in, an accepted ASR correction), 4 notes, 4 tasks, 2 reminders, 5 access profiles, entity aliases |
| Development set | 25 cases: 6 single-source, 5 cross-source, 4 relationship, 3 temporal, 1 contradiction, 1 provenance, 3 security, 2 negative |
| Frozen holdout | 44 cases: 6 single-source, 10 cross-source, 10 relationship, 4 temporal, 2 contradiction, 2 provenance, 6 security, 4 negative; fixture hash recorded in `fixtures.lock.json`; one look per decision point, logged in `holdout_runs.jsonl` |
| Metrics | recall@3/5/10, precision@3/5/10, MRR, source attribution@5, citation correctness@5, full-recall@5 and pooled recall@5 with Wilson 95% intervals, temporal accuracy, negative false-positive rate, exposed leakage by reason (gated) and unfiltered candidates (diagnostic), planted-text exposure, action-boundary probes, read-only check, returned tokens, retrieval latency p50/p95; retrieval only, no model. Two tracks: `synthetic-deterministic` and `production-embedding` |

### Baseline (holdout, decision point `44A-baseline`, deterministic bag-of-words embedder)

| System | recall@5 | full recall@5 (Wilson 95%) | relationship / cross-source full recall@5 | negative false positives | leaked hits (cases) |
|---|---|---|---|---|---|
| `b0` (today's lookups) | 0.16 | 4 of 36 (0.04 to 0.25) | 0 of 10 and 0 of 10 | 4 of 4 | 11 (8) |
| `b0-oracle` (every source, every meeting attached, word overlap) | 0.85 | 28 of 36 (0.62 to 0.88) | 6 of 10 and 8 of 10 | 3 of 4 | 104 (17) |

Both baselines left every store unchanged, and the action-boundary probes (an obedient model shown a spoken and a document-borne instruction) changed nothing. Leakage in the baselines is expected: they have no access control, and gates apply to B1 and later. The oracle already reaches most single-source and cross-source cases, so the benchmark's headroom is in relationship, provenance and security cases.

### Review round (2026-10-08, after the first acceptance report)

- **Case-level review.** [All 44 holdout cases](verification/phase-44a-holdout-case-review-2026-10-08.md): query, access context, expected references with the text they point to, exclusions, rationale, what each baseline returned (marked expected, other part of the right source, unneeded, stale or unauthorized) and the scoring outcome. It is generated from the recorded reports by `review.py`; no system was run and the holdout log still holds its two original entries. A test keeps the committed file identical to what the recorded results produce.
- **Exposure versus candidates.** A retrieval system can now return a `Retrieval(exposed, candidates)`. Only `exposed` (what the caller or model would receive) feeds the leakage gate, which stays at zero tolerance. `candidates` is a diagnostic: it reports how many unauthorized items were considered and how many a filter rejected before exposure. A plain list (both baselines) counts as exposed and reports no candidates. The scoring of the existing runs is unchanged: re-running both baselines on the development set reproduces the recorded digests, and a test enforces that.
- **Production-embedding track.** The same fixtures and baselines scored with the real `all-MiniLM-L6-v2` (the app's document embedder), reported as track `production-embedding` and never combined with the synthetic scores. It uses in-memory exact cosine; an opt-in test shows that ranking is identical to `PostgresDocumentStore` on real pgvector for all 69 questions. The frozen holdout was scored once on this track under its own decision point (owner-approved 2026-10-08).

  | Development set (n = 25, 21 with sources) | synthetic `b0` | production `b0` | synthetic `b0-oracle` | production `b0-oracle` |
  |---|---|---|---|---|
  | recall@5 / precision@5 / MRR | 0.21 / 0.09 / 0.22 | 0.26 / 0.10 / 0.28 | 0.74 / 0.24 / 0.73 | 0.74 / 0.24 / 0.73 |
  | full recall@5 (Wilson 95%) | 3 of 21 (0.05 to 0.35) | 4 of 21 (0.08 to 0.40) | 14 of 21 (0.45 to 0.83) | 14 of 21 (0.45 to 0.83) |
  | leaked hits exposed | 3 | 16 | 23 | 23 |
  | retrieval latency p50 | 0.1 ms | 9 ms | 2.5 ms | 13 ms |

  The real model helps today's document lookup a little (one more case fully recovered, an interval that overlaps the synthetic one) and exposes more unauthorized documents, because a semantic top-3 reliably reaches the sensitive postmortem. It changes nothing for the oracle, whose ranking is word overlap. On this corpus the large gap between `b0` and `b0-oracle` is about which sources are searched, not about how documents are embedded; the evidence for 44B is therefore "does one index over every source close that gap", not "does MiniLM beat a hash".

  Then the single frozen-holdout look, scored on its own decision point and never combined with the synthetic holdout scores:

  | Frozen holdout (n = 44, 36 with sources), decision point `44A-production-embedding-baseline` | synthetic `b0` | production `b0` | synthetic `b0-oracle` | production `b0-oracle` |
  |---|---|---|---|---|
  | recall@3 / @5 / @10 | 0.13 / 0.16 / 0.22 | 0.22 / 0.25 / 0.31 | 0.70 / 0.85 / 0.90 | 0.70 / 0.84 / 0.90 |
  | precision@5, MRR | 0.07, 0.16 | 0.14, 0.30 | 0.37, 0.73 | 0.36, 0.72 |
  | full recall@5 (Wilson 95%) | 4 of 36 (0.04 to 0.25) | 5 of 36 (0.06 to 0.29) | 28 of 36 (0.62 to 0.88) | 27 of 36 (0.59 to 0.86) |
  | pooled element recall@5 | 8 of 67 (0.06 to 0.22) | 15 of 67 (0.14 to 0.34) | 57 of 67 (0.75 to 0.92) | 56 of 67 (0.73 to 0.91) |
  | relationship / cross-source full recall@5 | 0 of 10 / 0 of 10 | 0 of 10 / 0 of 10 | 6 of 10 / 8 of 10 | 6 of 10 / 7 of 10 |
  | unauthorized hits **exposed** (cases affected) | 11 (8) | 30 (21) | 104 (17) | 104 (17) |
  | exposed, by reason | 9 over ceiling, 2 out of scope | 28 over ceiling, 2 out of scope | 85 over ceiling, 13 out of scope, 6 destination | the same |
  | negative questions that returned something | 4 of 4 | 4 of 4 | 3 of 4 | 3 of 4 |
  | retrieval latency p50 / p95 | 0.09 / 0.15 ms | 8.2 / 9.4 ms | 2.5 / 2.9 ms | 8.2 / 9.1 ms |

  Read each row on its own. Retrieval relevance and access control are separate questions, and the real model moved them in opposite directions for today's document lookup: pooled recall rose (8 to 15 of 67 expected references) while the number of unauthorized documents it exposed nearly tripled (11 to 30, in 21 cases instead of 8), because a semantic top-3 reliably reaches the sensitive and out-of-scope documents. The intervals overlap on every full-recall figure, so the one-case gains and the oracle's one-case loss (28 to 27) are not differences to act on. Neither baseline is access-controlled, so neither passes the leakage gate; the gate applies to B1 and later. This was a single look: the scores are preserved as recorded, the holdout log lists it, and nothing is tuned against it.

  **These are measurements on a small synthetic corpus whose cases were written and labelled by the agent that built the harness. They are not evidence of real-world retrieval quality.** The labels are provisionally reviewed, pending independent inspection by the owner.
- **The unexplained embodiment failure is explained and fixed.** `test_voice::test_multi_turn_conversation_through_hub_and_core` has failed since commit `a1843a3` (2026-10-07), which made a lone "hello reachy" or "Hey Reachy" mid-conversation get a short affirmation instead of a model reply, and updated the hub's version of the test fixture to "how are you today" but not the embodiment copy that still scripts "hello reachy". The first utterance is now acknowledged (by design) and is not a conversation turn, so the second reply says "turn 1". This is a stale test fixture, not a voice regression: changing the two script lines in that test makes all 27 voice tests pass on a clean checkout. It was fixed in a separate test-only commit (`0c146f0`) using the hub test's own request, "how are you today"; the test still checks that two spoken turns share one conversation, the half-duplex state order, and that nothing restarts the microphone by itself.
- **Pre-commit checks** (no commit made): diff read in full; no debug code, leftover prints or TODOs in added lines; secret scan (patterns for private keys, cloud and chat tokens, JWTs, key assignments, home paths and non-example e-mails, plus an entropy check) over about 27,000 added lines in 66 files found only a false positive (a deliberately fake `example.com` address) and path-like strings; no secret-named files; `uv.lock` is purely additive (four packages, all PyPI, all MIT); the vendored Ossie schema is Apache-2.0 with its LICENSE and NOTICE kept beside it; the existing web and Android clients send only the fields they edit, so the new edit-time refusal does not affect them.

### 44A acceptance

| Gate | Status |
|---|---|
| Contracts and access rules | Met: frozen types, composite references, `AccessContext` absent from every HTTP schema (tested), narrowing cannot widen |
| Migration 026 | Met on a disposable server: upgrade from 025 with seeded rows, conservative backfill, SQL that ignores the new columns, store round trips, dump, upgrade, restore and re-upgrade. **Not applied to the homelab.** |
| Ossie structural export | Met: validates against the pinned schema, golden file, fails closed on any other version or a tampered schema, runtime `jsonschema` |
| Classification through hub and clients | Met by design and test: hub forwards on create, refuses on edit, documents are core-only. Gap: the web and Android UIs have no control for it |
| Benchmark harness | Met: validated and frozen fixtures, B0 baselines on two tracks, scoring, Wilson intervals, exposed-versus-candidate leakage, probes, reproducible digest, holdout protocol, 44 harness tests (one needs Postgres) |
| Case-level review of the holdout | Produced; labels are **provisionally reviewed, pending independent owner inspection** |
| Repository failures kept visible | Met: 2 failing tests (one now explained as a stale fixture) plus 1 flaky, each reproduced on a clean checkout; no regression found |
| Deployment | **Software deployment done, passed and accepted by the owner 2026-10-08 (2 minutes' downtime; Telegram receipt confirmed); physical robot acceptance pending (the robot was offline).** The [rehearsal](verification/phase-44a-rehearsal-2026-10-08.md) passed on an isolated restored copy. A [runbook](deployment.md#applying-migration-026-phase-44a---runbook-prepared-and-not-executed) is prepared, not run: rehearsal on a restored copy, verified dump, rollback images, ordered stop, backup, build, migrate, start, twelve smoke tests, rollback criteria. Gates: owner approval of a date, a verified dump, `migrate`, core and hub rebuilt together; clients do not yet set classification |

### Readiness assessment

44A is complete as a local implementation and ready to commit on your approval. It is not ready to deploy, and 44B should not start until the case review is accepted. What it establishes: the contracts and access rules, classification at the source (migration 026, held back), a structural Ossie export, and a way to measure retrieval that existed before any retrieval was built. What the numbers say so far: today's behaviour recovers every expected source in about 1 of 9 holdout cases, searching every source with keyword overlap recovers about 3 of 4, and neither respects access rules. What they do not say: whether an index or hybrid retrieval closes the remaining gap, how any of it behaves on real data, or how robust the system is against injection (see below).

Remaining risks and limits:

- `AccessContext` is controlled by review and a schema test, not a language guarantee, because in-process code can construct one.
- The corpus is small, synthetic and keyword-friendly, and it was written by the agent that built the harness. The oracle already scores well on lexical cases, so a B1 improvement here does not prove one on real data, and a small difference is not a result.
- **Injection resistance is only sampled.** Two action-boundary probes (a spoken instruction in an attached meeting, a poisoned document lookup) show that nothing changed when an obedient model saw the text. That does not establish robustness to indirect prompt injection. The flows that carry stored text into a prompt are few today (attached meeting, document lookup), and the probes cover them; 44E must add probes for every new path that puts retrieved text in a prompt, with poisoned memories, notes, tasks and documents, before retrieval is enabled.
- **The holdout is the first version and will be outgrown.** Ten relationship and ten cross-source cases are an initial gate, not a basis for an architecture decision. Planned additions, as new fixture versions that start new baselines rather than edits to this one: paraphrased queries, ambiguous entities (two people with one first name), noisy ASR transcripts, and distractor documents that are related but wrong. Case sets should grow from real, redacted questions with the owner's approval.
- No answer-quality evaluation exists; the cases carry `expected_facts` for it.
- The golden file guards against drift, not against a wrong mapping.

## 11b. 44B: unified index, outbox and revalidation (2026-10-08)

Status: **built and tested locally; not committed, not deployed.** The homelab database is at 026; this work moves the repository to revision `027_knowledge_index`, so an image built from it refuses to start against the live database until 027 is applied (same pattern as 026, with the [runbook](deployment.md#applying-migration-026-phase-44a---runbook-prepared-and-not-executed) and the extra notes under [Schema upgrades](deployment.md#schema-upgrades-and-credential-keys)). Nothing searches the index and no retrieval flag exists yet; the worker is off unless `KNOWLEDGE_INDEXING_ENABLED` is true (compose default `false`). Evidence: [Phase 44B verification](verification/phase-44b-2026-10-08.md).

**One design change from section 6.** The outbox is filled by database triggers on the source tables rather than by a helper called from every store method. A trigger runs in the same transaction as the change, cannot be forgotten by a new code path, and also covers any other writer; it let the stores stay untouched except for read-by-id methods. Triggers also delete a record's index rows in the same transaction when it is forgotten, deleted, cancelled or failed, so exclusion never waits for the worker. Expiry (the passage of time) is handled by revalidation and reconciliation. A trigger fires only for columns that affect the index, so a read that stamps `last_accessed` or a reminder's `notified_at` queues nothing.

| Part | Where |
|---|---|
| Migration 027: `knowledge_items` (match text, `tsvector`, `vector(384)` with GIN and HNSW indexes, classification, scope, validity), `knowledge_outbox` (one row per source, with a generation counter), the triggers, a backfill that queues existing records. Undoable and safe to apply again (`rollback-027.sql`, `downgrade`). | `migrations/versions/027_knowledge_index.py`, `deploy/homelab/rollback-027.sql` |
| Source adapters: how memory, documents, meetings (corrected text and speaker names, never the raw transcript; summaries marked model-written at confidence 0.5), notes, tasks and reminders describe themselves, with a version hash of everything an index row or a retrieval depends on | `companion_core/knowledge/sources.py` |
| Index and outbox, in memory and on Postgres (`SKIP LOCKED` claims, leases, backoff, set-aside after 8 failures, revived by a new change) | `knowledge/index.py`, `knowledge/outbox.py` |
| Worker: change detection by version, embedding only changed text in batches of 16 on a worker thread, reconciliation (missing, stale, orphaned, expired, wrong embedding model), a loop that reconciles at start and hourly, start-up behind the flag | `knowledge/worker.py`, `knowledge/runtime.py` |
| **Retrieval-time revalidation**: each candidate is re-read from its store; existence, visibility, the stricter of the index and source classification, scope, destination and ceiling are applied; text and provenance come from the source; drops are counted by reason | `knowledge/revalidate.py` |
| Store additions (read by id): `MemoryStore.get_any`, `DocumentStore.get_document` and `list_document_ids`, `TaskStore.get_task`, `PlannerStore.get_note` and `get_reminder` | the stores |
| Measurement of the indexing load | `benchmarks/knowledge_retrieval/indexing_load.py` |

Bugs the tests found while building it: the worker loop swallowed cancellation and could not be stopped; a `--clean` restore of a pre-027 dump fails once the index tables exist (so the recovery order is now: run `rollback-027.sql`, then restore); and a change arriving while a source is being synced would have been deleted by that sync's completion (hence the generation counter).

### 44B acceptance (section 9 gates)

| Gate | Status |
|---|---|
| Retrieval-time revalidation implemented and tested (non-negotiable) | **Met.** Parametrised stale-index cases (forgotten, deleted, expired, cancelled, part removed), reclassification the index has not seen, stricter label wins, scope, destination, ceiling, historical mode, unknown parts, one read per source; the same against a stale Postgres index. Three deliberate breakages of the module (skip visibility, trust the index label, skip the access context) are each caught by the tests. |
| Migration 027 verified on disposable Postgres | **Met.** Applied on a seeded 026 database, repeated, undone two ways (alembic and the SQL file) and applied again, applied over leftovers, and the 026 recovery test still passes with the new recovery order. Not yet rehearsed on a restored production copy or applied to the homelab. |
| Crash-and-restart: nothing lost or duplicated | **Met.** A claim abandoned by a dead worker is retried after its lease; a concurrent change during a sync is not lost (generation guard); 24 sources processed by two concurrent workers are each synced exactly once. |
| Reconciliation repairs a deliberately damaged index | **Met** (deleted row, stale version, orphan, expiry, empty index after a restore), in memory and on Postgres. |
| Forget, delete and expiry excluded immediately with the worker stopped | **Met** for forget, delete and cancel (the trigger removes the rows in the same transaction) and for expiry and reclassification (revalidation), on Postgres. |
| Deployment readiness for 027 | **Rehearsed on a restored production copy, measured, and deployed 2026-10-08 with `KNOWLEDGE_INDEXING_ENABLED=false`** ([deployment record](verification/phase-44b-deployment-2026-10-08.md)). [Rehearsal record](verification/phase-44b-rehearsal-2026-10-08.md): migration 1.75 s, trigger overhead 0.2 to 0.4 ms per write, index storage about 4.5 KB per part, rollback in 0.09 s, the real write paths verified, retention reviewed. |
| Embedding load measured against a concurrent voice turn | **Partly met.** Measured: 400 segments with the real MiniLM embedded in about 1 to 2 s, event-loop stall under 2 ms while embedding, and torch's default 14 threads were slower than 2 on the development host, so core now sets 2 (`KNOWLEDGE_EMBED_THREADS`). Not measured: contention with the speech, language and diarization services on the homelab. The controlled test is prepared (`tools/knowledge_contention_test.py`, self-tested against stub servers) and needs the owner's approval to run. |

Not built in 44B, by design: search or candidate generation (44D), the context builder (44E), entities, any retrieval flag or route, a UI. Indexing the homelab's real records has not been run.

## 11c. 44D: retrieval configurations (development, 2026-10-08)

Status: **built and benchmarked on the development split; local; nothing wired or deployed; the frozen holdout not scored.** Evidence: [Phase 44D development comparison](verification/phase-44d-dev-2026-10-08.md).

| Part | Where |
|---|---|
| Candidate search: PostgreSQL full-text (OR of stemmed words, `ts_rank_cd`) and pgvector cosine (HNSW with iterative scan), with the caller's access applied as a pre-filter from the index labels (never relied on) and an in-memory test double | `knowledge/search.py` |
| Retriever: B1a lexical, B1b lexical + vector fused by reciprocal rank (k = 60), B1c cross-encoder reranking of the **authorised** survivors; every configuration revalidates against the stores under the trusted `AccessContext`; pinned sources (an attached meeting) as an extra candidate list; query cleaning (NUL, length); the 44A `ContextRetriever` call with a token cap; a trace of candidates and per-stage timings | `knowledge/retrieval.py` |
| Contract: `SourceFilters.pinned_sources` (additive) | `semantic/model.py` |
| Benchmark adapters for the five PostgreSQL variants on a fresh database per run, with an automatic holdout guard (`KBENCH_HOLDOUT_APPROVAL`), exposure/candidate/drop accounting, CPU, memory and stage timings | `benchmarks/knowledge_retrieval/kbench/b1.py`, `pg_env.py`, `b1_sensitivity.py` |

**First look at the frozen holdout (decision point `44D-first-look`, owner decision D12; B1a and B1b scored once each, B1c excluded):** [record](verification/phase-44d-first-look-2026-10-08.md). R@5 0.83 (B1a) and 0.86 (B1b) against 0.84 for keyword overlap over everything and 0.25 for today's lookups, with **no exposure** for either and the baselines exposing 104 and 30; B1b's MRR is 0.075 higher (interval just excluding zero), no other difference separates them. Relationship is the weak category (B1a 2 of 10, B1b 5, oracle 6). Not decided: whether vectors justify their cost.

Result in one line (development split): B1a (lexical) reaches R@5 0.86 and MRR 0.66 at 8 ms median; B1b (hybrid) R@5 0.79, MRR 0.80 at 28 ms with several times the CPU and memory; B1c is not justified; no variant exposed anything unauthorised. Gate status for 44D: authorization held in every run, the holdout is pending an approved candidate and decision point, answer quality is not evaluated, and production activation is not part of this stage.

## 12. Verification of this page

Documentation checks: facts read from the repository on 2026-10-08 (stores, models, `baseline.sql`, migrations 001 to 026, `shared/database.py`, the meeting store's `updated_at` writes, the `/conversation` meeting-context branch, the Phase 43 helpers the baselines call, ADRs 0001, 0011, 0030 and 0032) and the Ossie spec and schema at the pinned commit; relative links and heading anchors were checked by script. Automated results and the baseline-versus-regression evidence are in the [verification record](verification/phase-44a-2026-10-08.md). All of it is fixture and disposable-Postgres evidence: nothing was run against the homelab database, the robot or a model.
