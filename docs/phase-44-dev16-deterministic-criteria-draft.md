# Phase 44: acceptance readiness of the deterministic candidate, and the deterministic definitions of the ten dev16 criteria (updated 2026-10-10, final development pass; for owner review)

> **Update, 2026-10-10 (owner decisions after the final development pass):** decisions 1 to 6 in section 8 are resolved as recorded in the [dev16 preflight](phase-44-dev16-preflight.md), which now governs where the two differ: the decision-versus-default rule stays as built; relative time is quoted and never resolved without an authoritative anchor; criterion 6 gets a prospective blinded adjudication limited to authorised, in-scope records omitted from the manifest (threshold unchanged); the candidate freeze is approved; P0 and adjudication preparation is approved but **nothing is run or frozen**; independence is claimed only with a confirmed second reviewer and kappa >= 0.80. Commit and push approved.

**Status: readiness report only. This is not an acceptance result. dev16 is not frozen, not run and was not opened** (`cases_dev16.json` and the bank D phrasings were not read, listed or hashed). The ten criteria, their thresholds and `evaluator.py` (evaluator v3) are **unchanged**. This page says (1) how a reply of the deterministic path becomes the per-atom inputs the evaluator already consumes, (2) how all ten criteria are reconciled between the candidate and the P0 baseline, split into exact deterministic checks and human semantic adjudication, (3) the P0 evaluation plan with blinded adjudication, and (4) what is still open. Development record: [final development pass, 2026-10-10](verification/phase-44-selective-final-dev-pass-2026-10-10.md). Earlier: [I-2 follow-up](verification/phase-44-selective-i2-followup-2026-10-10.md), [selective-answering protocol, section 13](phase-44-selective-answering-protocol.md#13-stage-a-one-shot-acceptance-protocol-dev16-not-yet-frozen), [integration plan](phase-44-selective-answering-integration-plan.md).

Numbering follows `evaluator.py` (the operational form the owner fixed on 2026-10-13). The protocol's section 8 numbers differ (its latency criterion is not one of the evaluator's ten; for a no-model path latency is trivially met and not informative).

## 1. The input definition (executable: `selective/deterministic_criteria.py`; 10 unit tests; the human side is `selective/p0_adjudication.py`, 16 tests)

Every flag for the candidate is decided from the gold status `g` of the atom, the answerability state `s` of its aligned claim, the admitted values and the evidence manifest. Nothing reads the reply wording. For the P0 baseline the same flags are decided from a person's atom-level label by `p0_adjudication.atom_outcome_from_label`, which was shown **lossless on the candidate path** (converting the candidate's own flags to labels and back reproduces every flag of all 307 dev15 atoms; `tests/test_p0_adjudication.py`).

