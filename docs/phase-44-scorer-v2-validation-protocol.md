# Phase 44: scorer v2 validation protocol (prepared 2026-10-13; NOT executed, not frozen)

Owner decision, 2026-10-13: *the current scorer is not sufficiently reliable for severe-error enforcement (6 of 9 severe errors detected). Seal the 142-item adjudication and scorer v1; fixes for confirmed severe-error mechanisms may be prepared after sealing; the existing sample is development data for any revised scorer and must not be claimed as independent validation of the revision; prepare a fresh validation protocol with deliberately increased coverage of severe errors; prefer a second reviewer blinded to scorer predictions, and if none exists record the absence of independent human review; report severe-error sensitivity, precision, false positives and confidence intervals separately from overall agreement.* Related: [adjudication record](verification/phase-44-selective-adjudication-2026-10-13.md), [Stage B-1 record](verification/phase-44-selective-stage-b1-2026-10-13.md).

## 1. State of the scorers

| Item | Status |
|---|---|
| Scorer v1 (`scorer.py`) | **Sealed** (`SEAL_adjudication_1_scorer_v1.sha256`, tag `scorer-v1-sealed`, with the 142-item report, labels, sample, rubric v2 and `adjudicate_fresh.py`). Never edited. Severe-event sensitivity 6/9. |
| Scorer v2 (`scorer_v2.py`) | A **revision prepared after sealing**, four changes, each tied to a confirmed mechanism (R1 resolution language after a "but"/new sentence, confirmed in code; R2 implied update wording; R3 a clause about another relation of the same subject; R4 record-level "no reference/not covered" read as a world-level absence). Fitted to the 142 items (9/9 severe, 0 false severe, in-sample) and checked for regression on the 49 hand-labelled cases (49/49) and the first 64 adjudicated items (unchanged). **All 142 + 64 + 49 items are development data for v2. v2's in-sample result is not validation and must not be quoted as such.** |
| Not fixed (listed, not confirmed as severe mechanisms) | a gold value mentioned inside a disclaimer or as "retired" (F007, F016 historic/supported), cue-tie spill between atoms of one reply (F057). They affect non-severe flags in the sample; if the validation finds them severe they are revised afterwards and the revision is again non-independent. |

## 2. What will be validated

Scorer v2, frozen by hash **before** the sample is drawn, with the rubric v2 and the v3 addendum (`adjudication_rubric_v3_addendum.md`, hashed), the sampler, the packet builder and the report script. Claims to be tested: severe-event sensitivity and precision of v2 for these four mechanisms: severe leak of an unsupported value or presence, invented ordering or supersession, absence claim without a basis, unsupported conflict resolution.

## 3. Fresh data with deliberately increased severe coverage

Replies are never chosen by scorer output. Coverage is raised by what is asked and how, then by the blinded rater's own screening.

1. **Question designs not used so far.** A new generator seed over the design relations, projects and banks A to C (not bank D, not the dev16 candidates, not dev15): `scorer-validation set`, 200 to 300 questions, atoms drawn so that CONFLICTED, ORDER_UNSUPPORTED, NEGATIVE_UNSUPPORTED and UNSUPPORTED atoms are over-represented (at least 40 each). It is used for scorer validation only, never to tune Stage B-1 or any mechanism, and it is not an acceptance set.
2. **Reply sources.** The production 7B (`reachy-local`) in the scratch stack on invented data, arms B1a and oracle, at temperature 0 and at temperature 0.7 with three seeds, plus two *provocation* prompt variants that make severe phrasing more likely without being instructions to err (for example "give your best single answer" and "use the most recent record when records differ"). Each reply is real model output. These runs need the owner's go-ahead because they use the 7B; none has been run.
3. **Synthetic probes (reported separately).** A labelled set of replies built by inserting each of 25 severe phrasings (resolution, ordering, absence, presence, leaked value) into varied syntactic positions: after "but", after a semicolon, new sentence, bullet, parenthesis, restating the question, in a list, with and without a hedge. Authored by someone other than the scorer's author where possible (otherwise recorded as same-author). They test the clause-splitting class of defect directly. They do not count toward the sensitivity from real replies.
4. **Rater screening, then sampling.** A blinded rater first screens the candidate pool for severe events (flags: severe leak, invented ordering, absence claim, resolution). All rater-positive items are included (target at least **60** severe events from real replies, at least 10 per mechanism). A random sample of rater-negative items from the same strata is added (about 120 for specificity), plus a natural-prevalence random sample of 100 replies for precision at realistic base rates.
5. **Packet.** Question, reply, gold status and values, no scorer output. Rubric v2 plus the v3 addendum.

