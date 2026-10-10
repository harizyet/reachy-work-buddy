# Phase 48 — Phase 44 activation and operational acceptance

**Status: IN PROGRESS (48B supervised capture trial open since 2026-10-10 14:06 UTC; [log](verification/phase-48b-capture-trial-2026-10-10.md)). 48A rehearsal passed and `MEMORY_CANDIDATES_ENABLED=true` is live in production (2026-10-10, review only, capture off; [record](verification/phase-48a-review-activation-2026-10-10.md)); the owner's browser check is pending. Every other Phase 44 flag is still OFF.**

Phase 44 is engineering-complete and deployed, but its capabilities are disabled behind feature flags. Phase 48 converts that code into capabilities that are proven on the owner's real data and then used, limited, or rejected on evidence. **It adds no cognitive feature:** no new memory architecture, GraphRAG, relationship store, model-based candidate extractor, curiosity engine or entity graph (all remain deferred, see the [closure report](phase-44-closure-report.md#2-deferred-by-explicit-decision)).

> Phase 44 built the machinery. Phase 48 proves it and turns it on.

## 1. Scope

Phase 48 activates, validates, and either promotes or rejects:

| Flag | Introduced by | Stage |
|---|---|---|
| `MEMORY_CANDIDATES_ENABLED` | 44F | 48A |
| `MEMORY_CANDIDATES_CAPTURE_ENABLED` | 44F | 48B |
| `KNOWLEDGE_INDEXING_ENABLED` | 44B | 48D |
| `KNOWLEDGE_RETRIEVAL_ENABLED` | 44D/44E | 48E |
| `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED` | 44E | 48F |
| `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED` | 44E | 48G |

Each stage has a stop/rollback gate. Feature flags are the rollback mechanism; migration 028 is **not** rolled back because a capability fails acceptance (schema rollback is for data-integrity or compatibility problems only, `deploy/homelab/rollback-028.sql`).

## 2. Order

The order is asymmetric: candidate review has a much smaller blast radius than knowledge retrieval, so it goes first.

```text
48A  Memory candidate review only
 ↓
48B  Supervised candidate capture
 ↓
48C  Knowledge indexing readiness          (preparation runs in parallel with 48A/48B)
 ↓
48D  Production indexing / backfill
 ↓
48E  Retrieval-only validation
 ↓
48F  Selective-answering shadow
 ↓
48G  Limited live selective answering
 ↓
48H  Operational acceptance / close
```

Each stage that changes production needs the owner's go-ahead for that stage. Approval of one stage does not extend to the next.

## 3. 48A — Enable memory candidate review

**COMPLETE (2026-10-10).** Disposable rehearsal passed; review enabled in production; the owner confirmed in a production browser that the Memory page renders correctly ([record](verification/phase-48a-review-activation-2026-10-10.md)).

Set `MEMORY_CANDIDATES_ENABLED=true`, `MEMORY_CANDIDATES_CAPTURE_ENABLED=false`.

Purpose: expose the built candidate review API, verify the React Memory page, and verify accept, edit+accept, reject and suppress.

Acceptance:

- the Memory page loads in the owner's browser;
- pending/accepted/rejected states render correctly;
- an accepted candidate produces exactly one durable memory (an ordinary `MemoryRecord`), with an action receipt;
- repeated accept is idempotent; reject creates no memory;
- suppress prevents re-proposal under the same suppression rule;
- a forgotten memory stays governed by the existing two-step path;
- no candidate appears from normal conversation while capture is off.

Rollback: `MEMORY_CANDIDATES_ENABLED=false` (routes return to 404). No schema rollback.

**Order inside 48A (owner, 2026-10-10):** (1) disposable-stack rehearsal first (real Postgres, core, hub and React bundle in a separate named Compose project); (2) if it passes, enable review only in production; (3) the owner checks the Memory page through Web. **No robot is required or touched.** Capture stays off throughout.

**Prerequisites found in the code (2026-10-10):**