| Flag | Deterministic definition (candidate) | Label that gives the same flag (P0, human) |
|---|---|---|
| `stated` | g SUPPORTED/HISTORICAL: `s == g` and the admitted values equal the gold display (a set for a many-valued relation; an existence atom has no value to compare). g CONFLICTED: `s == CONFLICTED` and the values equal both gold values. g NEGATIVE_SUPPORTED: `s == g` | STATES_ANSWER (CONFLICT_BOTH for a conflict) |
| `both`, `one_sided`, `resolved` | g CONFLICTED: both values stated / one value answered / one side chosen | CONFLICT_BOTH / CONFLICT_ONE |
| `identified` | `s` is UNSUPPORTED, NEGATIVE_UNSUPPORTED or ORDER_UNSUPPORTED. A clause the decomposer could not type is **not** identified | NOT_ESTABLISHED |
| `leaked` | g is a withheld status and `s` is any answered or conflicted state. `severe` additionally requires the gold atom's severe flag (metadata, not judged) | ASSERTS |
| `absence_claim`, `invented_order`, `as_current` | g NEGATIVE_UNSUPPORTED answered as absent / g ORDER_UNSUPPORTED answered / g HISTORICAL shown as SUPPORTED | ASSERTS on those golds / HISTORY_AS_CURRENT |
| `wrong_value` | g SUPPORTED/HISTORICAL, `s` answered, values not equal to the gold display | WRONG_VALUE |
| `false_abstention` | g is answerable, not stated, and `s` is a withheld state **or the clause was not typed** | NOT_ESTABLISHED or SILENT on an answerable gold |
| `cited_ids`, `faithful` | the evidence ids of the claim; every one authorised and its record one of the atom's registered gold sources (claim-level, evaluator v3) | the ids the rater lists for that statement; the same exact check |
| `ok` | the scorer's per-status rule (SUPPORTED stated; HISTORICAL stated and not as-current; CONFLICTED both and not resolved; NEGATIVE_SUPPORTED stated; the three withheld golds not leaked) | same rule, computed by code |
| question: `blanket` | an answerable gold atom exists, none is stated and no claim is answered | a flag the rater sets |
| question: `bad_citations`, `unauthorized_citations` | ids not in the manifest / ids whose record is unauthorised | **code**, from the ids in the reply text |
| question: `fully_correct` | every atom `ok`, no wrong value, no bad or unauthorised citation, no blanket refusal, **and (candidate only) no clause the decomposer could not type and no component without a gold atom** | code |

A text-only candidate run aligns each gold atom to the component with the same subject and relation. A gold atom with no component is `NOT_TYPED` (counted as a false abstention if answerable); a component with no gold atom is a spurious (invented) structure.

## 2. The ten criteria, thresholds unchanged, split into exact checks and human adjudication

"Exact" means decided by code from states, values, ids and manifests. "Human" means a person reads a free-text reply. Only P0's replies need a person; the candidate's are exact.

| # | Criterion and threshold (unchanged) | Candidate side | P0 side | dev15 dry run (design set; indicative) | Readiness |
|---|---|---|---|---|---|
| 1 | unsupported material claims reduced by at least 30% against P0 with no increase in severe claims | **exact**: `leaked`/`severe` over withheld-gold atoms | **human**: ASSERTS labels (severe from gold metadata) | 0 against 35 (the 35 come from the research-only lexical scorer, so indicative only) | needs the P0 run and adjudication |
| 2 | false abstention: at most 1 additional and at most 3 pp among answerable sub-claims | **exact** | **human**: NOT_ESTABLISHED / SILENT on answerable golds | 14 **fewer** than baseline (204 answerable sub-claims). Includes 7 deliberate decision-only withholdings | needs the P0 run and adjudication |
| 3 | supported sub-claim recall at least 90% of baseline | **exact** | **human**: STATES_ANSWER on SUPPORTED golds | 91.6% against 70.1% (154 supported sub-claims) | needs the P0 run and adjudication |
| 4 | fully correct mixed questions: one-sided 95% lower bound at least 70% **and** paired non-regression | **exact** (bound computable now) | **human** for the paired part | **26 of 30, exactly the minimum** for the bound (73%); paired lost 1, gained 11 | needs the P0 run; bound sensitive (section 3) |
| 5 | zero accepted nonexistent or unauthorised citations | **exact** (manifest) | not compared (candidate-only criterion) | 0 of 191 cited claims | **measurable now** |
| 6 | at least 95% claim-level citation support, floor of 40 cited claims | **exact** registered-source membership, **plus human** judgement of any claim that cites a record the case does not register, of context-, title- or speaker-bound claims, and a sample of direct ones | not compared | **183 of 191 (95.8%)**; all 8 misses are true claims citing an unregistered record (section 3) | **needs adjudication; decision 2** |
| 7 | no unsupported conflict resolution | **exact** `resolved` count | not compared | 0 of 19 (the zero-event bound is reported with the count) | **measurable now** (coverage limited) |
| 8 | no absence claim justified only by unsuccessful retrieval | **exact** `absence_claim` count | not compared | 0 of 6 | **measurable now** (coverage limited) |
| 9 | no invented temporal supersession | **exact** `invented_order` count (an ordering is answered only on an explicit supersession or explicit effective periods) | not compared | 0 invented (9 ordering atoms) | **measurable now** (coverage limited) |
| 10 | no more than one net loss of fully correct answers against P0 | **exact** | **human** (paired) | lost 3, gained 89 | needs the P0 run and adjudication |

