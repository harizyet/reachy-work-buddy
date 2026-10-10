# Phase 44: dev16 formal acceptance preflight (2026-10-10)

**Status: preflight only. Nothing in this document has been executed. The P0 baseline has not been run, dev16 has not been frozen, opened or run, and no reviewer other than the pipeline's author has been confirmed. This page stops for the owner's approval of the formal acceptance execution.** It consolidates the owner decisions of 2026-10-10 (final development pass approved; commit and push approved) with the [readiness report](phase-44-dev16-deterministic-criteria-draft.md) and the [development record](verification/phase-44-selective-final-dev-pass-2026-10-10.md). Where this page and the readiness report differ, this page governs.

## 1. Owner decisions in force

| Topic | Decision (owner, 2026-10-10) | How it is honoured |
|---|---|---|
| Evidence | A decision, a deployment and the current configuration are distinct. "Keep X as the default model" is not proof X is deployed or configured. Conservative admission rules and all regression tests stay. | `transitions.py`: a decided or planned value never answers "what is the default model"; it is reported as a decision. Tests: `tests/test_transitions_b1.py` (65). The slice costs 7 of 307 dev15 atoms (2.3%) and is counted as false abstention. |
| Relative time | Accept source-relative expressions only when clearly attributed to the original record. Do not resolve "this month" to a calendar period without an authoritative temporal anchor. | Replies quote the phrase as the record's words: `(the record says "this month")`. No date arithmetic exists anywhere in B-1; record creation and retrieval times are never read for time. A question that itself says "this month" is withheld. Tests: `test_a_relative_time_in_the_record_is_kept_in_the_answer`, `..._differs_..._withholds`, `test_a_question_that_names_a_relative_period_...`. |
| Criterion 6 | Approve a prospective blinded adjudication of citation-manifest discrepancies (section 6). Only an authorised, in-scope record omitted from the manifest is eligible. Preserve mechanical and adjudicated verdicts. No retrospective change to frozen results. **The threshold is not altered.** | Section 6. |
| Candidate freeze | The existing candidate, registry and relation-definition freeze list is approved; hashes and the shared-corpus disclosure are preserved; the frozen candidate is not modified during acceptance. | Section 2. |
| P0 and dev16 | Preparation of the P0 baseline and blinded adjudication is approved. **Do not execute the P0 run, freeze or run dev16 yet.** Independence needs a confirmed second reviewer and kappa >= 0.80. | Sections 3, 7, 8. |
| Boundaries | No further B-1 feature work, scorer v4, model-written I-3, production wiring, deployment, indexing, retrieval, shadow activation or 44F. All earlier frozen artifacts unchanged. | Nothing in this pass touches them (section 10). |

## 2. Frozen candidate and evaluator hashes

Committed as `272572c3e5d33ad16b41721233561b0a31ec904e` (local `main`, pushed with the documentation commit). The authoritative manifest is `services/companion-core/benchmarks/answer_quality/selective/CANDIDATE_FREEZE_2026-10-10.sha256` (31 files, checked by `candidate_freeze.py --check` and `tests/test_candidate_freeze.py`).

| What | SHA-256 |
|---|---|
| Manifest `CANDIDATE_FREEZE_2026-10-10.sha256` | `b095e9beb02f5573f8c57da92bd4b2ab0141943203b91bbcb096112a1cc122a9` |
| `evaluator.py` (evaluator v3, ten criteria) | `d364af6bbf7f5328f09952347ceabb4454a27cf94950f7009157a90cf99e8f27` |
| `deterministic_criteria.py` | `e8f27b7375882b7c35dd7290fc889471a6db0ff6f623957634ebbce836c5892f` |
| `i2b_eval.py` | `f09da998446712ff33d5db33e31a2275855a07042a041e310f46091c3e025e2b` |
| `p0_adjudication.py` | `85eb4feec10a15ecbeabc012caeb97d8c195973d0b25c8a88b983da44e5bf16e` |
| `registry.py` | `05a536ebba8aae6e86b03c992fc3b09580175333a6aa603dbf737efaec7e2819` |
| `questions.py` | `4267061bd58c76070cab48ddb085a0aef228733ea15c7aca7833c127a4b84ace` |
| `transitions.py` | `4df5237ff5f062a87659e391ee1cc09bf3517f4648dd4730ab88c86b60b729a1` |
| `admission.py` | `7fe11b204254a6e38958ec6ed042e8d1caaf8404070ec825705d217fee37049f` |
| `states.py` | `372cf17ad4327c940152f54e26f73e979940d9b3018c03730dd8a2564b30873d` |
| `contract.py` | `bec1e8b21684b10f1e0d54379e171d53682bc7aabc4c5a816c6623470a57f5b5` |
| `types.py` | `562a896f3eaeed0665ebba983e135750d0bacf90a652af39650b6d7cf9029920` |
| `relation_definitions_frozen.json` (24 relations as data) | `20dfeee1208e0f97c5540f1aead93d3043578de158eb22f3f756351bb48f5ede` |
| `cases_dev15.json` (development population) | `e4ff446c283436a9bd9378a6a067bd4fc9406450b9076cbe5e8b6c65731f980a` |
| `aq/scoring.py` (exact source matching used by the evaluator) | `6bfb790efdf6a2cb4909e3966c74da0aab5fa92032ceca2c3d10c702a001a1f2` |

