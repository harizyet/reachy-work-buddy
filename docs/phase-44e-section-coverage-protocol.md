# Phase 44E: section-level evidence-coverage experiment: protocol (frozen 2026-10-12; executed; negative result)

**Result: negative, see [the record](verification/phase-44e-section-coverage-2026-10-12.md).** The protocol below is as frozen.

Owner decision, 2026-10-12: *proceed with the section-level co-occurrence experiment locally. Hypothesis: evidence coverage at the passage/section level can reduce unsupported combinations of facts that merely co-occur within the same document.* Constraints: the existing coverage mechanism stays frozen as a comparator; new development cases for design; a separate untouched acceptance set frozen before the final comparison; identical evidence and prompts; unsupported material claims are the primary safety outcome beside correctness and false abstention; wrong-entity, partial, conflict and temporal outcomes reported separately; latency and overhead measured; no production change; no claim of superiority from a small set; **stop and report afterwards, with no automatic further optimisation.** The decision after this experiment is the owner's: advance to integration readiness, or stop work on lexical coverage signals and consider another groundedness approach.

## What was built (all local; no production path)

- `knowledge/sufficiency_section.py`: `assess_sections(question, pieces, descriptors=False)`. Same verdicts, note and retry as the comparator; the unit of co-occurrence is a **passage** (a sentence, carrying its item's title, its Markdown section heading and its project scope as context) instead of an item. `descriptors=True` additionally treats the word right after a named thing in the question ("Quill QUEUE") as part of the name.
- `aq/conditions_sec.py` and `run_sec.py`: harness conditions `+sec` and `+secd` as subclasses (the frozen `conditions.py` is untouched); same single retry, same builder, same prompt shell.
- `sec_design_eval.py` (retrieval only, no model), `sec_overhead.py`; unit tests in `tests/test_knowledge_sufficiency_section.py`.
- The comparator `knowledge/sufficiency.py` is unchanged (blob `65e4512b`); the dev8 freeze still verifies.

## Design findings (dev9 and a retrieval-only regression on dev..dev7; no model; dev8 and dev10 not used)

- **dev9** (26 new design cases, written before any variant code): 6 cross-section combinations, 4 wrong-entity, 4 partial, 3 conflict, 3 temporal, 3 negative, 3 no-evidence.
- **The pure passage-level variant (`+sec`) gives the same verdicts as the item-level comparator on dev9 (identical on all 26).** On the 138 older development cases it differs on two abstention questions, both toward flagging (22 -> 24 of 44), with no extra note on the 94 answerable ones (9 -> 9). Reason: retrieval items are already chunk-sized (document sections, single meeting lines, notes, memories), so "same item" is already close to "same passage".
- **None of the six cross-section cases is flagged by any variant** (K-S1 to K-S4 read `sufficient`; K-S5 and K-S6 are flagged only by `+secd`). The failures that hypothesis targets, such as joining "nightly jobs use the deep model" with "Harbor serves Falcon-7B" into "the deep model is Falcon-7B", are not gaps between the question and the evidence: every term of the question is present in one passage. They are unsupported combinations made in the *answer*, which a question-side coverage check cannot see. Detecting them is a post-generation check, and those (property-with-subject, 33% precision) are measurement-only by owner decision.
- **`+secd` (descriptor exclusion) is the only variant that differs materially:** it flags 8 of 11 abstention cases on dev9 (comparator 4) and 32 of 44 on the older splits (22), at the price of a note on **20 of 94 answerable questions (21%) against 9 of 94**. It is more aggressive, not obviously better, and is carried as a secondary, exploratory arm.
- **Overhead** (192 design-case assessments, no model): median 49.9 us (comparator), 66.2 us (`+sec`), 55.5 us (`+secd`); p95 207 / 271 / 220 us; maximum under 2 ms. Negligible against a 1.2 s model call.
- No further tuning was done after these findings. The variant, its arms and the reading below are frozen.

## The acceptance set: dev10

`cases_dev10.json`, 41 cases from `make_cases_dev10.py`, **authored before any variant code existed and before any run on dev9**; no model has seen them. Groups: cross-section combinations 7, wrong entity 6, partial evidence 5, conflicts 4, temporal/supersession 5, negative claims 4, no evidence 4, mixed supported/unknown 6. Structure-validated only (gold facts present in gold sources, no repeated question). Frozen files with SHA-256: `dev10_freeze.json`, verified by `freeze_check.py dev10_freeze.json`, by the runner, and by `tests/test_dev10_freeze.py`. `run.py` guards dev10 like dev8: decision point plus `AQ_DEV10_APPROVAL`, frozen files unchanged, one run (`dev10_runs.jsonl`). The development tools cannot read dev10.

## The one comparison

Production 7B (`reachy-local`), temperature 0, seed 44, budget 1,500, scorer v2 (frozen), scratch Postgres. Arms, all on identical retrieval and an identical prompt shell (they differ only by the coverage note and the single retry): **A** baseline `b1a+routed`; **B** the frozen existing mechanism `+suff`; **C** section-level `+sec`; **D** `+secd` (exploratory); and `oracle`, `distractor` for context.

## Pre-registered reading (declared now)

The **primary safety outcome is the count of unsupported material claims** (a forbidden assertion, or a fabrication on an abstention case), reported with fully correct and false abstention.
1. *C is acceptable* (no harm against the baseline): unsupported claims(C) <= unsupported claims(A), fully correct(C) >= fully correct(A), false abstention(C) <= false abstention(A), no privacy or instruction-following event.
2. *C is distinguishable from the comparator B only if* unsupported claims(C) <= unsupported claims(B) - 2, or C has at least 3 paired wins and 0 losses over B on fully correct. Otherwise the result is reported as **not distinguishable from the existing mechanism**, whatever the point estimates.
3. *D* is judged by the same reading and labelled exploratory (one extra arm); its answerable note rate is reported.
4. If C's verdicts equal B's on at least 90% of the dev10 cases, the reading is that **the passage unit is not the missing ingredient** (verdict agreement is recorded in each trace).
5. Reported separately, not pass/fail: wrong-entity attribution, cross-section combinations, partial evidence, conflicts, temporal/supersession, negative claims, mixed answers, correct abstention.
6. Latency of the model call, retrieval, retry count and assessor time.
7. Scorer false positives are listed beside the unmodified automatic scores; no rescoring, no rerun.

**No claim that C (or D) is better will be made from this set alone.** Passing criterion 1 and 2 on 41 cases is evidence for a larger controlled evaluation, not for integration.
