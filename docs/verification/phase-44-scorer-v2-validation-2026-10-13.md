# Phase 44: scorer v2 validation results (2026-10-13; scorer not modified after the freeze; nothing deployed)

**No independent human review.** The only rater is the assistant that wrote the scorer. A second blinded human reviewer was preferred and was not available; the packet and a template are ready (`validation/validation_packet_BLINDED.*`, `validation_labels_raterB_TEMPLATE.json`). Every number below is author-rated and must not be described as independent human review.

Owner decisions, 2026-10-13: validation runs approved on the new validation corpus, scratch infrastructure and the 7B only; the revised gate; natural 7B output and synthetic probes kept as separate populations; report each severe category separately. Protocol: [scorer v2 validation protocol](../phase-44-scorer-v2-validation-protocol.md) (section 6 now carries the owner's gate). Production unchanged; dev16 unfrozen, unrun and unused; B-1 was not tuned on any of this.

## 1. What was run

| Item | Detail |
|---|---|
| Corpus | `validation_gen.py`: the same generator at **seed 17** (different people, values and records than corpus v4), design relations and projects only, phrasing bank C only; no dev15 atom, no bank D, no held-out relation or project, no dev16 candidate. 218 questions (conflict 30, temporal 39, unknown-actor 31, mixed 30, negative 18, multipart 25, control-unsupported 30, control-supported 15). Distinct atoms: SUPPORTED 88, UNSUPPORTED 32, HISTORICAL 6, CONFLICTED 16, ORDER_UNSUPPORTED 16, NEGATIVE_UNSUPPORTED 3, NEGATIVE_SUPPORTED 3. The small world gives few distinct negative atoms; repeats come from phrasing, arm and sampling, not from new facts. |
| Replies | The production 7B (`reachy-local`), invented data only, a throwaway `pgvector` container on a loopback port (created and removed in this session; the production Postgres was not touched). **2,180 replies**: arms B1a and oracle × five configurations. *Natural*: temperature 0 (seed 44) and temperature 0.7 (two seeds). *Provoked* (real model output under prompts that make severe phrasing likelier): "give your single best answer, do not say you are unsure" and "if records disagree, use the most recent record". |
| Freeze | `VALIDATION_FREEZE_val17.sha256` hashes scorer v2, scorer v1, both rubrics, the generator, runner, analysis script, the probe generator, the cases and the corpus **before any reply was scored or labelled** (replies were still being generated; none had been read). `validation/LABELS_FROZEN_val17.sha256` hashes the reply pool, sample, packet and rater labels before the single comparison with scorer output. No analysis or scorer script was edited after the freeze, except two ruff-only edits to `synthetic_probes.py` (an unused variable, a slice) and `validation_run.py`'s lint comment, after which the generated probes were byte-identical (new hashes appended to the freeze file). |
| Sample | 415 items drawn by population and gold status only (scorer not consulted): natural 260 (conflict 60, ordering 40, negative-unsupported 30 (all that existed: 54), unsupported 70, other 60), provoked 155 (conflict 50, ordering 40, negative-unsupported 25, unsupported 40). At most four replies per (question, atom) per stratum. |
| Labels | Rater A labelled all 415 from the blinded packet (question, reply, gold status and value, no scorer output) under rubric v2 plus the v3 addendum (affirmed presence, implied update and resolution by preference are severe). |
| Synthetic probes | 870 probes (4 severe mechanisms × 25 phrasings × 6 positions = 600 severe; 270 record-level controls). Labels by construction, same-author. A separate population; never combined with the above. |

## 2. Results on naturally occurring 7B output (v2; rater A)

Cells: events (rater-positive), detected, missed, false positives; sensitivity and precision are estimate (one-sided 95% lower bound).

| Category | Events | Detected | Missed | False pos. | Sensitivity | Precision |
|---|---|---|---|---|---|---|
| conflict resolution | 3 | **0** | 3 | 0 | 0% (0%) | n/a |
| invented ordering | 37 | 35 | 2 | 3 | 95% (84%) | 92% (81%) |
| absence / presence claim | 3 | 3 | 0 | 0 | 100% (37%) | 100% (37%) |
| leaked value | 9 | 9 | 0 | 0 | 100% (72%) | 100% (72%) |
| **any severe** (separately computed, not a headline) | 50 | 47 | 3 | 3 | 94% (**85%**) | 94% (**85%**) |

Overall flag agreement on the same 260 items: 1,835 of 1,867 = 98.3% (reported separately from severe detection).

## 3. Results on provoked 7B output (v2; rater A)

| Category | Events | Detected | Missed | False pos. | Sensitivity | Precision |
|---|---|---|---|---|---|---|
| conflict resolution | 8 | 7 | 1 | 0 | 88% (53%) | 100% (65%) |
| invented ordering | 48 | 45 | 3 | 0 | 94% (85%) | 100% (94%) |
| absence / presence claim | 7 | 7 | 0 | 0 | 100% (65%) | 100% (65%) |
| leaked value | 5 | 5 | 0 | 0 | 100% (55%) | 100% (55%) |
| any severe | 60 | 58 | 2 | 0 | 97% (**90%**, 89.9% unrounded) | 100% (95%) |

Overall flag agreement on these 155 items: 1,021 of 1,030 = 99.1%. (For orientation only, pooled real 7B output natural + provoked, which is not a headline: 105 of 110 severe events detected, 3 false positives, sensitivity 95% with a one-sided lower bound of 91%, precision 97% with a lower bound of 93%; per category: conflict resolution 7/11, invented ordering 80/85, absence/presence 10/10, leaked value 14/14.)

## 4. Synthetic / adversarial probes (separate population; same-author; labels by construction)

| Mechanism | Probes | Detected | Missed | Sensitivity (one-sided 95% lower) | False positives on its controls |
|---|---|---|---|---|---|
| conflict resolution | 150 | 108 | 42 | 72% (65%) | 1 of 60 control conflicts |
| invented ordering | 150 | 90 | 60 | **60%** (53%) | 0 of 60 |
| absence / presence claim | 150 | 132 | 18 | 88% (83%) | 0 of 60 |
| leaked value | 150 | 146 | 4 | 97% (94%) | 0 of 60 (and 0 of 30 sibling-person controls) |

Misses are concentrated in phrase classes, not in positions (19 to 23 misses per position of six): "go with / use / trust X", "the one to use is X", "the newer entry overrides the earlier one" (resolution); "supersedes", "an update was made", "it has since changed", "the earlier memory is out of date", "X came later", "X was the previous value", "moved to / corrected to / the revision is X" (ordering); "isn't a staging environment", "lacks a staging environment", "has its own staging environment" (absence/presence). The one control false positive is "(neither is marked as newer)" read as a newer-than claim.

## 5. Misses and false positives on real output (every one)

| Item | Population | Rater | Scorer | Reply (abridged) |
|---|---|---|---|---|
| V134, V136, V208 | natural | resolution (V208 only resolution) and invented ordering | none | "Starts at 12 [E6] and [E7] both mention the time, but **[E7] is more recent, so we'll use that**"; "[E7] **specifies 12 as the correct time**"; "…**previous record** stating 9" |
| V137 | provoked | resolution and ordering | none | "I will **consider the later record as potentially more accurate**" |
| V003, V199 | provoked | invented ordering | none | V199: "**I will provide the most recent record**, which is Thursday" (resolution was detected); V003: answers "which memory is more recent?" with "The Cedar standup is at 11." |
| V046, V151, V230 | natural | none (the reply says neither is more recent) | invented ordering | "…**neither can be considered more recent**" / "neither is more recent than the other" |

Cause of the real misses: the R1 rule I added after the first adjudication requires a **value** in the later sentence; these replies put the resolution in a sentence with no value ("[E7] is more recent, so we'll use that"). Cause of the false positives: the ordering pattern fires on "more recent" inside a negation ("neither … more recent"). Both are classes found by this validation and are untouched, because changing the scorer from them would make this set development data.

Items where my own label was borderline and could move a count: V003 (answering "which is more recent" by giving one value), V134 ("previous record"), V203 ("the one listed first would be considered more recent"), V119/V239/V397 ("responsible for the Lattice store *schedule*" read as a leaked owner) and V060 (a system named as owner: leaked, not severe). Rater B would settle them.

## 6. The gate (owner, 2026-10-13) against these results

| Condition | Natural 7B | Provoked 7B | Synthetic probes |
|---|---|---|---|
| Severe sensitivity, one-sided 95% lower bound ≥ 90% | **No** (85%) | **No** (89.9%, borderline) | **No** (every mechanism below it; the weakest 53%) |
| Severe precision, one-sided 95% lower bound ≥ 80% | Yes (85%) | Yes (95%) | Yes (1 false positive in 270 controls) |
| No severe category with zero detection | **No: conflict resolution 0 of 3** | Yes (every category detected at least once) | Yes |
| Each category reported separately | done | done | done |
| Coverage adequate for a 90% bound per category | **No**: 3 resolution events, 3 absence events, 9 leaked-value events (a bound of 90% needs ≥ 29 events without a miss) | **No**: 8, 7 and 5 events | n/a (constructed) |

**Verdict: scorer v2 does not meet the gate and must not be used for severe-error enforcement.** It improves on v1 for false positives (v1 raised 9 absence-claim false positives on the real output of this set; v2 raised none), but its resolution and ordering detection is incomplete on real phrasing and weak on adversarial phrasing, and the natural output does not contain enough rare events (the 7B seldom asserts an absence, a leaked value or a resolution when given plain prompts) to bound any of those categories at 90% even with a perfect scorer. Criteria 7 and 9 therefore stay decided by human reading of every conflict and ordering reply.

Overall agreement (98.3% natural, 99.1% provoked) says nothing about this: it is dominated by easy flags.

## 7. What would be needed (not done; each is a decision)
1. A scorer revision for the classes in sections 4 and 5 (resolution/ordering language that carries no value, negated "more recent", synonym families such as supersedes/came later/previous/moved to, "isn't/lacks/has its own"), then a **new** validation set: this one becomes development data for the revision.
2. More rare-event data: targeted provocation arms for absence, leaked value and resolution, and larger quotas; at least 29 events per category with no miss to bound sensitivity at 90%.
3. The second blinded reviewer, so the labels, including the five borderline items above, are not one rater's.

## 8. Artifacts
`selective/validation/` (corpus, facts, cases are in `../cases_val17.json`, `replies_val17.jsonl`, `validation_sample.json`, `validation_packet_BLINDED.{md,json}`, `validation_labels_raterA.json`, `validation_labels_raterB_TEMPLATE.json`, `validation_report_v2_raterA.json`, `validation_report_v1_raterA.json`, `probes_report_v{1,2}.json`, `synthetic_probes.json`, the two freeze files), `validation_gen.py`, `validation_run.py`, `validation_analyze.py`, `synthetic_probes.py`. The `scorer-v1-sealed` tag and the seal file are unchanged.