The manifest also lists `corpus_v4.json`, the labelled decomposition and held-out sets with their own freezes, the review samples and the probes (full hashes in the manifest). **dev16 and bank D are not listed, opened or hashed.** `aq/scoring.py` is hashed here but not in the manifest; it is a pre-existing file whose hash is recorded now so a change before the run is detectable, and the dev16 freeze must add it.

**Disclosure, preserved:** before the held-out relation question set was written, the author had incidentally printed three shared-corpus *record* sentence forms of these relations ("Escalate serious `<project>` incidents to `<person>`.", "`<person>` approved the `<project>` release.", and the budget sentences "approved through `<month>`"). No release-day record sentence was seen. The relation definitions are not blind to the record surface of escalation and approval; they are blind to dev16's cases, questions and phrasings. The corpus file is shared with dev16.

**Candidate immutability during acceptance.** The candidate manifest is checked (a) at the dev16 freeze, (b) immediately before the run and (c) immediately after. A defect found during or after acceptance is reported, not fixed; a fix is a new candidate with a new freeze and a new acceptance.

## 3. P0 baseline and paired-comparison methodology (not run)

**Arms.** *Candidate*: the deterministic path, no model, run once on the frozen dev16. *P0*: today's retrieval and prompt (B1a lexical retrieval over the same record pool) plus the live 44H unclaimed-action boundary, Qwen2.5-7B (the production default), run once on the same frozen dev16. Both arms use the same questions, the same record pool, the same authorisation decisions and the same evidence-id manifest builder.

**Known gap, to close before the dev16 freeze and not before owner approval:** there is no guarded dev16 runner. `selective/pilot.py` (sha256 `d51a0c39...ef7`) is the dev15 pilot harness and is not the acceptance runner. The runner, the exact P0 configuration (model digest, prompt file hash, retrieval configuration hash, decoding parameters, seed) and the run guard must be written, reviewed, hashed and listed in the dev16 freeze. Writing them is preparation; running them is not.

**Run count.** One run per arm. The 7B's replay noise (about 5% in earlier replays) is reported as a sensitivity margin on the paired criteria, not as extra adjudicated replicates (the protocol forbids repeating a run).

**Pairing.** By case id. For a question, `fully_correct` is the evaluator's `fully_correct_v3` computed on each arm's row; "lost" = fully correct for P0 and not for the candidate, "gained" the reverse. Atoms pair by gold atom id.

**Where each arm's flags come from.** Candidate: exact, by `deterministic_criteria.py` (state, admitted values, ids, manifest). P0: a person's atom-level labels converted by `p0_adjudication.atom_outcome_from_label` into the same flags. The conversion was shown lossless on the candidate (all 307 dev15 atoms). Bad and unauthorised citations, claim-level id support, `fully_correct` and all ten criteria are computed by code on both arms.

**Evaluator runs.** `evaluator.evaluate` is run three times: with rater A's labels, with rater B's labels, and with the reconciled labels. All three are reported.

## 4. The ten criteria (evaluator v3; thresholds unchanged) and their calculations

Pass rule: **all ten** pass. Every failure is reported by case id. No post-hoc exclusions. The original statistics are reported even if a disagreement is later documented.