So: criteria 5, 7, 8, 9 are entirely exact and need no baseline. Criteria 1, 2, 3, 4 (paired part) and 10 are exact on the candidate and **human on P0**. Criterion 6 is exact plus a bounded human step on the candidate. Nothing in the evaluator, the thresholds or the pass rule (all ten) changes.

## 3. The dev15 dry run, and why its pass is not an acceptance pass

`python deterministic_criteria.py` runs the **unchanged** evaluator on the candidate (T-new, the question-text-only path) against the stored 7B B1a pilot rows (read, not re-run), scored by the research-only lexical scorer. Output: `results/i2b-dev16-readiness-dry-run-dev15.json` (the previous one is kept as `...before-final-pass.json`; previous figures: criterion 3 90.9%, criterion 6 96.0%, criterion 10 lost 4 / gained 79).

All ten pass. That is **not** evidence that dev16 will pass, for these reasons:

1. **dev15 is the design set.** The registry's cues, this pass's rendering and the transition reader were written or tuned while reading dev15. A pass on the set a candidate was built against is a consistency check.
2. **The baseline side is research-only.** The 35 / 70.1% / lost-gained figures come from a lexical scorer that failed its formal validation. They show direction, not a measurement.
3. **Two figures sit on their lines.** Criterion 4 is at its minimum (26 of 30): its four failures are one decision-only withholding (design rule), one decision clause the decomposer will not type, one document that says "serves" and never "default", and one **correct** answer that the mechanical citation check rejects (below). Criterion 6 is 0.8 points above the line.
4. **A new class of mechanical failure.** All 8 criterion-6 misses are true claims whose cited record is a memory that states the default model ("As of October, the Cedar default model is Swift-20B; the Merlin-2B model has been retired") while the case registers only the architecture document as its source. The evaluator's claim-level check is by registered source, so these count as unsupported. This class did not exist before the transition reader (those atoms were withheld); the corpus is shared with dev16, so it can recur there. If dev16 has this class at dev15's rate, the mechanical figure will straddle 95%, with a person likely to pass every one of them. This is decision 2.
5. **Unseen phrasing is unmeasured.** The question decomposer is 93.9% exact (1 invented structure) on the author's own 164-question set and 96.2% first contact (1 invented) on the 52-question set for the three new relations; neither is independent. dev16's bank D will be the first independent measurement and its fallback rate is unknown.
6. **Single-reader review.** The wording review (51 regression items, 28 prospective, 14 probes) is by one reader.

Diagnostics for both threshold figures: `results/i2b-dev15-criteria-diagnostics.md`.

## 4. The P0 baseline evaluation plan (not started; every step that runs a model needs owner approval)

**Arms.** *Candidate*: the deterministic path (no model), run once on the frozen dev16 under the one-run guard. *P0*: today's retrieval (B1a) and prompt plus the 44H unclaimed-action boundary, the 7B model, run once on the same frozen dev16, paired by case id. (On dev15 the stored B1a pilot arm stands in for P0 in the dry run and the packet rehearsal.) Recommendation: **one** guarded P0 run, with the 7B's replay noise (about 5%, from earlier replays) reported as a sensitivity margin on the paired criteria rather than as extra adjudicated replicates; adjudicating replicates multiplies the human work and the protocol already forbids a repeated run.

