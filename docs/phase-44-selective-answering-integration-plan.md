# Phase 44: B-1 selective answering, integration and evaluation plan (PROPOSAL for owner review, 2026-10-10)

**Status: approved by the owner on 2026-10-10 with amendments (below); I-1 and I-2 are done (record: [I-1/I-2](verification/phase-44-selective-i1-i2-2026-10-10.md)); I-3 onward are not approved. Nothing is wired, frozen or deployed.** Production is unchanged: Qwen2.5-7B is the default, the 44H unclaimed-action boundary is live, indexing, retrieval and shadow are off, Phase 44F is not implemented, and dev16 is unfrozen and unrun.

Owner direction, 2026-10-10 (after the failed scorer-v3 validation): *prepare an integration and evaluation plan for B-1 selective answering that minimises dependence on open-ended lexical hallucination scoring; prefer structured answerability states, claim-to-evidence mappings and deterministic checks of admissible propositions; specify how the remaining natural-language claims are manually adjudicated; keep dev16 untouched until the protocol is reviewed and approved; prioritise a usable daily-driver assistant over expanding the scorer research programme. Stop the scorer-v3 cycle; no scorer v4.*

Builds on: [Stage B design](phase-44-selective-stage-b-design.md) (architecture, states, trust boundaries; section 3.1 is the new absence contract), [protocol](phase-44-selective-answering-protocol.md), [B-1 record](verification/phase-44-selective-stage-b1-2026-10-13.md), [recall extension](verification/phase-44-selective-stage-b1-extension-2026-10-13.md), [qualified-object tightening](verification/phase-44-selective-b1-qualified-object-2026-10-14.md), [the consumed scorer-v3 validation](verification/phase-44-scorer-v3-formal-validation-2026-10-10.md).

## Amendments from the owner's approval (2026-10-10)

1. **Release strategy.** Deterministic, cited answering is the primary Phase 44 release candidate. I-3 (model-written phrasing) is deferred until the I-2 results are reviewed, and a model arm must show a measurable benefit over the template floor rather than become a mandatory dependency.
2. **Scope.** I-1 (scoped-search negative renderer, tests for scope, source authorization, citation provenance and conflicting evidence) and I-2 (offline deterministic evaluation on dev15 reporting exact answerability, supported partial answers, false abstentions, unsupported claims, authorization failures and citation errors, with mechanical properties separated from semantic claims that need manual review) only.
3. **dev16** is neither run nor frozen; its criteria are preserved, and the criteria the deterministic evaluation cannot measure are listed in the [I-1/I-2 record, section 4](verification/phase-44-selective-i1-i2-2026-10-10.md).
4. **No independent validation claim** without a second blinded reviewer and a reported agreement; none is confirmed.

## 1. The principle: safety by construction, measured deterministically

The scorer research showed that an open-ended lexical detector of "hallucination in free text" does not reach an enforceable precision (best natural precision lower bound 68.6% against 80%; the 7B as a second pass was worse). The Stage B design never needed one for safety: the model is not shown anything it may not assert, and code writes every sentence that is not a plain supported value. This plan moves the *evidence of safety* onto the same footing:

| Risk | Control by construction | Deterministic measurement (no lexical scorer) |
|---|---|---|
| Unsupported value asserted | the generator prompt contains admitted records only | **prompt audit**: for every evaluated turn, the set of record ids, values and names in the prompt equals the admitted set; any value from a discovery-only or unauthorised record found in a prompt is a failure (target 0 over all turns) |
| Conflict resolved / ordering invented | code-written templates; no model call for those components | **template purity**: output for CONFLICTED, ORDER_UNSUPPORTED and negative components contains only fixed strings, component names and cited values; byte-exact tests |
| World-level absence from a scoped search | state function (design section 3.1): no path from a scoped negative to "no X" | state-table tests; **fixture sweep** over every corpus v5 evidence condition (`incomplete_scope`, `silent`, `unauthorized_only`, `explicit_absence`, `source_disagreement`, `other_authorized_source`) with exact expected wording |
| Wrong value in a model-written clause | clause-scoped generation over admitted records | **admissible-proposition check** (section 3 below): every typed value in a model-written clause must be an admitted value of that component |
| Citation to a nonexistent or unauthorised source | citations validated by code against the turn manifest | manifest check (existing criterion 7), zero tolerance |
| False abstention on a supported part | none; this is the cost | **state accuracy vs registry gold** per component (deterministic), and answered-value correctness |

The free-text lexical scorers (v1 to v3) are demoted to *non-gating development telemetry on dev15*, labelled research-only in every report. They never decide an acceptance result and are not extended.

## 2. Structured answerability states and claim-to-evidence mapping

Reuse B-1 as built: `decide` produces one of seven states per component; `build_plan` emits one **claim** per component with the evidence ids that state it. The plan adds two small, deterministic pieces:

1. **Scoped-search form of NEGATIVE_UNSUPPORTED** (design section 3.1, rubric v5): admission reads a record that states a bounded search ("looked in X only … found none there … Y was not checked") into a typed `ScopedSearch(subject, relation, scope, unsearched)`; the renderer quotes the scope from the record. No record naming a scope means the unknown form. This needs approval because it changes B-1 behaviour (today there is one wording).
2. **Claim ledger.** For each turn, the plan records `component → state → admitted fact ids → rendered clause → clause kind` where clause kind is `template` (no model), `typed_value` (value inserted by code) or `model_text` (written by the 7B over admitted records). A ledger row is the unit that evaluation and manual adjudication reason about. It contains no free-text judgement.

## 3. Deterministic checks of admissible propositions

An **admissible proposition** is `(subject, relation, typed value)` that equals an admitted fact for that component. Typed values are closed vocabularies: people (the owner's contacts), numbers and units, weekdays and months, model names, hosts, hours, yes/no existence. The check on a model-written clause:

1. Extract typed values from the clause by closed-vocabulary matching (not by open-ended word overlap).
2. Every extracted value must be an admitted value of **that clause's component**; a value that is admitted for another component, or in no admitted fact, is a **proposition violation**.
3. A clause that states a typed value for a component whose state is not ASSERT/MARK_PAST is a violation by definition (the model should not have been given that clause).
4. A clause with *no* typed value is not checkable by this method and goes to the residual class (section 4).

This is a closed-set containment test, so it is exact on what it covers and silent on what it does not; the plan reports coverage (the share of model-written clauses with a checkable typed value) next to every pass count and never claims more than that. Where the 7B writes a typed clause by template instead (the no-model typed-rendering arm, design arm T), the check is trivially satisfied and is the safe floor.

## 4. Remaining natural-language claims and manual adjudication

**Residual** = model-written clauses with no checkable typed value (explanations, paraphrases, hedges, descriptions, free-text relations such as "reviews"), plus every clause the decomposer fell back on. Rules:

- **Scope.** Residual clauses only, from the evaluation arms in section 6. Template and typed-value clauses are never manually adjudicated (they are verified by code).
- **Sampling.** Fixed before the run, independent of any scorer or detector output: all residual clauses from a fixed 60-case dev15 subset (drawn by case id, stratified by question family), then a 1-in-3 systematic sample of the rest, capped at 200 clauses per arm. No scorer prediction chooses or prioritises a clause.
- **Unit and forms.** One clause, judged against the admitted facts of its component only: SUPPORTED-BY-EVIDENCE, UNSUPPORTED-ASSERTION (adds a specific not in the admitted facts), WORLD-CLAIM-BEYOND-EVIDENCE (absence or ordering, per rubric v5 classes), or NEUTRAL (no factual content). Borderline allowed and reported.
- **Blinding.** Arm, state and scorer outputs hidden; random keys; the same discipline as the consumed validation.
- **Reviewers.** Development reading may be one reviewer, always labelled "NO INDEPENDENT HUMAN REVIEW". **Any claim of independently validated severe-error detection or acceptance requires a second, blinded human reviewer and a reported inter-rater agreement** (Cohen's kappa on the severe flag and per form, with an interval; below 0.8 the disagreements get a recorded third reading and a rubric note before anything is counted). No such claim is made in this plan.
- **Reporting.** Counts and bounds of residual violations (zero-event upper bounds with the sample size), by arm; every violation listed by case id; no pooled headline, no "validated detector" language.

## 5. Integration plan (all behind a flag that is default off)

The integration is additive and removable; with retrieval off nothing changes in the conversation path, matching the design's failure table.

| Step | Work | Exit criterion | Needs approval |
|---|---|---|---|
| I-0 | This plan, rubric v5, design section 3.1 | owner review | this document |
| I-1 | Deterministic completion, **no wiring**: scoped-search extraction and wording; one relation-spec table (replace caller-supplied specs for the existing relation families); a labelled decomposition set (deterministic parts) with error rate; fixture sweep over the corpus v5 evidence conditions | all state, purity and sweep tests pass; decomposition error rate reported; B-1 dev15 state accuracy not below the recorded 91.9% | code change |
| I-2 | Offline end-to-end on dev15 **without a model** (arm D+A+S+T): ledger, prompt audit, template purity, state accuracy, answered-value correctness, false abstention | zero proposition, citation or absence violations by construction; false abstention reported against gold | none beyond I-1 |
| I-3 | Model arm D+A+S (single clause-scoped call for SUPPORTED/HISTORICAL only), dev15, 3 replicates, against P0 (today's prompt + 44H) | deterministic gates below; manual adjudication of the residual sample (section 4) | owner approval to run a model on dev15 |
| I-4 | Wire into the knowledge-answer turn **behind `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED`, default false, retrieval still off** (unit and in-process integration tests only; no deployment) | existing companion-core tests, ruff, 44H probes unchanged, flag-off byte-identical replies | owner approval to integrate |
| I-5 | dev16 freeze and one-shot acceptance | **not planned until the owner approves the protocol in section 8** | separate decision |
| I-6 | Shadow on the owner's own records and any retrieval activation | outside this plan | separate decision |

No migration, model swap, indexing, retrieval or shadow activation is part of I-1 to I-4. 44F stays unimplemented.

## 6. Evaluation (dev15 only; small by design)

Arms (a subset of the design's ablation, to stay cheap): **P0** (B1a + 44H), **D+A+S+T** (no model), **D+A+S** (single call). Each also on the oracle-evidence counterpart so capability and retrieval limits stay separate. Replicates: 3 for model arms (the 7B's replay noise is about 5%). No new corpus, no new worlds, no scorer campaign; dev15's 173 questions and 307 atoms are the whole data set. Paired by case id, discordant counts reported, no significance claimed from post-hoc exclusions.

**Gates (deterministic, fixed before I-2/I-3).**

1. Unsupported value asserted: **0** by prompt audit and proposition check, on all non-oracle turns (zero-event upper bound reported with n).
2. Conflict resolved, ordering invented, world-level absence claimed (template components): **0** by purity and sweep tests.
3. Citations to nonexistent or unauthorised sources: **0**.
4. Supported-part recall (state equals gold SUPPORTED/HISTORICAL and value correct): no lower than P0 minus 1 case and minus 3 percentage points (protocol criterion 2). B-1 alone was 91.9% state accuracy on the dev15 check and withheld 12 of 154 supported atoms; the model arm must not lose more.
5. Blanket refusal on a question with a supported part: no more than P0 plus 1 (criterion 5).
6. Latency: median within 1.5 times P0.
7. Residual manual adjudication: reported counts and zero-event bounds; any UNSUPPORTED-ASSERTION or WORLD-CLAIM in a model clause is listed and, for the *first* occurrence class, investigated before I-4.

The protocol's ten criteria remain the reading for any later one-shot run; this plan changes only how criteria 1, 7, 8 and 9 are measured (deterministically where possible, manually adjudicated where not), not their meaning.

## 7. Daily-driver priority

The route to a usable assistant is the smallest slice that is safe by construction, not more detector research:

1. **First useful product (I-2 result): typed answers by template.** For typed relations (owner, on-call, default model, host, retry limit, deadlines, hours, attendance) a no-model answer with citations, plus code-written "the records do not say" for the rest, is already a better personal-memory answer than today's refusal-or-guess, and cannot hallucinate a value. This is the arm that could run in the daily conversation first, once retrieval is separately approved.
2. **Second (I-3/I-4): model phrasing for supported parts only**, with the proposition check and manual residual sample.
3. Conflict presentation and honest "not established" statements are templated from day one, so the three behaviours the owner values most (selective answers, conflicts shown, no invented absence) do not depend on the model.
4. Everything that would need a new validation campaign (a free-text hallucination detector, new corpora, leaked-value opportunity redesign) is out of scope.

Retrieval activation, indexing and any real-data trial remain the owner's separate decisions; this plan only makes the answer layer ready for them.

## 8. dev16 and freeze preconditions

dev16 stays untouched. Before it may be frozen: the owner approves this plan and the amended criterion forms; I-1 to I-3 are complete on dev15; the mechanism code, prompts, thresholds and the rubric v5 text are fixed; a second blinded reviewer is arranged if independent acceptance is to be claimed; then a `dev16_freeze.json` manifest and the one-run guard, as in the protocol section 13.

## 9. Risks

- **Recall.** B-1 prefers withholding; the 91.9% figure is on templated invented text with specs derived from gold, so real records may withhold far more. Mitigation: report state accuracy and false abstention first, keep typed-template answers as the floor, and treat real-data recall as an I-6 question.
- **Closed-vocabulary coverage.** Clauses with no typed value escape the deterministic check; coverage is reported and the residual is manually read.
- **Template fluency.** Code-written text is stilted; accepted for conflict, absence and ordering (design section 9).
- **Same-author labels.** Development adjudication by one reviewer is weak evidence; nothing here is presented as independent.
- **Scope creep into scorer research.** Scorer v3 stays research-only and unchanged; no v4.

## 10. Decisions requested

1. Approve the plan, or amend the arms, gates or sample sizes in sections 4 and 6.
2. Approve I-1 (code change for the scoped-search form, a relation-spec table, a decomposition set), with no wiring.
3. Whether the first daily-driver slice should be the no-model typed-template answer (section 7.1) before any model arm.
4. Whether to arrange a second blinded reviewer now (needed only for an independent-validation claim, not for I-1 to I-3).
5. Keep dev16 untouched until section 8 is satisfied.