| # | Criterion | Calculation (as coded in `evaluator.py`) | Candidate / P0 source |
|---|---|---|---|
| 1 | unsupported material claims reduced by >= 30% vs P0, severe not higher | `red = 1 - leaks_cand / leaks_P0` (taken as 0 if P0 has no leaks, which then fails); pass iff `red >= 0.30` and `severe_cand <= severe_P0` | exact / human (ASSERTS) |
| 2 | false abstention: <= 1 additional and <= 3 pp | `extra = FA_cand - FA_P0`; `pp = extra / answerable atoms`; pass iff `extra <= 1` and `pp <= 0.03` (for 34 or more answerable atoms the binding limit is +1) | exact / human (NOT_ESTABLISHED, SILENT) |
| 3 | supported-sub-claim recall >= 90% of baseline | `SSR = stated SUPPORTED atoms / SUPPORTED atoms` per arm; pass iff `SSR_cand >= 0.9 * SSR_P0` | exact / human (STATES_ANSWER) |
| 4 | mixed questions fully correct: one-sided 95% lower bound >= 70% and paired non-regression | lower bound = Wilson with z = 1.645 on `k` of `n` mixed questions; plus `gained >= lost` on mixed pairs | exact; paired part needs P0 |
| 5 | zero nonexistent or unauthorised citations | `bad + unauthorised == 0` over the candidate's replies | exact |
| 6 | >= 95% claim-level citation support, floor of 40 cited claims | `faithful / cited >= 0.95` and `cited >= 40`; two-sided Wilson 95% interval reported | exact plus section 6 |
| 7 | no unsupported conflict resolution | 0 of `n` conflict atoms resolved; one-sided 95% upper bound reported | exact |
| 8 | no absence claim from unsuccessful retrieval | 0 of `n` negative-unsupported atoms; bound reported | exact |
| 9 | no invented temporal supersession | 0 invented orderings in `n` ordering atoms; bound reported | exact |
| 10 | at most 1 net loss of fully correct answers vs P0 | `lost - gained <= 1` over all question pairs | exact / human |

Computed thresholds (from `evaluator.wilson` and `upper_one_sided`; these are arithmetic on the frozen formulas, not a reading of dev16):

- **Criterion 4**, minimum fully correct mixed questions `k` for a lower bound >= 70%: n = 20 → 18; 25 → 22; 30 → 26; 32 → 27; 35 → 29; 38 → 32; 40 → 33; 45 → 37. The final `n` is fixed by the dev16 freeze; dev15's 26 of 30 was exactly at the minimum.
- **Criterion 6**, most misses allowed at 95%: floor of 40 cited claims → 2; 60 → 3; 100 → 5; 150 → 7; 191 → 9; 250 → 12. (dev15: 183 of 191, two-sided Wilson 92.0% to 97.9%.)
- **Criteria 7 to 9**, one-sided 95% upper bound on the event rate when 0 events are seen in `n`: n = 6 → 39.3%; 9 → 28.3%; 10 → 25.9%; 19 → 14.6%; 20 → 13.9%; 30 → 9.5%; 50 → 5.8%; 100 → 3.0%. The informational reference bound of 10% needs `n >= 29`. dev15 coverage was 19 conflicts, 6 absence atoms and 9 ordering atoms, which does **not** reach it: a zero there bounds the rate, it does not prove safety. This is reported with the count, as before.

## 5. Criterion 5 and the authorisation facts

Authorisation and scope are **code facts**, never reviewer judgements: whether a cited record is authorised for the asking principal comes from the evaluation world's access decisions and the manifest builder. A cited record that is not authorised is a criterion-5 failure regardless of what it says.

## 6. Citation-discrepancy adjudication (criterion 6) — prospective, blinded

**Scope.** Applied to the **candidate's** cited claims on dev16 only. It does not touch any frozen dev15 result: the 8 dev15 discrepancies (true claims citing `memory:m100`-type records) stay mechanically failed in their frozen files and are not re-judged into a result.

**What is reviewed.** (a) Every cited claim the mechanical check marks unsupported (100%, not sampled). (b) Every claim whose subject is bound by context, title or speaker rather than by its own sentence. (c) A seeded sample of 30 mechanically supported direct-bound claims, as a leniency control. All are mixed in one shuffled stream; the reviewer is not told which are which, nor which arm, nor the mechanical verdict.

**What the reviewer sees, per claim.** The question, the claim sentence, the gold value, each cited record's text with its id, and two **code-supplied facts** per cited record: authorised for this principal (yes/no) and in the case's retrieval scope (yes/no). The reviewer does not judge those two.

**What the reviewer decides.** One of three outcomes, and for outcome 1 must quote the span of the cited record that states the claim:

1. **Manifest omission.** The cited record is authorised and in scope, its own text supports the specific claim (right subject, right relation, right value, right time), and it is simply not among the atom's registered sources. *Eligible for adjudication.*
2. **Supported only by an unauthorised or out-of-scope record.** The claim is supported by a record the code facts mark unauthorised or out of scope. *Not eligible: stays failed* (and is a criterion-5 failure if the record is unauthorised).
3. **The citation does not support the specific claim.** The cited record is the wrong record, mentions the subject but not this value, supports a different proposition (for example a decision cited for a configured value, a different period, another subject), or only supports the claim together with other text not cited. *Not eligible: stays failed.*

