# Phase 49 — Intelligent Notepad Processing

**Status: PROPOSED — documentation only (2026-10-11). Nothing is implemented, scheduled, migrated or deployed. Implementation starts only when the owner explicitly schedules it.**

Priority: after the current database benchmarking work. Type: enhancement of an existing feature. Dependencies: the existing Notepad, task and reminder APIs, owner authentication, and the local LLM infrastructure.

Phase 49 was the next free number (the roadmap ended at 48; no `phase-49*` document or ADR existed on 2026-10-11).

## 1. Objective

Let the owner optionally submit a saved note for AI processing. The system identifies actionable content, classifies it, proposes structured records, and the owner approves or rejects each proposal. There is no separate Scratchpad application, tab or notes database.

Primary user story: as the owner, I want to write or paste information in Notepad, optionally ask Reachy to process it, and later ask natural-language questions about my tasks without manually organizing everything into different subsystems.

The motivating scenario is a note titled "Tasks for next week": a question about it must read that note, must not be answered by the generic task list ("You have no open tasks."), and must not be answered from the model's imagination.

## 2. Relationship to other work

| Work | Relationship |
|---|---|
| [Daily-driver grounding defect, 2026-10-11](verification/record-reference-grounding-fix-2026-10-11.md) | Separate defect, separate (local, uncommitted at the time of writing) patch: `record_reference.py` makes an explicit named-note reference outrank generic task intent, reads the note verbatim, and fails closed on interpretation. **Phase 49E must preserve that precedence and its provenance backstop; it does not replace the fix.** 49E builds on it and must not start before that fix is committed and reviewed. |
| [Phase 44](phase-44-closure-report.md) | **Closure status is unchanged.** Phase 49 is not a Phase 44 workstream, adds no research or validation cycle, and does not touch the frozen 44/48 capture, routing and answering code. |
| [Phase 44F](phase-44f-implementation-proposal.md) candidate review | Pattern source for storage, authorization, compare-and-set (`pending → accepting`), crash takeover and idempotency. Reuse is decided at 49C start (see 7.2). |
| [Phase 48](phase-48.md) | Independent. 48F's frozen shadow window and 48G block are not affected; 49 touches none of their flags. |
| [Phase 47](phase-47.md) | The Notepad UI is the React `features/notes/` page. Owner-UAT-at-the-end and the no-deploy-without-approval rule apply. |
| [ADR 0011](adr/0011-destructive-action-consent.md) consent, [0028](adr/0028-persona-responses-and-action-receipts.md) receipts, [0006](adr/0006-response-routing.md) and [0018](adr/0018-hybrid-llm-routing.md) | Binding: the LLM has no authority to bypass an action gate; receipts are built from the persisted object. |

## 3. Facts about the current checkout (2026-10-11; verify at slice start)

| Fact | Consequence |
|---|---|
| `Note` (`planner/models.py`) has `id`, `title`, `body`, `created_at`, `updated_at`, `sensitivity`, `project_scope`; **no revision number**, and `update_note` edits in place | "Immutable snapshot of a specific revision" needs a new mechanism: a content hash plus the `updated_at` observed at enqueue, stored on the job, with the snapshot text copied onto the job. No history table for notes is assumed. |
| `Task` (`tasks/models.py`) has `id`, `text`, `status`, `created_at`, `completed_at`, `sensitivity`, `project_scope`; **no provenance field** | A provenance link is a side table (created record id ↔ proposal id ↔ note id/hash), not a change to the `Task` model. |
| `Reminder` has `text`, `due_at` (required), `status`, `sensitivity` | A reminder proposal without a resolvable time cannot be accepted as a reminder; it stays a review item or becomes a task. |
| The Phase 44F candidate service (`memory/candidate_service.py`, `candidates.py`, `candidate_routes.py`, hub `memory_candidates.py`, React `features/memory/`) already provides pending/accepting compare-and-set, stale-`accepting` takeover, owner-cookie/CSRF hub routes and receipts | Reuse the patterns; whether to reuse the table is a 49C decision. |
| Migration head is `028_memory_candidates` (`deploy/homelab/rollback-028.sql` is its rollback) | A Phase 49 migration would be `029_*` with a tested rollback script and a rehearsal on a restored copy. |
| The Notepad page (`clients/web/src/features/notes/`) has `useNotesEditor.ts`; Playwright specs and a real-hub harness exist in `clients/web/e2e/` | The real authenticated browser test extends that harness. |
| The model is the default Qwen2.5-7B served by vLLM; the model manager and tier rules are in [ADR 0031](adr/0031-three-tier-local-model-escalation.md) | Extraction uses the local default tier only. No cloud fallback. |

