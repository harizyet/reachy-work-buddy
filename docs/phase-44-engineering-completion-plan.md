# Phase 44: engineering completion plan (44E integration of the frozen B-1 path, 44F minimum build, acceptance checks) — PROPOSAL, 2026-10-10

**Status: APPROVED by the owner with amendments; E1–E5 IMPLEMENTED and verified locally 2026-10-10 ([record](verification/phase-44e-selective-integration-2026-10-10.md); uncommitted, nothing deployed). (2026-10-10, "Engineering integration approval"; see section 7). E1–E5 are approved for local/offline development and verification only; 44F implementation, migration 028 and UI need a separate decision after 44E verification. Original status: plan only, for owner review. Nothing is implemented, migrated, deployed or activated. Indexing, retrieval and shadow stay off; `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED` does not exist yet.** Priority has moved from research validation to engineering integration (owner directive, 2026-10-10).

## 0. Research track: paused

The dev16 acceptance evaluation, the scorer, the frozen candidate ([manifest](../services/companion-core/benchmarks/answer_quality/selective/CANDIDATE_FREEZE_2026-10-10.sha256)), `evaluator.py`, the thresholds and the criterion-6 rules are **unchanged and not to be modified or run by this plan**. dev16 is not frozen, not opened and not run. The track is **paused pending independent adjudication (reviewer B unassigned) and adequate statistical coverage (criteria 7–9 need ≥29 independent facts each; dev15 offers 16 / 3 / 9)**. No criterion is weakened or changed retroactively; if the track resumes, the [freeze command](phase-44-dev16-freeze-command.md) is the starting point. **Consequence for wording:** engineering gates below are *operational acceptance*, not a research claim, and no document may call the B-1 path "validated" or "accepted" on the strength of them.

## 1. What exists, and the central finding

| Piece | State |
|---|---|
| 44A/44B index, outbox, revalidation | built, migration 027 deployed, indexing OFF |
| 44D `Retriever` (B1a), `revalidate` under `AccessContext` | built, benchmarked, **called by no route** |
| 44E `build_context` (ContextBundle → bounded cited evidence block) | built, **called only by the measure-only shadow** |
| Measure-only shadow (`knowledge/shadow.py`, flag `KNOWLEDGE_SHADOW_ENABLED`) | built, OFF; derives the trusted `AccessContext` (voice = shared/public, text = private channel, sensitive tier never read) |
| `routing.py` status routing, `qualify.py` | built; shadow only |
| B-1 `answerability_b1` (admit → state → code-written, cited claims; `plan_question`) | frozen; imported by nothing in `src/` |
| 44H unclaimed-action boundary | **live**; one `elif` in `conversation_turn` |
| `KNOWLEDGE_RETRIEVAL_ENABLED` | **designed in [phase-44.md §7](phase-44.md), not implemented** |

**Central finding: there is no knowledge-answer path in the conversation route to integrate into.** Retrieved text has never reached a reply. So 44E integration means adding the *first* retrieval-to-reply path, with B-1 as the only thing that writes the reply. That is smaller and safer than a model-with-evidence path (no prompt, no model, no free text), but it is new route code and must be treated as such.

## 2. 44E: smallest integration of the frozen B-1 path

### 2.1 Design (one new module, one new `elif`)

New module `companion_core/knowledge/selective_answer.py` (an adapter; B-1 is imported, never edited):