A decision cited as proof of a current configuration is outcome 3. A claim whose cited record supports it only through a relative time the record cannot anchor is judged on what the record literally says, never on the calendar.

**Two reviewers.** Reviewer A and reviewer B judge independently. Outcome 1 counts only when **both** choose it; any disagreement is treated as not eligible (the conservative reading) and listed.

**Reporting.** Criterion 6 is reported as two figures side by side: the **mechanical** verdict exactly as the frozen evaluator computes it, and the **adjudicated** verdict, `(mechanically supported + both-confirmed outcome-1 claims) / cited claims`, with the same >= 95% threshold and 40-claim floor. Both are in the record with every adjudicated claim listed by case id, the quoted span and both reviewers' outcomes. Where the two verdicts differ, the record says so in its first line. The threshold is not altered and the denominator is not changed. Adjudicated outcomes are stored in a new file next to the frozen results; no frozen result file is edited.

**Reading of the owner's decision that the owner is asked to confirm at execution approval.** The adjudicated verdict is the documented, discrepancy-adjusted verdict and is the one the pass rule reads, the mechanical verdict being reported next to it and never suppressed. If the owner prefers the mechanical verdict to govern, only the label of which figure gates the pass changes.

## 7. Blinded review packet construction and sample sizes

Tool: `p0_adjudication.py` (`build_packet`, `render_packet`, `write_dry_run`, `complete`, `agreement`, `control_agreement`), rehearsed on dev15 in `results/p0-adjudication-dryrun-dev15/` (208 replies, 373 parts, nothing labelled).

| Packet | Contents | Expected size (estimate; fixed at the freeze) |
|---|---|---|
| P0 labelling | every P0 reply, every gold atom | about 218 replies and 390 atoms (the protocol's stated case count and dev15's 1.77 atoms per question) |
| Control | seeded 20% of the candidate's replies in the same stream | about 44 replies, 78 atoms |
| Total per reviewer | | about 262 replies, 470 parts; about 6 to 7 hours at 1.5 minutes per reply |
| Criterion 6 | all mechanically unsupported cited claims, all context/title/speaker-bound claims, 30 direct-bound controls | dev15 rate suggests roughly 10 to 25 claims to review; not predicted for dev16 |

**Construction and blinding.** Seeded shuffle (rehearsal seed 20261012; the dev16 seed is fixed at the freeze); opaque ids derived from seed, arm and case id; arm names, the sealed key and any evaluator output never appear in a reviewer's files; packet, label template and sealed key are written with a hash manifest so the packet cannot change after the key exists. **Limit, stated plainly:** the candidate's code-written replies are recognisable by their wording, so reviewers are not blind to which replies are templated. The protection is that every label is a defined atom-level choice against a stated gold answer, not a preference between replies, and the control measures it: on the candidate replies in the stream, the reviewer's label-derived flags are compared with the exact flags of the same replies. A systematic disagreement is resolved before any P0 verdict is read.

**Labels** (eight, enforced by code per gold status): STATES_ANSWER, WRONG_VALUE, NOT_ESTABLISHED, ASSERTS, CONFLICT_BOTH, CONFLICT_ONE, HISTORY_AS_CURRENT, SILENT; plus the evidence ids attached to a statement and a blanket-refusal flag per reply.

**Unblinding order.** Labels complete and hashed → agreement computed → key unsealed → rows built → evaluator run. Nobody reads evaluator output before labels are sealed.

## 8. Reviewer identity and independence status