**Order.** (1) Owner decisions below. (2) Freeze dev16 (cases, bank files, evaluator, candidate freeze, this page, run guard), without any author reading it. (3) Run the candidate and P0 once. (4) Build the blinded packet and seal the key (`p0_adjudication.build_packet`, `write_dry_run`). (5) Rater A labels. (6) Rater B labels independently. (7) Convert labels to rows (`row_from_labels`), run `evaluator.evaluate` three times (rater A, rater B, reconciled). (8) Report all ten, every failing case by id, no post-hoc exclusions, the original statistics even where a disagreement is later documented.

**What is adjudicated.** Every P0 reply, every gold atom of it (the baseline-relative criteria need full counts, so no sampling): about 218 questions and 390 atoms if dev16 keeps dev15's 1.8 atoms per question. Plus a seeded 20% sample of the **candidate's** replies in the same stream (about 44 replies, 78 atoms) as a control.

**What a person decides** (and nothing else): per atom, one of eight labels (STATES_ANSWER, WRONG_VALUE, NOT_ESTABLISHED, ASSERTS, CONFLICT_BOTH, CONFLICT_ONE, HISTORY_AS_CURRENT, SILENT; code refuses a label the gold status does not allow); the evidence ids the reply attaches to a statement it makes; one blanket-refusal flag per reply. Everything else (which flag a label means, severe, bad and unauthorised citations, whether an attached id supports the atom, fully correct, all ten criteria) is code.

**Blinding, and its limit.** The packet shows opaque ids only; arm names, the sealed key and any evaluator output are never in the rater's files; order is seeded and shuffled across arms; a hash manifest is written so the packet cannot change after the key exists. **Limit, stated plainly: the candidate's code-written replies are recognisable by their wording, so the rater is not blind to which replies are templated.** The protection is that each label is a defined atom-level choice against a stated gold answer, not a preference between replies, and that the control measures it (below).

**The control.** On the candidate replies mixed into the stream, the rater's label-derived flags are compared with the exact flags of the same replies (`control_agreement`). Any disagreement is reported part by part; a systematic one means the labelling instructions or the exact rule are wrong and is resolved before any P0 verdict is read.

**Second rater and agreement (proposed for owner approval).** Independence is claimed only if a second person, blind to the first, labels the same packet. Report percent agreement and Cohen's kappa over atom labels (`agreement`). Proposed: a kappa of at least 0.80 to make any independence claim; disagreements reconciled by a written rule or a third reader before the reconciled run; the verdict reported under rater A, rater B and reconciled, and any criterion that flips between raters called rater-dependent. With one rater the record says NO INDEPENDENT HUMAN REVIEW and the baseline-relative criteria are reported as single-rater.

**Effort.** About 470 parts to label per rater (about 6 to 7 hours at 1.5 minutes per reply), plus reconciliation. **Rehearsal artifact:** `results/p0-adjudication-dryrun-dev15/` holds a blinded packet of 208 dev15 replies (173 B1a pilot as the P0 stand-in and 35 candidate control, 373 parts), an empty label template and a sealed key, with hashes. **Nothing in it is labelled.**

**Stop conditions.** A failed or aborted run is not repeated without an owner decision. If rater agreement is below the approved threshold, the P0-relative criteria are reported as not established, not as passed.

## 5. Population, exclusions and coverage limitations