- The flags were not in Compose or in core's environment; a default-`false` pass-through is in the repo, so activation is the `.env` value plus a core-only recreate (the hub only proxies and needs no flag).
- With capture off there are no candidates, so the rehearsal creates them through the core service on the disposable stack. Production receives no hand-inserted rows; the production check is that the page and routes work and the queue is empty and stays empty.
- The owner's browser check of the React Memory page is the owner's step ([Phase 47](phase-47.md) UAT convention).

## 4. 48B — Supervised candidate capture

### 4.1 Architectural rule and activation blocker

Reachy is the assistant; the robot is one embodiment and channel. Cognition, identity and long-term memory belong to companion-core, not to physical robot state. Today capture asks the hub `GET /privacy/state`, which answers `privacy_mode: false` only when a registered robot is armed for wake listening (`reachy_hub/app.py`); with no armed robot, or on a lookup error, nothing is captured. That couples Web and Android memory to the robot's wake-arm state. **This is treated as a design defect and an activation blocker: `MEMORY_CANDIDATES_CAPTURE_ENABLED` is not enabled in production until it is removed and the revised policy is tested.**

Two concepts that were conflated as "privacy" are separated:

1. **Embodiment privacy** — wake-word listening, microphone/camera capture, physical robot state. It may constrain robot-origin interactions only.
2. **Memory capture policy** — whether a given authenticated interaction may propose a memory candidate. It is decided from the interaction's channel and trust context.

### 4.2 Capture eligibility policy

| Interaction | Eligible |
|---|---|
| authenticated private Web chat | yes |
| authenticated private Android chat | yes |
| authenticated owner Telegram (authenticated private owner channel) | yes |
| robot voice | **no, deferred (owner, 2026-10-10)**: an armed robot does not show the speaker is the owner, and nearby people must not populate the owner's candidate queue. Re-enable when Phase 32 owner verification provides trust evidence. The wake-arm/privacy logic is retained for that integration (`ROBOT_VOICE_ELIGIBLE = False` in code, not an environment setting) |
| shared, public or untrusted channel | no |
| sensitive turn | no, unless the existing memory/privacy policy explicitly permits it |
| `MEMORY_CANDIDATES_CAPTURE_ENABLED` false (or review flag off) | never; remains the global kill switch |

This is the smallest change that removes the robot dependency, not an auth or privacy rewrite. It keeps the existing exclusions (sensitive text, assistant text, retrieved or attached content) and adds no endpoint or client-supplied trust field. **Implemented in `0304ab8` (2026-10-10), not deployed:** channel and modality decide eligibility; robot-voice turns are ineligible in Phase 48 (the retained logic would consult `GET /privacy/state` only for them). Evidence: [48B record](verification/phase-48b-capture-eligibility-2026-10-10.md).

### 4.3 Trial

Set `MEMORY_CANDIDATES_CAPTURE_ENABLED=true` for a short supervised trial: 3 to 7 days, or 30 to 50 candidate-worthy interactions, using ordinary natural interactions through Web and Android (and Telegram where applicable), not only scripted prompts.

Measure: proposals, useful candidates, false/annoying candidates, missed candidate-worthy facts, duplicates, sensitivity mistakes, scope mistakes, suppression success. Metrics: precision, acceptance rate, edit-before-accept rate, rejection rate, suppression rate, duplicate rate. **Precision matters more than recall.**

Promotion gate: at least 80% of surfaced candidates judged useful or reasonable; 0 sensitive-capture violations; 0 durable memories without explicit acceptance; 0 candidates from shared/public/untrusted channels. If precision is poor: capture OFF, review stays ON, rules refined in a later phase.

## 5. 48C — Knowledge indexing operational readiness

**COMPLETE for the small-corpus activation (2026-10-10).** The owner waived the off-host backup for this 48D activation only (about 85 index rows; derived index and outbox only; the general off-host requirement stands for operations that risk authoritative data), subject to a fresh local dump, row counts, a synthetic benchmark on a disposable stack, an idle baseline and a rehearsed rollback. All were done: [record](verification/phase-48d-indexing-activation-2026-10-10.md). Stop conditions used: chat p95 regression over 10%, any OOM or service restart, sustained swap churn or growth (the 7.8 GB of swapped cold pages is not a blocker; active si/so traffic is the measure), dropped meeting jobs, 25 or more PgBouncer-fronted backends.