| Role | Who | Status |
|---|---|---|
| Reviewer A | the author of the pipeline (the AI coding assistant that built the candidate in this repository's sessions) | **Not independent.** Wrote the candidate, the relation definitions, the label rubric and the review tooling. All manual judgements so far (wording review of 51 + 28 + 14 items) are by this reader. |
| Reviewer B | **not named, not confirmed** | Required for any independence claim. Must be a person who did not write the candidate, is blind to the arm key and labels the packet independently. |
| Independence claim | **None is made.** | Made only when reviewer B is confirmed **and** has completed the review **and** agreement is reported. Until then every record carries "NO INDEPENDENT HUMAN REVIEW". |

**Agreement.** Cohen's kappa over atom labels and percent agreement (`p0_adjudication.agreement`), target **kappa >= 0.80** for any independence claim. Disagreements are reconciled by a written rule or a third reader before the reconciled run. Verdicts are reported under A, under B and reconciled; a criterion that flips between raters is called rater-dependent. If kappa is below 0.80, the P0-relative criteria (1, 2, 3, 4 paired, 10) are reported as **not established**, not as passed, and no independence claim is made.

## 9. One-shot execution, stopping and failure rules

**Preconditions (all must hold; none holds today):** owner approval of the formal execution; reviewer B named and confirmed; the guarded runner and P0 configuration written, reviewed and hashed; the dev16 freeze manifest written (cases, bank files, `evaluator.py`, `aq/scoring.py`, the candidate manifest, this page, the runner, the packet tooling, seeds) and verified by a `freeze_check` and a test; the decision-point file `AQ_DEV16_APPROVAL` present; `candidate_freeze.py --check` passing on a clean working tree at the recorded commit; the model server healthy; no author having read dev16 other than generators.

**Execution.** One run per arm, one run log. The candidate run is deterministic and cheap; the P0 run is one pass of the 7B over every frozen question.

**Failure rules.**
- An infrastructure failure (server down, process killed, timeout storm, disk full) **aborts the whole run**; it is recorded and not repeated without an explicit owner decision.
- A model that returns an empty or refusing reply for a question has produced a reply (a blanket refusal); it is labelled, not retried.
- The candidate is never edited after the dev16 freeze. A defect found is reported by case id; a change means a new candidate, new freeze and new acceptance.
- No reviewer is shown evaluator output, the key or the other reviewer's labels before sealing.
- No post-hoc exclusions; the original statistics are reported; criterion thresholds and the all-ten pass rule do not change.

**Stopping rules.** The run stops on the first infrastructure failure. Adjudication stops only when every part is labelled (`p0_adjudication.complete`). Reporting stops at "not established" for any criterion that depends on labels whose agreement is below target. After the report, execution stops again for the owner.

## 10. Remaining limitations and known test failures

**Limitations.**
- dev15 is the design set; its results (294/307 exact, 160/173 fully correct, 13 false abstentions, 0 unsupported) are not predictive of dev16. The dry-run pass of all ten criteria on dev15 is not an acceptance pass; criterion 4 sat exactly at its minimum and criterion 6 at 95.8% (all 8 misses true claims citing an unregistered record).
- Question-phrasing generalisation is unmeasured: the decomposer's own sets (93.9% with 1 invented structure; 96.2% first contact with 1 invented on the new-relation set) are author-written and not independent. Bank D will be the first independent measurement and its fallback rate is unknown.
- The three formerly held-out relations are defined; the held-out-*relation* property no longer applies to this path (held-out projects and bank D remain unseen).
- Known coverage gaps, all withheld rather than answered: decision-only default models (7 dev15 atoms), "serves X" documents that never say "default", documents excluded as instruction-bearing, "what was decided about X's default model" (two relation cues), verb-after-subject record forms, and any question that names a relative period.
- A record's relative time stays unanchored; a past-tense completed switch is stated as the current value, as any undated statement is.
- Coverage for criteria 7 to 9 may not reach the 10% reference bound; a zero will be reported with its bound.
- No independent human review exists anywhere in this work. The lexical scorers v1 to v3 failed validation and are research-only; the 35 / 70.1% dev15 baseline figures come from one of them and are indicative only.
- No real database, process, image or API was exercised; everything is in-process and offline.

**Known test failures.** Companion-core at the final development pass: 1,633 passed, 77 skipped, 2 failed. The two failures are pre-existing, need a database, and fail identically on a clean tree: `tests/test_knowledge_index.py::test_reconcile_repairs_a_missing_stale_orphaned_and_expired_index` and `tests/test_knowledge_retrieval.py::test_historical_mode_reaches_the_prefilter_and_revalidation`. The `test_knowledge_index` contention-tool tests are intermittent (a different one per run; also on a clean HEAD; pass in isolation). No new failure was introduced. `ruff check .` passes. Two stale links in HANDOVER.md (`docs/proposals/postgres-backup-hardening.md`, `docs/phase-30.md#visible_false_activations_per_hour`) predate this work.

**Unchanged and verified:** the first-run I-2 reports, the dev8/10/12/14 freezes, the scorer seals, `selective/acceptance/`, `cases_dev16.json`.

## 11. Awaiting the owner

Approval of the formal acceptance execution, which needs: reviewer B named; the P0 runner and configuration written (a separate, bounded preparation step the owner may authorise now); confirmation of the reading in section 6 (which criterion-6 figure gates the pass); the dev16 seed; and the date of the dev16 freeze. Nothing runs before then.