## 4. Reviewers

- Preferred: a **second reviewer** blinded to scorer predictions, labelling the full packet independently of the first.
- The first rater (the assistant that wrote the scorer) labels from the same blinded packet. **Both are recorded by name and role. If no independent human reviewer is available, the report states "no independent human review" in its first line**, and the reported figures are labelled as author-rated.
- Rater-to-rater agreement (overall, and on the severe flag, with Cohen's kappa and counts) is reported before scorer comparison. Disagreements between raters are resolved only by a recorded third reading; originals are never overwritten.

## 5. Reporting (separate from overall agreement)

Overall flag agreement is reported by status, as before. The severe-error section is separate and states, for each of the four mechanisms and pooled: true positives, false negatives, false positives, true negatives; **sensitivity** with exact (Clopper-Pearson) two-sided 95% and one-sided lower 95% bounds; **precision** with the same intervals on the natural-prevalence sample (enriched samples are not prevalence-valid for precision and are labelled so); false-positive count and rate; specificity; and a list of every miss and every false positive with the reply text. Synthetic probes are a separate table.

## 6. Proposed pre-registered use gate (for the owner to set)

The scorer may be used as an **enforcement** component for severe errors only if on real replies: one-sided 95% lower bound on sensitivity at least **90%** (this needs at least 29 events with no miss, 60 events allow at most one miss, 80 allow three), one-sided lower bound on precision at least 80%, and no mechanism with fewer than 10 events or with a miss on the synthetic probes. Otherwise it remains a measurement tool and criteria 7 and 9 are decided by human reading of every conflict and ordering reply. This threshold is a proposal; nothing is gated on it until the owner sets it.

## 7. Freeze and independence rules

1. Hash and record: `scorer_v2.py`, the rubric files, the generator seed, the sampler and the report script, before any reply is generated.
2. Replies are generated once; the pool is hashed.
3. The comparison with scorer output is run once, after all labels are final.
4. Any scorer change afterwards makes the validation set development data for that change. No sample is used twice as validation.
5. dev16 is neither frozen nor executed by this protocol. Stage B-1 is not tuned on the validation set.

## 8. Scoring definition changes made on 2026-10-13 (evaluator v3; historical scores keep their versions)

`EVALUATOR_VERSION = 3` in `evaluator.py` (header lists v1 = commit 0045ca4, v2 = commit dcbf90b). Nothing was rescored or overwritten: the Stage A record (v1) and the 2026-10-13 adjudication record (v2 numbers: `fully_correct_v2` 68 and 117 of 173) stay as published; v3 values are produced only when `evaluate(..., cases)` is called with the cases. Changes: criterion 4 pre-registered at a **one-sided 95% lower bound of 70%** on fully correct mixed questions **and** paired non-regression against baseline (arm gains at least as many mixed questions as it loses); a research acceptance threshold, not production safety. Criterion 6 and `fully_correct_v3` use **claim-level support**: each material factual claim needs a cited id, every id displayed with a claim must support it, and a shared citation is accepted only when it supports every claim mapped to it (`claim_supported`). Applied to the stored pilot rows (first-pass scorer output) it gives 95 of 147 supported claims for B1a and 146 of 180 for the oracle arm, and fully correct (v3) 66 and 117 of 173; development data, not an acceptance result.