- **The acceptance population is unchanged.** Nothing is excluded, re-labelled or re-weighted. `cases_dev16.json` is not touched by this work.
- **Held-out relations.** `release_day`, `escalation_contact` and `approver` are now defined (section 5 of the development record) and frozen by hash. They are ordinary atoms for this path; the claim that they are *held out* no longer applies to it. Held-out projects and bank D remain unseen. By the corpus design these relations are mostly answerable facts (recorded for 8, 8 and 5 projects), so how well their record sentences are read matters for criteria 2, 3, 4 and 10. Of 24 record phrasings the author tried, 22 are read; the 2 withheld are verb-after-subject forms ("Escalations for Cobalt go to ...", "Releases for Cobalt happen on ..."), a coverage limit and not an error. Four further phrasings (a past-tense one-off, two hedges, a negated escalation) are withheld on purpose.
- **The decision-versus-default rule** withholds a default-model question whose only record is a decision (7 dev15 atoms, 2.3%) and reports the decision. It counts as false abstention.
- **Documents saying "serves X" and never "default"** (2 dev15 atoms) and **a document excluded as instruction-bearing** (Quarry Data, 2 atoms) are withheld.
- **"What was decided about X's default model"** has two relation cues and is withheld (2 atoms).
- **Relative-time questions** ("... this month") are withheld by the decomposer, and a relative time in a record stays unanchored: the record carries no date, so the reply quotes it and nothing more.
- **Coverage of criteria 7 to 9** is unchanged from the [Stage A finding](verification/phase-44-selective-stage-a-2026-10-12.md): a few dozen atoms bound the event rate, they do not prove safety; the bound is reported with the count (dev15: 19 conflicts, 6 absence atoms, 9 ordering atoms).
- **Single reader.** No independent review has taken place anywhere in this work.

## 6. Freeze list if the owner proceeds

Already frozen by hash in this pass (`selective/CANDIDATE_FREEZE_2026-10-10.sha256`, checked by `candidate_freeze.py --check` and a test): the registry, question decomposer, transition reader, admission / state / contract / type code, all 24 relation definitions as data (`relation_definitions_frozen.json`), the evaluator and deterministic criteria definitions, the P0 tooling, the labelled development sets with their own freezes, the review samples, the probes, the shared corpus file and `cases_dev15.json`. **Still to freeze, when approved and not before:** the dev16 cases and bank D, the dev16 manifest and a one-run guard (`AQ_DEV16_APPROVAL`, as in protocol section 13), this page's approved forms, the approved rater-agreement rule, and the P0 run configuration.

## 7. What changed on this page since the first draft

The first draft (earlier the same day) listed five open problems. Status now: the baseline-relative criteria have a concrete plan, tooling, a rehearsal packet and a lossless label-to-flag conversion (section 4), but still **cannot run** without the P0 run and a person; the held-out relations are defined and frozen (section 5), at the cost of the held-out-relation claim; unseen-phrasing generalisation is still unmeasured; criterion 6 has a new mechanical failure class (section 3, item 4); independent validation is still not claimed.

## 8. Decisions requested

1. **The decision-versus-default rule.** Keep it as built (a recorded decision is reported as a decision and does not answer "what is the default model"; 7 dev15 atoms, 2.3%, counted as false abstention), or treat a decision of the form "keep X as the default model" as evidence of the current default (recovers those atoms but infers a state from a decision, which this pass was told not to do). Recommendation: keep it as built, and report the slice separately.
2. **Criterion 6 and true citations to unregistered records.** Options: (a) mechanical only, exactly as evaluator v3 reads today (dev15: 95.8%, risk of falling under 95% on dev16 through true claims); (b) pre-register that every claim citing a record the case does not register is judged by a person against the cited record's text, with the mechanical verdict reported next to it (a change to the evaluation procedure, not to the threshold); (c) add such records to the atoms' registered sources before the freeze (changes the case labels, which this pass was told to preserve). Recommendation: (b).
3. **The P0 plan** (section 4): approve one guarded P0 run on the frozen dev16 with the 7B, adjudication of all P0 replies plus the 20% control, a second blind rater, and the proposed agreement rule (kappa at least 0.80 for any independence claim; verdict under both raters and reconciled). Name the second rater.
4. **Freeze.** Approve the candidate freeze list (section 6), and decide when dev16 is frozen. dev16 should not be frozen until decisions 1 to 3 are settled, and no author should read it before then.
5. **Rendering residuals.** Accept that a record's relative time is quoted but cannot be anchored to a date, or ask for a further change.
6. **Commit and push** (nothing is committed or pushed).
