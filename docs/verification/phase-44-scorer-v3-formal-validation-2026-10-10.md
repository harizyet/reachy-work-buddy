# Phase 44 scorer v3: formal validation result (one-shot, consumed)

**NO INDEPENDENT HUMAN REVIEW.** Every label in this record was written by one rater, the same assistant that wrote scorer v3 and the rubric addenda. No second reviewer was available. Nothing here is independent human adjudication, and the same-author caveat applies to every figure below.

Scorer v3 is **research-only**. It is not wired into any route, flag or conversation. Protocol: [formal validation protocol](../phase-44-scorer-v3-formal-validation-protocol.md) (frozen at `d44563b` before any reply was generated). State transitions as recorded in `acceptance/STATE.json` (UTC): generated 2026-10-09 15:56, labels frozen 16:06:41, scored 16:06:55. Nothing was tuned, re-scored or re-run. The acceptance set is consumed.

## Verdicts

Gates (unchanged from the protocol): one-sided 95% lower bound on sensitivity at least 90%; on precision at least 80%; no severe category with zero detection. Event target 46 per category; fewer than 29 rater-confirmed events cannot reach a 90% bound even with no miss, so those categories are reported as coverage insufficient and are not scored pass or fail.

| Population | Category | Events (target 46) | Detected | Sensitivity, exact lower bound | Precision, exact lower bound | Verdict |
|---|---|---|---|---|---|---|
| Natural 7B | conflict resolution | 47 | 46 | 97.9%, **90.3%** (pass) | 79.3%, **68.6%** (fail) | **FAIL** (precision) |
| Natural 7B | invented ordering | 48 | 48 | 100%, **94.0%** (pass) | 70.6%, **60.2%** (fail) | **FAIL** (precision) |
| Natural 7B | absence or presence | 67 | 66 | 98.5%, **93.1%** (pass) | 75.9%, **67.1%** (fail) | **FAIL** (precision) |
| Natural 7B | leaked value | 13 | 11 | 84.6%, 59.0% | 78.6%, 53.4% | **NATURALISTIC COVERAGE INSUFFICIENT** |
| Provoked 7B | conflict resolution | 53 | 42 | 79.3%, **68.0%** (fail) | 91.3%, 81.2% (pass) | **FAIL** (sensitivity) |
| Provoked 7B | invented ordering | 79 | 72 | 91.1%, **84.0%** (fail) | 97.3%, 91.7% (pass) | **FAIL** (sensitivity) |
| Provoked 7B | absence or presence | 52 | 50 | 96.2%, **88.4%** (fail) | 94.3%, 86.0% (pass) | **FAIL** (sensitivity, 2 misses) |
| Provoked 7B | leaked value | 17 | 12 | 70.6%, 47.8% | 75.0%, 51.6% | **ADVERSARIAL COVERAGE INSUFFICIENT** |

No category passes both gates. All six scored categories fail: the three natural ones on precision (sensitivity passes), the three provoked ones on sensitivity (precision passes). The two leaked-value populations stopped at 13 and 17 events with every planned opportunity labelled (576 each), so they are coverage insufficient, not failed. Detection was not zero in any category.

Provoked results are adversarial robustness. They are not operational sensitivity and are not pooled with the natural results.

### Denominators and sampling

2,752 of 3,748 generated replies were labelled; each sequence stopped at 46 rater-confirmed events (labels only; the scorer had not run) or when it ran out. One reply per distinct (world, subject, relation) fact per population. Controls (200 per population) were labelled in full. Events per category counted on the sequence; false positives counted on sequence plus controls. No pre-registered expansion triggered: the rule applies only when a sequence ends with 28 to 45 events, and the two leaked-value sequences ended at 13 and 17. `acceptance/plan.json` has the per-sequence counts.

## Cluster-aware bounds

The bootstrap resamples worlds (5th percentile), the design-effect bound uses the intra-cluster correlation, and the conservative bound is the lower of the two. The world-level figure is a stress diagnostic (the share of worlds with events in which every event was detected), not a gate.

| Population, category | Exact lower bound | Conservative cluster-aware bound | World-level stress diagnostic | Worlds with events |
|---|---|---|---|---|
| Natural conflict resolution | 90.3% | 90.3% (ICC 0.00) | 75.0% | 17 |
| Natural invented ordering | 94.0% | 94.0% (ICC 0.00) | 82.9% | 16 |
| Natural absence or presence | 93.1% | 93.1% (ICC 0.00) | 76.2% | 18 |
| Natural leaked value | 59.0% | 59.0% | 60.6% | 10 |
| Provoked conflict resolution | 68.0% | 68.0% | 22.7% | 16 |
| Provoked invented ordering | 84.0% | **82.5%** (ICC 0.03) | 39.2% | 18 |
| Provoked absence or presence | 88.4% | 88.4% | 69.0% | 18 |
| Provoked leaked value | 47.8% | 47.8% | 35.5% | 13 |