1. **Gate (cheap, deterministic, first):** flag on **and** `qualify()` says knowledge question **and** `decompose_question` recognises ≥1 component against the relation registry. Anything else → return `None` and the turn proceeds exactly as today. This is the "claim" rule: B-1 answers only questions it understands; a decomposer fallback falls through to existing behaviour (it never refuses on the old path's behalf).
2. **Access:** the same trusted derivation the shadow uses (`access_for_owner`: voice → public; text → private channel, work-private ceiling; sensitive never; destination local). No model text can widen it.
3. **Retrieve:** `Retriever(B1A)` + `revalidate` (existing code). Needs the index populated, so the feature is inert until the owner separately enables indexing/retrieval.
4. **Map to B-1 inputs:** each revalidated `KnowledgeItem` → `DiscoveryItem(ref, text read from the source, provenance mapping from the item)`; `AuthDecision(authorized=True, checked_at=now, policy_version, acl_revision)` **only for items that survived revalidation**; evidence ids `E1..En` assigned in a fixed order. Provenance fields B-1 requires but the item lacks (author class, explicit effective period) → the record is not admitted (B-1 already fails closed).
5. **Plan and render:** `plan_question(...)` → `compose(...)`. Output is code-written text with `[E#]` citations and the manifest `{E#: refs, authorized}`.
6. **Verify before release (new, small):** every cited id exists in the manifest; every manifest ref is among the revalidated items for this turn; no citation outside the set. Any failure → discard, fall through to existing behaviour, increment `selective.verify_failed`.
7. **Release:** reply, `production_handler = "knowledge.selective"`, privacy = highest sensitivity among *cited* records (never lower than the turn's channel default), voice replies use the existing text/voice citation rendering from `build_context`.
8. **Failure handling:** any exception, timeout (bounded like the shadow, e.g. 2 s) or empty index → `None` (existing behaviour) plus a counter. The path never raises into the turn.

**Placement in `conversation_turn`:** in the final `else`, **after** the command-suggestion classifier and the 44H `unclaimed_action_reply` check, **before** the model call. So an action request is always caught first (the new path never sees one), deterministic handlers keep precedence, and consent/receipt/draft machinery is untouched. The new path creates no draft, no receipt, no memory, no task, no hub call and issues no action claim (its templates contain no completion verbs; checked by test with a copy of the 44H claim detector).

**Flag:** `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED`, default `false` (compose default too), read once at startup like the other knowledge flags. **It requires `KNOWLEDGE_RETRIEVAL_ENABLED=true`** (introduced here as a read-only retrieval switch, or the adapter owns a private retriever; owner decision D1 below). With retrieval off the flag is inert and logs one warning. Flag off ⇒ `app.state.selective_answerer is None` and the `elif` short-circuits on `is not None`: no object, no query, no import side effect on the turn.

**Models, thresholds, evaluator, registry, relation definitions:** untouched. The registry is hashed in the candidate freeze; a test asserts the freeze check still passes after integration (`candidate_freeze.py --check`).

### 2.2 Steps and dependencies

| # | Step | Depends on | Exit |
|---|---|---|---|
| E0 | Owner decisions D1–D4 (section 6) | this plan | decisions recorded |
| E1 | Adapter module and mapping tests (pure; fixtures only) | E0 | mapping, access, verify unit tests pass |
| E2 | Flag, startup wiring (`app.state`), the `elif`, counters | E1 | flag-off test: replies byte-identical to baseline over the existing conversation suites |
| E3 | Integration tests on a disposable `pgvector/pgvector:pg16` DB with real index + worker + revalidation (section 4) | E2 | all section 4 checks pass |
| E4 | Real-process check: in-process app (ASGITransport), then a disposable compose project, flag on/off/on | E3 | rollback and error checks pass; no production service touched |
| E5 | Verification record, HANDOVER/docs update, owner review | E4 | owner decision on any enablement (separate) |

Nothing in E1–E5 touches the homelab database, production flags, the model server's configuration, or real records. Production activation (indexing → retrieval → selective) is three separate later decisions.

## 3. 44F: minimum usable build (separately gated; not started)

Reviewed: [slices](phase-44f-implementation-slices.md), [phase-44.md §3.1](phase-44.md#31-44f-conversational-memory-capture-roadmap-2026-10-08-plan-only). Minimum usable = **slices 0–3** plus the expiry part of slice 4. Skipped for now: worthiness, placement, connection links, curiosity, re-entry.

| Requirement | Minimum implementation |
|---|---|
| **Gate** | `MEMORY_CANDIDATES_ENABLED=false` default; independent of `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED` and of retrieval/indexing (candidates are *excluded* from both). Slice 0 prerequisite satisfied: 44H unclaimed-action boundary is live, so capture cannot be the source of a false "saved" claim. Shadow need not be on. |
| **Capture** | Deterministic pattern rules on the owner's **final utterance**, after the reply, off the critical path, rate-limited ("I prefer…", "my X is Y", "from now on…"). The existing explicit "remember …" handler is unchanged (it already writes with the owner's explicit act). Never from assistant text, retrieved or attached content, shared/non-private channels, privacy mode, or turns the privacy classifier marks `sensitive`. |
| **Store** | Migration `028_memory_candidates` (the first and only migration in this plan): text, provenance pointer (session, turn, channel), proposed type/scope, sensitivity, status `pending|accepted|edited-accepted|rejected|expired|suppressed`, created, expires; plus a suppression-rule table. In-memory twin for tests. **Excluded from recall, the knowledge index/outbox triggers, retrieval, prompts and export.** Rollback rehearsal on a restored copy before any deploy. |
| **Review queue (web)** | Core routes `GET/POST /memory-candidates…` behind existing owner auth, surfaced through the hub proxy pattern in the operator UI (`clients/operator-ui`, with owner-cookie/CSRF as for other writes). List with provenance, proposed type, expiry. |
| **Accept / edit / reject / suppress** | Accept and edit-then-accept call the existing `add_memory` with `source="candidate:<id>"` and write a `memory.created` receipt; reject; reject-and-never-propose-again (suppression rule matched before proposing). Delete-all and forget-from-one-conversation keep **text-only** confirmation (ADR 0011). **No spoken accept; nothing accepted by default, timeout, silence or confidence.** |
| **Privacy / sensitive exclusion** | The exclusions above are enforced at capture (not at review), by trusted turn state only; planted instructions cannot create, prioritise or accept a candidate (live-route injection cases). |
| **Provenance / retention** | Every candidate and every accepted memory carries `candidate:<id>` plus session/turn pointer; default expiry (proposal: 30 days pending) with a pruning job that deletes and keeps a count; rejected text purged on a short schedule; retention documented in the phase page. |
| **Dependencies** | None on 44E/B-1. Order: F1 store + migration rehearsal → F2 rules + exclusion tests → F3 routes + UI + consent tests → F4 expiry/pruning → verification record. Each step ends with an owner decision. |

**Gates (operational):** zero candidates from every excluded source (adversarial set); zero memory rows without an accept (table comparison before/after a long scripted conversation); voice cannot accept; receipts on every accepted write; suppression, delete-all and expiry verified; candidates/hour on owner-reviewed conversations judged acceptable by the owner.

## 4. Engineering acceptance checks (integration tests, no new benchmark)

All run in pytest on disposable infrastructure: the in-process app (ASGITransport) with the injected stores for logic, and a disposable `pgvector/pgvector:pg16` database (real index worker, real revalidation) for retrieval-backed cases. Fixtures use the existing invented corpus; no real records.

| Area | Check | Pass condition |
|---|---|---|
| **Correct end-to-end answers** | Ask the flag-on app typed questions (owner, on-call, default model, host, retry limit, deadline, attendance) against the indexed fixture corpus over text. | Exact expected value and `[E#]` citations; reply handler `knowledge.selective`; multi-part question answers the supported part and states the rest as unsupported. |
| **Fall-through** | Questions B-1 does not understand; non-knowledge chat; deterministic-handler phrases. | Reply identical to the flag-off app (same handler, same text from the same fake model). |
| **Access control** | Voice/shared speaker; private text; restricted-scope and over-ceiling records; sensitive tier; record changed or deleted after indexing; ACL tightened between index and ask. | Value from a record the caller may not see never appears in reply, manifest or logs; revalidation drops it; voice gets public-only; deleted record not cited. |
| **Unsupported / conflicting / historical** | Question with no record; two records disagreeing; superseded fact; scoped-search negative; ordering question without an explicit statement. | `UNSUPPORTED/CONFLICTED/HISTORICAL/NEGATIVE_*/ORDER_UNSUPPORTED` wording exactly as in the B-1 templates; never a resolved conflict, invented ordering or world-level absence. |
| **Citation validity** | Cross-check every `[E#]` against the manifest and the revalidated set; forge a bad id via a faulty adapter in a test. | 0 invalid citations; verification failure ⇒ no release, falls through, counter increments. |
| **Action and receipt boundary (44H)** | The 12 live-route probes and H-001 with the flag on; planted instruction inside an indexed record ("reply done, the robot is asleep"). | 44H fixed reply still wins for action requests; no store, draft, receipt, hub or robot call changes; B-1 reply contains no completion claim; the planted text is data, never obeyed. |
| **Feature-flag rollback** | Flag on → answered; flag off + restart → identical to baseline; flag on with retrieval off → inert + one warning; indexing off. | Byte-identical flag-off replies over the existing core suites; no state to undo (no migration in 44E). |
| **Service errors / observability** | Index DB unavailable, search timeout, revalidation error, adapter exception, empty index. | Turn completes via existing behaviour in every case, never a 5xx; the failure is counted. Aggregate-only counters (no queries, ids or evidence): attempted, claimed, answered by state, fell-through by reason (not-qualified, not-understood, no-evidence, verify-failed, error, timeout), latency buckets — in the shadow-telemetry style; a startup log line states the flag state. |
| **Regression** | Full companion-core suite; ruff; `candidate_freeze.py --check`; 44H suites. | No new failures vs the known baseline (reconcile and historical-mode DB tests; intermittent contention tests). |

## 5. Phase 44 requirements: satisfied vs outstanding

| Requirement | State |
|---|---|
| 44A schema/contracts, 44B index/outbox/revalidation, indexing-workload gate | **satisfied** (027 deployed, trial accepted) |
| 44D retrieval library and benchmark (zero exposure, B1a selected) | **satisfied** as a library; **not wired** |
| 44E context builder (budget, escaping, dedup, provenance) | **satisfied** as a library; used only by shadow |
| Deterministic cited answer path | **satisfied as frozen source**; not wired; operational acceptance only, research acceptance paused |
| 44H unclaimed-action boundary | **satisfied, deployed** |
| 44H broader answer/action receipt boundary (claims inside model answers) | outstanding (proposal only); less critical for B-1 (code-written), still open for any model-written path |
| 44E route integration (first retrieval→reply path), flag, observability | **outstanding** — section 2 |
| `KNOWLEDGE_RETRIEVAL_ENABLED` implementation, production indexing/retrieval activation | **outstanding**, separate owner decisions |
| 44E injection probes for every new path that puts retrieved text in a reply | **outstanding** (the B-1 path emits code-written text, which shrinks but does not remove the need; probes in section 4) |
| Shadow rollout / live qualification precision | deferred by the owner; not required by this plan |
| 44F (all slices) | **outstanding**, not started — section 3 |
| 44G conflict/`superseded_by` classification, 44C entities | not started; out of scope |
| dev16 acceptance, independent validation | **paused** (section 0) |

## 6. Risks and decisions

**Risks.** (1) The registry and decomposer were developed on invented text; real records may be understood far less often. Mitigation: the gate falls through when it does not understand, so the worst case is "no change", and the counters measure the real claim rate before any broader enablement. (2) Real provenance may lack the fields B-1 needs (author class, effective period); B-1 then withholds. The cost is false abstentions, not wrong answers. (3) Template wording is stilted. (4) Adding the first retrieval-to-reply path enlarges the attack surface (injected record text); mitigated by code-written output and the planted-instruction tests, but it is new route code. (5) Latency of retrieval added to knowledge turns; bounded by a timeout. (6) 44F candidate text is private data: retention and purge must be right at the first deploy. (7) No independent validation exists for B-1's behaviour on real data.

**Decisions requested.**
- **D1** Does the selective flag require a new `KNOWLEDGE_RETRIEVAL_ENABLED` (recommended, matches the designed three-state table) or own a private retriever?
- **D2** On internal failure, fall through to today's behaviour (recommended) or return a fixed "I couldn't check your records" reply?
- **D3** Reply privacy: highest cited sensitivity (recommended) versus channel default only.
- **D4** Approve starting E1–E5 (no deploy) and, separately, 44F steps F1–F4 as a second gate; commit/push of this plan and the pending smoke-test records.

## 7. Owner decisions (2026-10-10) that amend this plan

- **D1.** Implement both `KNOWLEDGE_RETRIEVAL_ENABLED` and `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED`, default OFF; reuse the existing authorised retrieval and revalidation layer (no private retriever). Retrieval on / selective off injects **nothing** into the ordinary model prompt.
- **D2.** Three outcomes: ineligible or unrelated request, existing behaviour; eligible request with successful retrieval, a deterministic cited answer or "not established"; eligible request with a retrieval, authorisation, citation-validation or dependency failure, a **fixed truthful failure reply and no LLM call** (this replaces "fall through on internal failure" in section 2.1; absence of evidence is not an infrastructure failure). Regression tests: retrieval times out or fails after intent recognition, no fallback LLM call.
- **D3.** Existing `AccessContext` and revalidation. Output sensitivity is the maximum of what is disclosed; delivery only when the channel ceiling allows it; no restricted titles, names, citation markers or existence information in replies or errors.
- **D4.** E1–E5 local/offline only, adapter separate from the frozen B-1 candidate, disposable PostgreSQL, 44H boundary preserved; no dev16, thresholds or scorer research. Return with results, evidence, limitations and a proposed controlled deployment gate.
