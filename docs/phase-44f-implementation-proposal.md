# Phase 44F: focused implementation proposal (deterministic memory candidates, owner review, receipts, exclusions, retention) — PROPOSAL, 2026-10-10

**Status: proposal for owner review. Nothing is implemented. Migration 028, any code and any UI need a separate owner approval; 44F stays separately gated from 44E (its own flags, no shared state).** Source specification: [phase-44.md §3.1](phase-44.md#31-44f-conversational-memory-capture-roadmap-2026-10-08-plan-only) and the [slice table](phase-44f-implementation-slices.md); this page narrows them to the first usable milestone (slices 0 to 3 plus candidate retention) and checks them against the code as it is today. Out of scope here: worthiness, placement, connection links, re-entry, curiosity, a model-based extractor.

## 1. What the code gives us today (checked 2026-10-10)

| Fact | Consequence for 44F |
|---|---|
| Memory is written only by an explicit owner act: the `memory.capture` handler for "remember …" (stores the owner's words, `source="conversation"`, keyword-classified sensitivity, writes a `memory.created` receipt) or `POST /memories` | The candidate path must end in the same `add_memory` call and the same receipt type; "remember …" keeps working unchanged and never creates a candidate |
| Receipts are built from the persisted object, never reply wording (ADR 0028); `memory.created` exists; a failed receipt never undoes the action | Reuse `memory.created` with a "from a reviewed suggestion" field; no new receipt type or schema |
| Forgetting a memory is a soft delete behind a text-only SINGLE-scope confirmation; `request_confirmation` refuses BULK unconditionally (ADR 0011) | "Delete all candidates" cannot reuse that mechanism; see decision D3 |
| A turn carries `channel`, `input_modality`, `context_meeting_id`; there is **no privacy-mode field** and no per-turn "shared speaker" flag; a spoken turn is treated as a shared speaker everywhere in 44 | Exclusions must be derived from these trusted fields; privacy mode needs a hub lookup that fails closed (dependency, section 3) |
| The `memories` table has an index-enqueue trigger (migration 027) | The candidate table must have **no** trigger and no foreign key into the index; only an accepted memory is indexed, and only when indexing is separately enabled |
| Memory content is plaintext in PostgreSQL (the keyring protects secrets, not memories) | Candidate text has the same at-rest status; retention and backup scope matter more (section 5) |
| No memory screen and no hub route exist ([phase-47.md](phase-47.md)); the React client plan reserves `features/memory/`; Phase 47 is owner-UAT-at-the-end with no backend change or deploy without approval | The review surface needs core routes, hub proxy routes (owner cookie and CSRF) and a UI, and is the longest-lead item |
| Migration head is `027_knowledge_index`; the 44E flags are off and absent from Compose | 028 is new and must be rehearsed on a restored copy; 44F flags follow the same rule |

## 2. Design

**Flags (both default false, neither in Compose, independent of every 44E flag):** `MEMORY_CANDIDATES_ENABLED` (store, review routes, retention job) and `MEMORY_CANDIDATES_CAPTURE_ENABLED` (proposing; requires the first). The review surface can therefore be exercised with an empty queue before any capture runs, and capture can be paused without removing review.

**Store (migration 028, rollback script alongside).** `memory_candidates`: `id`, `text` (≤ 400 chars; cleared when the candidate leaves `pending`), `rule_id` and `rule_version`, provenance pointer (`conversation_id`, `session_id`, `turn_index`, `channel`; a pointer, never a transcript), `proposed_type`, `proposed_scope`, `sensitivity` (floor `work-private`), `status` (`pending`, `accepting`, `accepted`, `edited-accepted`, `rejected`, `expired`, `suppressed`), `text_hash` (sha256 of the normalised text, for duplicate and suppression matching), `memory_id` (set on accept), `created_at`, `expires_at`, `decided_at`. `memory_candidate_suppressions`: `text_hash`, `rule_id`, `created_at` only (no text). `memory_candidate_counters`: expired, rejected and suppressed counts by day. CHECK constraints on status, sensitivity and length. No trigger, no foreign key to `knowledge_items`, excluded from `recall`, the index, retrieval, context bundles, prompts and export by construction (a different table that only the review code reads).

**Deterministic proposals (slice 2).** A small versioned rule set on the owner's final utterance, run in a background task **after** the reply is final (the 44E shadow pattern: constant-time offer, bounded queue, per-job timeout, own counters, never raises, cannot alter or delay a reply). First rules, each with an id and a positive and negative test set: standing preference ("I prefer X to Y", "I always/never X"), standing instruction ("from now on X", "going forward X"), personal fact ("my X is Y"), naming ("call me X"). A candidate is created only when **all** hold:
- the message is one short owner sentence (≤ 2 sentences, ≤ 400 characters, no line breaks beyond one, no code fence, no URL, no quoted block): a pasted document or a planted instruction cannot match, because the pattern must cover the whole message;
- not a question, hypothetical ("if", "would", "should I"), report of someone else's words, or negation-only;
- the turn was answered by the ordinary conversation path (no handler claimed it), so "remember …", tasks, reminders and commands never double-capture;
- the text is not already a pending candidate, a suppression, or an existing memory (normalised hash match), and the hourly and daily caps (proposed 5 and 20) are not reached.

**Exclusions, enforced at capture from trusted turn state only (not at review):** spoken turns (shared speaker); any channel not on an owner-authenticated text allow-list (configured, default to be inventoried at F2 start); a slash command; an attached meeting; privacy mode on, or unknown (hub lookup, cached a few seconds, **fail closed**); a turn whose text the keyword classifier labels `sensitive` (no candidate, no row, one aggregate counter only); anything derived from assistant text, retrieved records, documents or meetings (the only input is `turn.text`, the owner's own message). Unknown sensitivity is `work-private`, never `public`.

**Review (slice 3).** Core routes behind the existing internal-service trust: list pending, accept (optionally with edited text, type, scope, sensitivity, expiry), reject, reject-and-never-propose-again (writes a suppression), forget-everything-from-one-conversation. Hub proxy routes use the existing owner cookie and CSRF; none is reachable from `/conversation` or the voice path, so **a spoken turn cannot accept** anything; typed `/` commands (`/candidates`, `/accept`, `/reject`) are optional and typed-only (Phase 24c), added last. Nothing is accepted by default, timeout, silence, confidence or edit.

**Accept (the only path to memory).** (1) compare-and-set `pending → accepting`; (2) validate the final text (length, the classifier re-run; the owner may raise sensitivity freely, lowering below the classifier is allowed only with an explicit recorded flag); (3) existing `add_memory(content, source="candidate:<id>", type, scope, sensitivity, expires_at)` with a default expiry for working and episodic memories; (4) set `accepted` or `edited-accepted`, `memory_id`, clear the candidate text; (5) write the `memory.created` receipt (existing mechanism: failure is logged and never undoes the accept) with a field saying it came from a reviewed suggestion and whether the text was edited. A crash between (1) and (4) leaves `accepting`; a start-up reconciliation marks it `accepted` if a memory with `source="candidate:<id>"` exists and otherwise reverts it to `pending`. A second accept returns a conflict.

## 3. Dependencies and risks

- **Privacy-mode signal:** the turn lacks it; core must ask the hub (a getter may need a small hub route). If unavailable, capture stays off. Verify at the start of F2.
- **UI path:** the React client (`clients/web`, Phase 47, owner UAT at the end) versus the legacy operator UI; recommend React `features/memory/` and no legacy screen. The hub route and UI are the long pole and need Phase 47 coordination.
- **Rule recall and precision are unknown.** Patterns will miss most statements and some will be noise; the gate is the owner's judgement on a supervised window, measured from review outcomes (shown, accepted, edited, rejected, suppressed per day), not from stored transcripts.
- **Injection:** the whole-message pattern rule is the main defence; adversarial tests include pasted documents, "from now on …" inside quoted text, assistant text and retrieved content.
- **Plaintext candidate text** in the database and its backups; mitigated by short retention and clearing text on decision.
- **Dangling provenance pointers:** the conversation store is in memory, so a pointer to a past conversation cannot be resolved after a restart; the pointer is for attribution and bulk "forget this conversation", not replay.
- **ADR 0011 and bulk deletion:** see D3.

## 4. Steps (each ends with a dated verification record and an owner decision)

| Step | Work | Needs |
|---|---|---|
| F0 | Owner decisions (section 7) | this page |
| F1 | Migration 028 + rollback script, in-memory twin, store tests; rehearsal on a restored copy of the database (never the live one); proof that no trigger, index or read path other than review touches a candidate | **migration approval** |
| F2 | Rule set, exclusions, caps, background capture runner behind its flag; adversarial and zero-candidate matrices | F1 |
| F3 | Core routes, accept state machine, receipts, suppression, forget-from-conversation, retention job; consent tests (voice cannot accept) | F1, F2 |
| F4 | Hub proxy routes, React `features/memory/`, optional typed commands | F3, Phase 47 coordination, **UI approval** |
| F5 | Verification record, retention policy page, owner review | F3, F4 |

Deployment is a later, separate gate: backup and restored-copy rehearsal of 028, deploy with both flags false, review-only window with an empty queue, then a supervised capture window.

## 5. Retention (proposal)

| Item | Retention |
|---|---|
| `pending` candidate | 14 days, then the row is deleted and a daily counter incremented |
| `rejected` | text cleared at once; metadata row kept 30 days for the measurement, then deleted |
| suppression | hash and rule id only, no text; kept until the owner removes it |
| `accepted` / `edited-accepted` | text cleared on accept; the provenance row lives as long as the memory is not forgotten, is cleared when it is forgotten, and deleted when the memory is hard-deleted |
| `expired`, counters | counts only, by day; 365 days |
| flag turned off | no capture, routes absent (404), the retention job stops; existing rows stay until the owner purges them (an explicit purge procedure is part of F3) |

## 6. Acceptance checks (integration tests on disposable PostgreSQL, no new benchmark)

Zero candidates from each excluded source (voice, non-allow-listed channel, slash, attached meeting, privacy mode on or unknown, sensitive text, assistant text, retrieved or pasted content, quoted and multi-line text); zero memory rows without an accept (the table compared before and after a long scripted conversation with capture on); accept, edit, reject, suppress, forget-from-conversation and double-accept races; crash recovery of `accepting`; receipts present and a failing receipt not undoing the accept; a candidate canary absent from recall, the index, retrieval, context bundles, prompts and export; voice cannot accept; a planted instruction cannot create, prioritise or accept a candidate; foreground replies, prompts and model calls identical with capture on and off and a failing capture never delaying or truncating a reply; flag-off: no table read, routes 404, byte-identical existing suites; retention job behaviour and counters; rollback script restoring the 027 schema.

## 7. Decisions requested

1. Approve this scope (slices 0 to 3, retention, the two flags) and the step order, or amend it.
2. Approve the review surface in React `features/memory/` (not the legacy UI), and the hub route and any small hub getter for privacy mode.
3. **D3:** for "delete all candidates", choose between (a) treating unreviewed candidates as non-authoritative proposals that may be cleared in bulk by an owner text action with a prompt, and recording that reading of ADR 0011 in a short addendum, or (b) no bulk delete: reject one by one, "forget this conversation" as the only group action, and retention for the rest (recommended: (b) until an addendum is approved, because it needs no change to the consent rules).
4. Confirm the retention numbers (14 days pending, 30 days rejected metadata, caps of 5 per hour and 20 per day) or give others.
5. Approve F1 including migration 028 (rehearsal on a restored copy only; no apply to the live database), as a separate decision from F2 onward.