Cluster adjustment did not change any verdict. It weakens the provoked ordering bound (84.0% to 82.5%), which already failed. The natural conflict-resolution sensitivity margin is thin (90.3% against a 90% gate, one miss in 47); no category triggers "gate not robust to clustering", because none passed on the exact bound and fell on the cluster-aware one. The world-level diagnostic is much lower than the pooled bounds in every row, so the pooled sensitivity figures should not be read as a guarantee for each world.

## What the failures are

Descriptive counts from the failure lists, written after scoring and not used for any change:

- **Natural ordering and conflict precision.** 16 of the 20 natural ordering false positives are replies that say the two memories conflict and that "neither overrides the other". Rubric v4 says negated precedence is not a claim, so these are scorer errors, not label disagreements. The 12 natural conflict false positives are mostly replies that list both values or flag the conflict and also state a single answer or say "please clarify".
- **Natural absence precision.** Ten of the 21 natural absence false positives are replies that say "no escalation channel found in the Osprey chat space" or "the internal portal was not checked". The rater labelled these as record-level statements about what was searched. The scorer treats them as world claims. This is the area where the rater convention and the scorer disagree most, and the rater marked 12 of the 32 borderline labels here. Whether those replies are violations is a rubric question, not one the numbers settle.
- **Provoked conflict and ordering misses.** The misses are mostly replies of the form "the most recent record states X" or "there is conflicting information. The most recent record states that Cedar has no status page", where resolution is expressed by recency wording rather than the patterns v3 detects (status-page, runbook, rotation and channel families especially, which the development probes did not cover).
- **Leaked value.** The misses are "X is on call for Y this month" answered to "who is running Y", which the rater counted as an assignment of the wrong role to a person, and hedged inferences ("this suggests"). The 576 planned opportunities produced only 13 and 17 events: the 7B almost always refuses these questions. A naturalistic gate for leaked values is not reachable with this design.

Full lists (every miss and every false positive with its reply) are in `acceptance/report.json`; scorer outputs for every labelled item are in `acceptance/scorer_outputs.json`.

## Synthetic probe bank E (separate population, labels by construction, same author)

Run once. Not operational evidence.

| Category | Sensitivity (lower) | Precision (lower) | Gate diagnostic |
|---|---|---|---|
| Conflict resolution | 83.3% (78.6%) | 94.7% (91.2%) | sensitivity below 90% |
| Invented ordering | 100% (98.2%) | 100% (98.2%) | both pass |
| Absence or presence | 100% (97.9%) | 76.2% (70.5%) | precision below 80% |
| Leaked value | 100% (98.4%) | 99.5% (97.4%) | both pass |

Matched-pair accuracy: 611 of 702 pairs scored both members correctly (87.0%). The synthetic results agree in direction with the natural and provoked results (absence precision low, conflict-resolution sensitivity low), and they are not a substitute for either.

## Limits

- Single rater, same author as the scorer. 32 of 2,752 labels were marked borderline. No label was changed after freezing.
- The rater reads the replies as an assistant that already knows how the scorer works, which is the weakness of this design and the reason no pass would have established independence.
- Natural 7B results come from three sampling configurations of one model and one prompt; provoked results use two added prompt instructions. Generated against synthetic worlds (seeds 31 to 48); the corpus is invented.
- `acceptance/STATE.json` records `"replies": 3348` for the generation step. The file has 3,748 lines and its hash matches the one recorded; the count is a recording error in the state writer, with no effect on any result.
- A key-collision defect in the plan (conflict and control sequences shared key prefixes) was found after generation and before any label; the fix and new hashes are appended to `ACCEPTANCE_FREEZE_v3.sha256`. No reply, plan, scorer or threshold changed.
- The fresh bank E and probe bank E had not been run against v3 before this run.

## Preserved artifacts (`services/companion-core/benchmarks/answer_quality/selective/acceptance/`)

The hashes are in `ARTIFACTS.sha256` there. The frozen set is `plan.json`, `replies.jsonl`, `packet_block01.md` to `packet_block10.md`, `packet_map.json`, `labels_raterA.json`, `report.json`, `scorer_outputs.json` and `STATE.json` (stage `scored`, forward-only). The run cannot be repeated: the state machine refuses it.

## What this does not establish, and open decisions

Scorer v3 did not pass its gates in any of the six scored categories. It must not be used as a gate on answers, and no B-1 integration, deployment, indexing, retrieval or shadow step depends on it. Per the owner's decision, v3 is not to be tuned on these failures and re-run on this set.

Decisions for the owner:

1. Whether to stop scorer v3 here, or to author a v4 on fresh worlds with a new frozen validation. dev16 stays unfrozen and unrun.
2. Whether the record-level versus world-level absence convention should be settled in the rubric before any further validation (it drives ten of the natural absence false positives).
3. Whether a naturalistic leaked-value gate is worth pursuing. With this design the 7B produces too few events; a gate would need a different opportunity design, which is a protocol change.
4. A second reviewer, if any further validation is run.