Close the operational blockers from the [closure report](phase-44-closure-report.md#3-operationally-blocked). The migration-028 backup waiver was for disposable data and does **not** extend to indexing the real corpus.

Required: off-host backup; isolated restore; fresh memory baseline (host available memory read 3.4 GB on 2026-10-10 against 7.7 GB at the trial minimum); database-connection, disk and CPU baselines; bulk-indexing contention test; rollback rehearsal.

Record: available RAM, PostgreSQL size, records by source, index row estimate, indexing wall time, CPU and memory peaks, DB connections, effect on vLLM TTFT and decode, on meeting transcription/diarization, and on normal API latency. Ceilings come from the measured hardware, not arbitrary numbers, for example: chat p95 regression under 10%, no OOM, no model eviction, no dropped meeting jobs, DB pool below its configured ceiling.

The off-host backup is the known hard part: the backup programme is paused and the NAS offers no usable transfer path ([plan](postgres-backup-implementation-plan.md)). Resolved for the small-corpus 48D activation by the owner's scoped waiver (see below). A read-only idle baseline and prerequisite status is recorded in [the 48C baseline](verification/phase-48c-baseline-2026-10-10.md). 48C preparation is non-invasive documentation and checks only while the 48B window is open; indexing is not activated during it without separate approval.

## 6. 48D — Enable indexing and backfill

**COMPLETE (2026-10-10, 14:35 UTC).** `KNOWLEDGE_INDEXING_ENABLED=true`; retrieval, selective answering and shadow remain off. 83 rows indexed in under 20 s; sources byte-identical before and after; no drift or orphans; chat p95 unaffected; no restart. Evidence and findings: [record](verification/phase-48d-indexing-activation-2026-10-10.md). **48E needs the owner's approval.**

Set `KNOWLEDGE_INDEXING_ENABLED=true` with retrieval, shadow and selective answering all OFF, so indexing cannot affect replies. Backfill every supported source type: memories, documents, meetings, notes, tasks, reminders.

Verify: source versus index counts; no orphans; no forgotten or expired memories indexed; deleted records disappear; accepted transcript corrections reflected; generated summaries distinguishable from evidence; sensitivity inheritance; project scopes; source references resolve to authoritative data.

Reconciliation test: source edit → outbox → reindex → query index → source revalidation. Stale-item test: forget/delete/reclassify → retrieval refuses the item **immediately**, before reconciliation catches up. That revalidation-at-retrieval property is explicitly an acceptance item.

Carry-over: one pending outbox row (a note, generation 30) exists from 2026-10-09; the worker will claim it. Never insert, delete or edit outbox rows by hand.

## 7. 48E — Retrieval-only validation

**EXECUTED (2026-10-10); awaiting the owner's decision on 48F.** `KNOWLEDGE_RETRIEVAL_ENABLED=true`, selective answering and shadow off. Frozen case sets (35 real-owner cases on production, read-only; 52 synthetic cases on a restored copy including stale-index mutations): recall@5 100% on every positive set after reconciliation, 0 restricted, forgotten, expired, deleted or cross-scope leakage in 100 case runs, every citation resolved. Main finding for 48F: retrieval does not signal absence. [Record](verification/phase-48e-retrieval-validation-2026-10-10.md).

Set `KNOWLEDGE_RETRIEVAL_ENABLED=true`, selective answering still off. Test retrieval independently of generation with a real-owner query set covering memory lookup, meeting facts, project facts, task/reminder state, cross-source facts, historical facts, absent facts, conflicting facts, sensitive records and project-scoped records.

Per query record: expected sources, retrieved top-k, correct source present, restricted source leaked, stale source, citation resolvable. Metrics: recall@k, precision@k; **restricted-record leakage, expired/forgotten retrieval and cross-scope leakage must all be 0.** If quality is poor, stop here; do not compensate with the LLM.

## 8. 48F — Selective shadow

Set `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED=true`, selective answering OFF; replies are unchanged and only aggregate categories are recorded ([telemetry policy](phase-44e-selective-shadow-telemetry-policy.md)). Run until 100 to 200 genuine knowledge-like turns or 2 weeks, whichever comes first.

Review: share of turns classified as knowledge requests; typed/ambiguous/untyped; supported/unsupported/conflicted; retrieval failures; timeouts; sources per answer; voice versus text; questions the generic model answered but selective answering would abstain from; questions where it would prevent a hallucination. The test is not "was it correct" but "would it be more trustworthy than the existing generic model".

The owner said on 2026-10-12 not to start the shadow window until the groundedness milestone was revisited; this phase is that revisit and needs the owner's explicit start.

## 9. 48G — Limited live selective answering

Only after 48F review. Start with authenticated web and Android **text** only, well-typed questions with supported evidence only; ambiguous and untyped requests stay on the existing path. No voice at first (citations are visible in text, corrections are easier, no shared-speaker privacy ceiling).

Canary: 10 to 25% of eligible requests if a share flag existed; **it does not** (only the two enable flags and a timeout setting exist), so the first restriction is by channel and adding a share flag would be a code change needing its own decision.

Acceptance: 0 restricted-record leaks; 0 false authoritative claims; citation/source traceability; accurate failure reply; correct abstention on unsupported questions; acceptable latency. Then expand to all authenticated text. Voice is a separate final promotion.

## 10. 48H — Operational acceptance and close

Phase 48 closes when each capability has a disposition:

| Capability | Disposition (to be filled by evidence) |
|---|---|
| Memory candidate review | ACTIVE / ACTIVE WITH LIMITS / DISABLED BY EVIDENCE / DEFERRED BY OWNER |
| Memory candidate capture | same |
| Knowledge indexing | same |
| Knowledge retrieval | same |
| Selective shadow | complete, then OFF |
| Selective answering | same, per channel |

Each row is backed by the section 11 checks. Expected target if the evidence is good: candidates enabled, capture enabled, indexing enabled, retrieval enabled, shadow OFF, selective answering enabled for accepted channels. No capability is required to end enabled merely because it exists; no Phase 44 feature stays disabled merely because activation was never attempted.

## 11. Test strategy

Memory review, candidate quality, indexing, retrieval and selective answering are tested **primarily through Web and Android**. The robot is **not a gate** for 48A to 48G. Robot testing belongs to the final regression in 48H, to show that memory and knowledge changes did not regress embodiment.

48H final verification:

- Web works (review, capture, retrieval, selective answering);
- Android works;
- Telegram works where applicable;
- the robot still converses normally by voice;
- robot privacy mode and wake arming still behave correctly, and robot-origin capture follows its own voice/privacy/trust rules;
- no memory-capture or knowledge change caused an embodiment regression.

Robot work follows the standing safety rules in [AGENTS.md](../AGENTS.md); this phase does not start, restart or resume the daemon.

## 12. Rollback

| Failure | Rollback | Kept |
|---|---|---|
| Candidate capture poor | `MEMORY_CANDIDATES_CAPTURE_ENABLED=false` | review and schema |
| Retrieval poor | `KNOWLEDGE_RETRIEVAL_ENABLED=false` | the index, for debugging |
| Selective answering poor | `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED=false` | retrieval for explicit tools |

## 13. Guardrails for this phase

- All standing rules in [AGENTS.md](../AGENTS.md) apply: stage files explicitly, no credentials in logs, disposable checks in a separate named Compose project, never delete user volumes.
- Every production change is a separate owner-approved step with a recorded before/after (flag state, container ids, rollback command). Evidence goes into dated verification records; this page keeps the plan and dispositions.
- The 44H unclaimed-action boundary, text-only destructive confirmation and the ADR 0011 consent rules are unchanged and must be re-probed after each activation.
- Mocks, disposable-stack rehearsals and live production checks are labelled separately in every record.

## 14. Progress log

| Date | Stage | Event |
|---|---|---|
| 2026-10-10 | all | Phase proposed and documented. Production flag state read: none of the six flags set (only `KNOWLEDGE_INDEXING_ENABLED=false` is in core's environment). |
| 2026-10-10 | 48A | Compose pass-through added for both memory-candidate flags (default false; not deployed, running core unchanged). Robot-armed coupling of capture confirmed in code. |
| 2026-10-10 | 48B | Owner decision: memory is channel-independent from the robot. Capture policy separated from embodiment privacy (section 4); coupling is an activation blocker; capture stays off until fixed and tested. Robot is not a gate before 48H. |
| 2026-10-10 | 48A | Disposable-stack rehearsal with the production images passed (idempotent accept, edit, reject, suppress, forget, capture-off, UI, rollback). `MEMORY_CANDIDATES_ENABLED=true` set in production, core-only recreate, capture OFF, queue empty. Record: [48A](verification/phase-48a-review-activation-2026-10-10.md). Awaiting the owner's browser check. |
| 2026-10-10 | 48B | Capture eligibility refactor implemented (`0304ab8`) and verified on a disposable stack built from that commit (Web, Android, Telegram contract, robot voice both ways, unauthenticated, sensitive, flag combinations, one memory and one receipt, reply parity; no robot). Not deployed; production capture still OFF. Record: [48B](verification/phase-48b-capture-eligibility-2026-10-10.md). Awaiting owner approval of 48B activation. |
| 2026-10-10 | 48B | Owner decisions: robot voice ineligible until Phase 32 (`ROBOT_VOICE_ELIGIBLE = False`, `d899e14`, regression test armed robot + unverified voice = 0 candidates); 48B activation approved. Core rebuilt from a clean worktree of `d899e14`, recreated alone at 14:06 UTC with `MEMORY_CANDIDATES_CAPTURE_ENABLED=true`; queue empty. Supervised trial open, rules frozen. Record: [trial log](verification/phase-48b-capture-trial-2026-10-10.md). |
| 2026-10-10 | 48B/48C | Capture implementation and rules frozen for the evidence window (hashes and end-of-window procedure in the trial log). Read-only 48C baseline taken: corpus is tiny (about 85 index rows), swap nearly full, off-host backup still unmet; no indexing or load. Record: [48C baseline](verification/phase-48c-baseline-2026-10-10.md). |
| 2026-10-10 | 48A | **COMPLETE.** Owner confirmed the production Memory page renders correctly in a browser. |
| 2026-10-10 | 48C/48D | Off-host backup waived for this small index activation (owner). Fresh dump verified readable, source checksums recorded, synthetic benchmark on a disposable stack (chat +6.4% p95, swap static), idle baseline, rehearsal of disable/rebuild/rollback on a restored copy. `KNOWLEDGE_INDEXING_ENABLED=true` at 14:35 UTC; 83 rows, sources unchanged, no stop condition. Finding: the 48B end-of-window summary line is never logged (see trial log). Retrieval stays off; awaiting approval for 48E. Record: [48D](verification/phase-48d-indexing-activation-2026-10-10.md). |
| 2026-10-10 | 48B | Read-only aggregate counters route added (core only, `9c8214a`) and deployed at 14:45 UTC; capture files unchanged; trial continues (restart boundaries logged). The 14:06 to 14:34 tally is an accepted documented gap. |
| 2026-10-10 | 48E | `KNOWLEDGE_RETRIEVAL_ENABLED=true` at 14:46 UTC (inert for replies). Retrieval validated on frozen sets: 0 leakage, recall@5 100% (after reconciliation), no tuning. Findings: retrieval returns loosely related items for absent facts; unscoped records are visible to scoped callers by design (D8). Record: [48E](verification/phase-48e-retrieval-validation-2026-10-10.md). Stopped before 48F. |
