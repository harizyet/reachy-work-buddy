# Phase 44E: selective shadow mode and zero-evidence qualification, local verification, 2026-10-10

**Status: implemented and verified locally/offline only. UNCOMMITTED (the owner approved committing the proposal only; new code stops here for a separate decision). Nothing deployed, migrated, indexed or activated; Compose unchanged and does not pass any of the flags; the frozen B-1 candidate, evaluator, thresholds, criterion-6 rules and dev16 are untouched (`candidate_freeze.py --check`: intact). No 44F work.** Decisions: D1 to D4 of the owner's 2026-10-10 "Deployment readiness decisions".

## 1. What changed

| Piece | Where |
|---|---|
| Zero-evidence qualification (adapter only): a reply that is wholly "not established" with nothing admissible and nothing cited becomes *"I couldn't establish that from the records I was able to check."* Absence statements, scoped-search negatives, conflicts, historical and supported values, supported parts of partial answers and caveats about unreadable records keep B-1's own text | `knowledge/selective_answer.py` |
| Deterministic routing `classify()` (typed, ambiguous, untyped, ineligible; reason and anchor categories) and a side-effect-free `assess()` that returns categories only; the live path's behaviour is unchanged | same |
| Selective shadow: flag `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED` (default false; needs `KNOWLEDGE_RETRIEVAL_ENABLED` and `KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH`; needs no live selective flag) | `knowledge/selective_shadow.py` (new) |
| Wiring: one parameter, `app.state.selective_shadow`, lifespan construction/start/stop, one `submit` after the reply is final (30 added lines in `app.py` on top of the 42 committed in `b34d366`; net additions only) | `app.py` |
| Tests | `test_selective_shadow.py` (13), `test_selective_shadow_lifespan.py` (4, real PostgreSQL), three zero-evidence tests added to `test_selective_answering.py` (33 now); PG test wording updated |

**Shadow contract.** Offered after the reply is final, constant time, never raises; one background worker, short queue (default 10, clamped 1 to 20, oldest dropped), per-job timeout (3 s, clamped 0.2 to 5), one job at a time. The job uses the **turn's own channel access** (a spoken turn: public only) through the existing `Retriever` and revalidation and the same verification as the live path, reduces the result to categories and discards it. It cannot release, delay or change a reply and keeps its own counters (the live answerer's are untouched). Every counter name comes from a fixed vocabulary (anything else is recorded as `other`), so no prompt, reply, evidence, title, record id, session id or any text can be written; one JSON line per hour window, mode 0600, retention 30 days. No semantic comparison with the production reply: the only production fact kept is the kind of path that answered (model, deterministic handler, action boundary, selective).

## 2. Test evidence

- **New and changed tests: 17 shadow tests + 3 zero-evidence tests + the unchanged earlier 34, all pass**; production-lifespan and real-PostgreSQL tests used a disposable `pgvector/pgvector:pg16` (digest `sha256:ccc6e83d…b4d6b`, removed afterwards, throwaway credential deleted).
- **Full companion-core suite** with database tests enabled: **1,844 passed, 8 skipped, 5 failed: exactly the five known baseline failures** (reconcile; three contention-tool tests; historical mode). `ruff check .` clean; candidate freeze intact.

| Requirement | Evidence |
|---|---|
| Off unless prerequisites | flag alone, retrieval alone, no log path, no database: no object and no file (unit and lifespan) |
| Never changes or delays the reply | prompts, replies, model calls and a fingerprint of every authoritative table identical with the shadow on and off (in-memory and real PostgreSQL, text and voice); a shadow whose retrieval takes 1 s, hangs 30 s or raises leaves four foreground turns unchanged and fast; 40 foreground turns with a saturated shadow took 0.3 s |
| Never releases an answer | the typed Quill question is answered by the ordinary model path with the shadow on; no `<evidence` in any prompt; with the live answerer also on, only the live path releases and the shadow's counters stay separate |
| Trusted channel, revalidated sources, restricted content | every counter group identical with and without restricted records (text and voice); spoken turn never counts a work-private citation; no `sensitive` bucket exists; corpus words absent from the file (whole-token check against the real corpus) |
| Bounded queue, concurrency, timeouts | queue 2: dropped-oldest counted, `processed + dropped = admitted`, funnel reconciles to 0, also under a real database |
| Aggregate-only, no identifiers | allow-list test on every field and name; the file holds none of a planted credential, names, session ids or record keys; arbitrary strings become `other`; mode 0600 |
| Failures isolated | retrieval raising, index empty, hang/timeout, an exception inside the job, a real index table renamed mid-flight: bounded categories counted, foreground unchanged, recovery without a restart, pool within its bound, no exception text or question in logs |
| Clean stop | stop counts queued work as discarded, a restart appends to the same file, shutdown releases every connection |
| Flag-OFF | every existing selective, shadow and 44H test still passes; a flag-off app builds no shadow and no file |

## 3. Routing metrics (descriptive, from the existing labelled qualification sets; invented-corpus vocabulary; NOT a validation)

191 labelled questions (97 personal-knowledge, 94 other), classified by `classify()`:

| Class | Personal-knowledge (97) | Other (94) |
|---|---|---|
| typed (every clause typed) | 13 (13%) | 0 |
| ambiguous (some clauses typed) | 0 | 0 |
| untyped, `not_understood` | 71 (73%) | 10 (11%) |
| untyped, `needs_structured_data` | 0 | 0 |
| ineligible, status question | 10 (10%) | 1 (1%) |
| ineligible, not a knowledge question | 3 (3%) | 83 (88%) |

Anchor evidence for the 81 untyped requests (the activation-safety concern: record-dependent, untyped, answered by the ordinary model today): **all 10 non-personal false catches are anchored by a known term alone**; of the 71 personal untyped, 37 are also known-term only and 34 have a record noun, a first-person or team phrase, or more. A rule "two or more anchor kinds" would have caught 32 of the 71 with 0 false catches in these sets; "a record noun" 27 with 0; "first-person or team" 16 with 0. This is a preview of the narrower safeguard to propose after representative evidence, not a recommendation; the shadow therefore counts `untyped_anchor_strength` (single or multiple) and `record_dependent_untyped_by_path` on real traffic.

## 4. Remaining activation blockers

1. **No real-traffic routing evidence yet.** The shadow must run (local code only; nothing deployed) on the owner's real traffic and records; the narrower safeguard of D1 is proposed only after that.
2. **Index not populated with the owner's records.** Production indexing (phase-44 gate, see the [proposal](../phase-44-deployment-readiness-proposal.md)) has not run beyond one note; without it the live path fails closed and the shadow reports `failed_not_ready`.
3. **Operational prerequisites unmet today** (section 5 of the proposal, D4): a verified off-host backup and an isolated restore (the backup programme is paused and no off-host destination works); bounded worker contention measured on a bulk load; a rehearsed rollback. Host available memory read 3.4 GB on 2026-10-10 against 7.7 GB at the lowest point of the 2026-10-09 trial, so the memory baseline must be re-taken before any indexing window.
4. **Owner approval to commit this code, then separate approvals** for deployment with the flags false, for the shadow window, and for each later step. 44F, dev16 and scorer work are untouched.
5. Residual limits unchanged: answer quality is not assessable from content-free telemetry; coverage of real phrasing is unmeasured; ineligible and untyped requests still reach the ordinary model with the flags on or off.