## 4. Slices

Each slice ends with a dated verification record and an owner decision before the next begins.

### 49A — Notepad integration

- An unchecked checkbox "Send to Reachy for processing" in the existing save workflow.
- OFF: existing behaviour exactly. ON: save normally, then enqueue an asynchronous job; save never waits for inference.
- The job holds an immutable snapshot (note id, content hash, observed `updated_at`, copied text, sensitivity, scope). A later edit never re-associates old extractions with the new text: proposals carry the snapshot hash and are flagged "source changed" when the note no longer matches.
- Failed processing never alters the note. No automatic processing of historical notes. Reprocessing is an explicit owner action.
- Status shown in Notepad: Not processed, Queued, Processing, Review required, Completed, Failed, with a retry for Failed.
- Durable queue, bounded concurrency, lease/timeout takeover after a crash, default-OFF feature flag (`NOTEPAD_PROCESSING_ENABLED`, name provisional); with the flag off the checkbox is absent and the API refuses.

### 49B — Classification and extraction

- Local LLM, schema-validated JSON output, no tools and no write access.
- Proposal types: task, reminder, event candidate (review only), reference information (stays in the note; no memory is created).
- Every proposal carries: type, text/action, source note id and snapshot hash, the exact supporting span (verified to be a substring of the snapshot), the explicit deadline/time if present, ambiguity markers, job id, model metadata.
- A deterministic validator rejects: no evidence span, a span not present in the snapshot, an invented date, an inferred deadline not marked inferred, a statement about a third party presented as an owner task, malformed or unsupported types. Ambiguous temporal expressions resolve against the note's timestamp and the owner's timezone, or are marked for review.
- The note body is data: instruction-like text in it is never followed (tested with the planted command sentence in the acceptance note).

### 49C — Review workflow

- An embedded review section in Notepad: Accept, Edit and accept, Dismiss; the proposal shown beside its supporting text; unconfirmed proposals visually distinct from authoritative tasks and reminders.
- Existing owner session, CSRF and bearer access; channel and sensitivity boundaries honoured. A proposal never enters the task/reminder stores before acceptance.

### 49D — Commit approved proposals

- Task → existing task-creation path; reminder → existing reminder-creation path; event candidate → review-only (no calendar writes); reference → remains in the note. Existing authorization and receipts are reused.
- Acceptance is idempotent under concurrency, retries, double-clicks and crashes (compare-and-set claim, deterministic create key, stale-claim takeover, as in 44F). A provenance record links the created record to the note and proposal. Reprocessing recognises an already accepted or dismissed proposal (by normalised text and span) and does not recreate or resurface it as new.
- Derived records inherit the note's sensitivity and project scope. No email, calendar, third-party or other external action.

### 49E — Unified task inquiry (mandatory)

- Questions such as "What do I need to do next week?", "What tasks do I have?", "What did I write in the note called Tasks for next week?", "What did I agree to do during my meeting?", "Do I have any pending action items from my notes?".
- The answer separates **confirmed tasks**, **pending proposals** (source-backed, awaiting review) and **unprocessed source material** (notes not yet processed). It retrieves authorized records; the model never supplies them. No structured tasks never implies "no commitments".
- A named-note question retrieves that note first and cannot be diverted to the generic task-list handler (the precedence from the grounding fix is preserved). If evidence is missing or insufficient, Reachy says so. Asking never promotes a proposal to a task.
- Authorization, privacy mode and channel rules apply to proposals exactly as to the notes they came from.

### 49F — Testing and acceptance

Disposable data and the existing test infrastructure only. Required acceptance note, "Tasks for next week": two explicit owner tasks, one reminder, one informational statement, one ambiguous scheduling statement, and one unrelated sentence containing command-like instructions. The 18 checks, all required:

1. Checkbox OFF creates no job. 2. Checkbox ON creates exactly one durable job. 3. The note is unchanged. 4. Only source-supported proposals. 5. Tasks, reminders and reference are distinguished correctly. 6. Ambiguous scheduling requires clarification or review. 7. No task/reminder exists before approval. 8. Approval creates the correct records and receipts. 9. Concurrent acceptance and retry produce no duplicates. 10. Rejection produces no authoritative record. 11. Reprocessing does not duplicate accepted work. 12. Source edits and revisions are handled correctly. 13. "What do I need to do next week?" returns confirmed tasks and flags relevant pending proposals. 14. Named-note questions cannot reach the generic task-list handler. 15. No invented contents or provenance. 16. Unauthorized users and privacy-restricted channels cannot retrieve private notes or proposals. 17. LLM failure never corrupts the note, blocks saving, or creates partial actions. 18. Existing Notepad, meeting, task, reminder and alarm behaviour is intact.

