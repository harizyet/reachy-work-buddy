# Phase 44E: selective-answering integration, local verification (E1–E5), 2026-10-10

**Status: implemented and verified locally/offline only. UNCOMMITTED (the owner approved committing the plan and records, not this code). Nothing deployed; indexing, retrieval and shadow are off in production; no migration; compose files unchanged (they do not pass the two new flags to the container, so production cannot enable them by accident); the frozen B-1 candidate, evaluator, thresholds, criterion-6 rules and dev16 are untouched (`candidate_freeze.py --check`: intact; `git diff` shows no frozen path).** Plan and owner amendments D1–D4: [engineering completion plan](../phase-44-engineering-completion-plan.md#7-owner-decisions-2026-10-10-that-amend-this-plan). No independent validation of B-1 is claimed by this work.

## 1. What was built

| Piece | Where |
|---|---|
| Adapter (new; imports the frozen `answerability_b1`, edits none of it) | `companion_core/knowledge/selective_answer.py` |
| Wiring: constructor parameter, `app.state.selective_answerer`, lifespan construction, one `elif` after the 44H boundary, privacy merge (42 added lines, no deletions) | `companion_core/app.py` |
| Tests | `tests/test_selective_answering.py` (30, in-memory live route), `..._postgres.py` (2, real index/worker/revalidation), `..._lifespan.py` (2, production lifespan) |

**Flags (both default off; `from_env` needs both).** `KNOWLEDGE_RETRIEVAL_ENABLED` and `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED`. Selective alone is inert with one warning; retrieval alone builds nothing and puts nothing in any prompt (no code path uses retrieval for the ordinary prompt). The adapter reuses the existing `Retriever` (B1a, lexical) and `revalidate`; no private retriever exists.

**Outcomes (D2).** (1) Ineligible or unrelated: existing behaviour, decided before any I/O (attached meeting; status question; not a knowledge question or no known anchor; no typed clause for the B-1 decomposer; attendance, which needs structured data this adapter does not supply). (2) Eligible and retrieved: B-1's code-written text with verified citations, including "the records do not say" and conflicts. (3) Eligible and anything fails (retrieval, index not ready or empty, pipeline, citation validation, timeout of 3 s): one fixed reply, **no model answer call**: *"I couldn't check your records just now, so I haven't answered that. Please try again shortly."* One wording for every kind, so it reveals neither the stage nor whether anything restricted exists. An empty result from a working index is an answer (absence); an unpopulated index is a failure.

**Privacy (D3).** Access from trusted turn state exactly as the shadow derives it (voice: public only; text: work-private ceiling; sensitive never; destination local). B-1 sees only records that survived revalidation; the adapter re-checks the ceiling, drops model-written records, and verifies every citation against this turn's revalidated records and the ceiling. Citation markers are renumbered by order of appearance (found in testing: a restricted record's presence had shifted a marker number through ranking). The reply's privacy label is the maximum over cited records, merged with the existing classification; voice replies carry no markers; text replies end with a "Sources:" line naming only cited, authorised records by title or kind.

## 2. Results

- **New tests: 34 passed** (30 + 2 on real PostgreSQL + 2 on the production lifespan), disposable `pgvector/pgvector:pg16` (digest `sha256:ccc6e83d…b4d6b`), removed afterwards, throwaway credential in a mode-600 file.
- **Full companion-core suite** with the database tests enabled: **1,824 passed, 8 skipped, 5 failed: exactly the five known baseline failures** (`test_knowledge_index` reconcile; three `test_knowledge_index` contention-tool tests; `test_knowledge_retrieval` historical mode). No new failure. `ruff check .` clean. `candidate_freeze.py --check`: candidate freeze intact.