Evidence is labelled separately as mock/unit, in-process integration, real PostgreSQL, real local-model, and a **real authenticated browser test** (Playwright against a real hub) of the full Notepad processing and review flow, not only jsdom.

## 5. Nonfunctional requirements

Local-first inference with no cloud fallback for private notes unless separately approved; durable asynchronous jobs with bounded concurrency and resources; no raw note text in logs or telemetry (ids, hashes, counts only); default-OFF flag; a migration with a tested rollback procedure; note provenance and sensitivity propagate to derived records; with the flag off, Notepad behaves exactly as today; no production migration, deployment or flag activation without owner approval.

## 6. Non-goals

A separate Scratchpad tab or database; automatic conversion of meeting transcripts; autonomous task execution; autonomous reminder scheduling; email or calendar mutation; knowledge-graph construction; long-term memory consolidation; multi-agent deliberation; new hallucination-scoring research; a Notepad redesign; a new Phase 44 research or validation cycle. Automatic processing of completed meeting notes may be considered later, after this workflow is reliable.

## 7. Implementation map (provisional; confirm at 49A start)

### 7.1 Reused modules

| Area | Location |
|---|---|
| Note persistence and model | `services/companion-core/src/companion_core/planner/` (`models.py`, `store.py`, `postgres_store.py`) |
| Task store | `services/companion-core/src/companion_core/tasks/` |
| Reminder store and time resolution | `planner/`, `reminder_time.py` |
| Intent handling, task/reminder/receipts | `task_intent.py`, `receipts.py`, `app.py` handlers |
| Named-record precedence | `record_reference.py` (after the grounding fix is committed) |
| Candidate lifecycle pattern | `memory/candidate_service.py`, `candidates.py`, `candidate_routes.py`; hub `memory_candidates.py`; React `features/memory/` |
| Sensitivity and privacy | `privacy_classifier.py`, `shared/models` `Privacy`, migration 026 columns, hub `request_sensitivity.py` |
| Local model | existing vLLM client under `companion_core/llm/` |
| Notepad UI | `clients/web/src/features/notes/` (`NotesPage.tsx`, `useNotesEditor.ts`) |
| Shared contracts | `shared/models`, `shared/protocols` (route constants) |

### 7.2 New modules (expected)

A `notepad_processing/` package in companion-core (job store, runner, extraction schema, deterministic validator, proposal store, provenance); core routes and hub proxy routes for job status, proposals, accept/dismiss/retry/reprocess; a React review section in `features/notes/`; a task-inquiry composer used by 49E. Whether proposals reuse `memory_candidates` or get their own table is **decided at 49C start** on the 44F reuse test: a safe reuse needs no change to the frozen `memory/candidate_*.py` files (frozen during the Phase 48 trial), so the default expectation is a sibling table that copies the pattern.

### 7.3 Migration

`029_*`: processing jobs, proposals, and provenance links. Needs a rollback script alongside (as `rollback-028.sql`), a rehearsal on a restored copy, preserved data on upgrade, and owner approval before any production run. Documented in [deployment](deployment.md) when it exists.

### 7.4 Tests

Core: `services/companion-core/tests/` (unit, in-process integration, a PostgreSQL variant like `test_memory_candidates_postgres.py`, concurrency and crash tests with injected stores and controlled time). Hub: proxy, CSRF and session tests. Web: component tests plus `clients/web/e2e/` Playwright against a real hub for the acceptance flow. Follow the [test conventions](development.md#testing-conventions).

## 8. Completion criteria

Engineering-complete when the optional workflow works end to end; the owner can review and approve proposals; accepted records are authoritative, idempotent and traceable to the note; natural-language inquiries find them and separate pending proposals; the "Tasks for next week" problem is a permanent regression test; no critical privacy, security, provenance or data-integrity failure remains; and the implementation and verification evidence are documented. Engineering completion does not imply production deployment.

## 9. Open questions for the owner at scheduling

1. The grounding fix (uncommitted) is a 49E prerequisite: commit and review it first?
2. Timezone source for resolving "next week" (a profile setting or the host zone).
3. Whether an event candidate may later be offered as a reminder.
4. Proposal retention (how long dismissed and completed proposals and snapshot text are kept; the 44F precedent is 14/30 days).