| Required check | Evidence |
|---|---|
| Feature-flag rollback | flag matrix test; flag off and retrieval-only: prompts and replies byte-identical over 8 questions, 0 searches, no evidence block in any prompt; lifespan test on, off, on with the same database; fingerprint of every authoritative table unchanged |
| Authorised citations | every `[E#]` verified against the turn's revalidated records; forged `[E99]` gives the fixed reply; over-ceiling and model-written records excluded even when the retriever returns them |
| Unsupported / conflict / partial | "The records do not say …"; "The records disagree on … They do not say which applies."; multi-part questions answer the supported part and state the rest (exact fixed forms asserted) |
| Source sensitivity | spoken turn: public only; reply with and without a restricted record byte-identical in text and voice (reply, marker numbers, privacy label); a question only a restricted record could answer behaves like one with no record; work-private citation gives a work-private label |
| Dependency failures | retriever raises, retriever never returns (0.3 s limit), index count raises, index empty, pipeline exception, forged citation, real table renamed mid-flight on PostgreSQL: each gives the fixed reply, **0 model answer calls**, one `failed_*` count, no exception text, record text or question in logs; recovery without restart |
| 44H boundary | action requests (delete memories, standby, privacy mode, "I confirm") still get the fixed 44H reply, the answerer is not attempted, no store changes; a record with a planted instruction changes nothing and its extra text is never repeated; no reply makes a completion claim (44H claim detector) |
| Observability | counters only (attempted, eligible, ineligible by reason, answered, state, failed by kind, excluded by reason, latency buckets); summary logged at shutdown; nothing textual |

Latency on the production lifespan with PostgreSQL: **17 ms** for an answered question (hashing embedder not involved; B1a is lexical). The preceding command-suggestion classifier still makes its own (existing) model call before this branch; it is not an answer call.

## 3. Remaining limitations

1. **Coverage on real records is unmeasured.** The registry and decomposer were developed on invented text; on questions they cannot type, or without a known-term anchor, the turn falls to the existing ungrounded model path (by design, but the owner will see ungrounded answers for those). The counters measure this before any enablement.
2. **Ineligible means today's behaviour, including ungrounded model answers.** Only requests that enter the path are protected from fallback.
3. **Retrieval recall bounds correctness.** B-1 sees at most 15 revalidated records; a conflicting record that does not reach the pool is invisible to it (a "supported" answer may be incomplete). The text-only claim is "according to the records retrieved".
4. **Shared speaker:** records above public are treated as absent ("the records do not say"); deliberate, no existence leak, but not literally true.
5. **Attendance and speaker questions** are ineligible (the adapter supplies no structured attendee or speaker data); the frozen B-1 supports them only with it.
6. **Provenance is derived, not stored:** author class from source type (memory, note, task, reminder: owner; meeting: attendee; document: third party), creation time from `observed_at` or the turn time, ACL revision constant 1 (authorisation is the same-turn revalidation). Expiry and `valid_until` are not treated as effective periods (expired records are dropped by `temporal="current"`).
7. **Vocabulary anchor** refreshes every 15 minutes in the background; a record added since may not anchor a question until then.
8. Not exercised: a real model, real records, the real homelab database, the web/voice clients end to end, concurrent load. `[E#]` markers are meaningful to the owner only through the Sources line (no response-model field was added).

## 4. Proposed controlled deployment gate (for owner review; nothing here is authorised)

Prerequisites, each a separate owner decision, in order:

1. **Commit and push** the code and this record (explicitly staged files).
2. **Deploy the core image with both flags false** (add the two variables to compose with default `false`); verify flag-off equivalence on the live service (a fixed set of ordinary turns identical to before; 44H probes unchanged); no migration is involved, so rollback is the previous image.
3. **Indexing on the owner's own records** (existing 44B gate, flag `KNOWLEDGE_INDEXING_ENABLED`): confirm the index is populated and reconciled before retrieval is enabled; the answerer fails closed on an empty index.
4. **Shadow-first on real records (recommended):** run the measure-only shadow window already designed, plus the answerer's own counters in a "decide but do not release" mode (a small follow-up, not built) to learn the real eligible and answerable rates before any owner-visible reply.
5. **Controlled enablement:** `KNOWLEDGE_RETRIEVAL_ENABLED=true` then `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED=true`, text channel only first, owner present, a short supervised window (a few days), with these stop conditions: any reply citing a record the owner did not expect to be reachable; any failure reply rate above an owner-set limit; any invalid citation (must be 0); any reply that states a value the cited record does not contain; unexpected latency (set limit, e.g. median under 1 s).
6. **Rollback:** unset the flags and recreate core (about 30 s); no data to undo.
7. Voice (shared-speaker) enablement as a further step, after text.

44F stays separately gated: its implementation, migration 028 and UI need a separate decision after this verification.
