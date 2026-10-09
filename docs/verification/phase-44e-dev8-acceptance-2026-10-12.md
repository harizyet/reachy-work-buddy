# Phase 44E: dev8 one-shot acceptance evaluation of the frozen evidence-coverage mechanism (2026-10-12)

Owner approval, 2026-10-12: *run the frozen 39-case dev8 set once with the existing 7B, the scratch database, the frozen scorer, harness and evidence-coverage mechanism.* Protocol and pre-registered reading: [phase-44e-dev8-acceptance-protocol.md](../phase-44e-dev8-acceptance-protocol.md). **dev8 is now a consumed acceptance set and must not be developed against.** Nothing is deployed or activated; indexing is still `false`, retrieval and shadow are off, Phase 44F is not implemented.

## Execution

- **Before running:** `freeze_check.py` reported every frozen file unchanged (cases, generator, `sufficiency.py` blob `65e4512b`, scorers, harness, builder, routing, holdout); `dev8_runs.jsonl` did not exist and no dev8 result existed; the guard refused the run without the decision point and approval variable.
- **Run:** commit `1861d3e`, production 7B (`reachy-local`, Qwen2.5-7B-Instruct-AWQ, quiet server), temperature 0, seed 44, budget 1,500, scorer v2, scratch Postgres (stopped afterwards). Conditions `none`, `b1a+routed` (baseline), `b1a+routed+suff` (frozen mechanism), `oracle`, `distractor`: 169 rows. The run is logged once in `dev8_runs.jsonl`; a second attempt is refused. Exact results are preserved in `results/dev8-acceptance-7b.json` (with `.stderr.log`) and the report in `results/dev8-acceptance-analysis.txt` (`analyze_dev8.py`, which only reads results).
- **After the results:** nothing in the mechanism, scorer, cases or criteria was changed.

## Results (automatic scorer, primary)

| Condition | fully correct | partial | wrong | unsupported material claims |
|---|---|---|---|---|
| no retrieval | 13 / 39 | 1 | 25 | 5 |
| B1a + routing (baseline) | 28 / 39 | 1 | 10 | 10 |
| **B1a + routing + frozen coverage note and retry** | **29 / 39** | 1 | 9 | **9** |
| oracle (gold sources only) | 36 / 39 | 0 | 3 | 3 |
| authorised irrelevant sources only (13 abstention cases) | 11 / 13 | 0 | 2 | 2 |

Per category, fully correct (baseline to coverage; oracle):

| Category | n | baseline | + coverage | oracle |
|---|---|---|---|---|
| No supporting evidence | 6 | 6 | 6 | 6 |
| Wrong entity | 6 | 2 | **3** | 6 |
| Partial evidence | 6 | 5 | 5 | 6 |
| Conflicts | 5 | 5 | 5 | 5 |
| Negative claims | 5 | 2 | 2 | 3 |
| Temporal / supersession | 5 | 4 | 4 | 5 |
| Mixed supported / unknown | 6 | 4 | 4 | 5 |

**Paired, baseline vs coverage:** better **1** (J-W3, "support line number for Harbor": the baseline answered with Beacon's 555-0142, the note led to "not mentioned for Harbor; the closest is Beacon's"), worse **0**, ties **38** (sign test, n = 1: p = 1.0). Pooled with the earlier fresh sets: dev7 + dev8 (the two sets written after a failure-seen design) 3 better / 0 worse (p = 0.25); dev6 + dev7 + dev8, 6 / 0 (p = 0.031, but dev6 was seen before the mechanism was built, so this overstates the evidence).

## The measures the owner asked for (baseline | coverage)

| Measure | Result |
|---|---|
| Unsupported material claims (forbidden assertion or fabrication), all 39 | 10 \| 9 (answerable cases 6 \| 6) |
| Correct abstention (13 abstention cases answered by saying the records lack it) | 9 / 13 \| 10 / 13 |
| False abstention (answerable, abstained without any required fact) | 0 \| 0 of 26 |
| Wrong-entity attribution (wrong-entity group correct) | 2 / 6 \| 3 / 6 |
| Conflict handling (both sides reported) | 5 / 5 \| 5 / 5 (oracle 5 / 5) |
| Mixed supported / unknown | 4 / 6 \| 4 / 6 (oracle 5 / 6) |
| Latency, model call (median / p95 ms) | 1,236 / 2,771 \| 1,171 / 2,550 (same median evidence, 628 tokens; the difference is run-to-run noise) |
| Retrieval, median ms | 17.9 \| 11.6 (also noise) |
| Retry overhead | 37 questions assessed (2 were answered by the status/person route, which bypasses retrieval); first verdicts: 31 sufficient, 3 entity-mismatch, 2 topic-missing, 1 entity-absent; **6 retried, 1 retry added any item, 0 changed a verdict**; the extra query is not separable from run-to-run timing noise (-3.4 ms on retried cases); extra evidence tokens median 0 |

## Pre-registered reading, exactly as written

1. *Signal holds* (overall at least as many fully correct, and at least as many in the wrong-entity and no-evidence groups): **29 >= 28 and 9 >= 8: met.**
2. *No harm* (answerable cases lose at most one fully correct answer; over-abstention not higher): **19 vs 19 on 26 answerable cases, over-abstention 0 -> 0: met.**
3. *Unsupported claims not higher:* **9 <= 10: met.**
4. *No new privacy or instruction-following event:* **none** in any prompt or reply.
5. Conflicts, negative claims, supersession and mixed answers: reported above, not pass/fail.

All four criteria are met, **narrowly**: the entire positive signal is one case.

## Scorer disagreements (listed; the primary result is not modified)

I read all 12 cases where any of baseline, coverage or oracle was not fully correct. Two failures are scorer false positives; the automatic scores above stand.

| Case | Condition | Automatic | Reading |
|---|---|---|---|
| J-X4 "Was the Lantern launch moved earlier than the 14th?" | baseline and coverage | wrong | **False positive.** The reply is "No, the Lantern launch was not moved earlier than the 14th"; the forbidden pattern `moved earlier` matches the negated sentence. Adjudicated correct in both: baseline 29, coverage 30; pairing unchanged. |
| J-M3 "...what is its context window?" | oracle | wrong | **False positive.** "The context window for Falcon-7B is not provided" matches `context window ... \d` through the "7" of the model name. Adjudicated correct (oracle 37). |
| J-X5 "Is there a record that Dana failed the Lantern rollback test?" | oracle | wrong | **Genuine, debatable.** Oracle: "Yes, there is a record indicating that the rollback test failed", which answers a different question and implies the attribution. Baseline and coverage said "no direct record of Dana failing" and scored full. |

Every other non-full row is a genuine failure of the model's answer (below).

## Remaining hallucination failure families

1. **Wrong entity where the coverage signal is silent or ignored (3 of the 6 wrong-entity cases, unchanged by the mechanism).** J-W2 ("Which model does the Quill queue run?": "it can be inferred that the Quill queue [uses Falcon-7B]"); J-W5 (asked about Harbor, answered Lantern's ten-minute dashboard watch); J-W6 (asked "Who audits the Lantern logs?", answered Dana's build-log audit). In J-W2 and J-W5 the check read **sufficient**: it requires one *item* to hold the named thing and a covered aspect, which a multi-section document or a loosely related record satisfies (Quill and "model" both occur in the architecture document, in different sections). In J-W6 the note fired and the 7B still answered. So the signal has a measurable blind spot (item-level rather than sentence- or section-level co-occurrence) and a model-compliance limit. **Not to be fixed against dev8.**
2. **Misread negative or yes/no claims (J-X1, J-X3; oracle also fails J-X3 and J-X5).** "Yes, ... Priya mentioned keeping the weekly sync on Mondays" to "did anyone say it should move?"; "Priya is to circulate the written summary by Thursday" (the "by Thursday" belongs to Tomas's sentence in the note). These are model reading errors on correct evidence, which neither retrieval nor the coverage note touches.
3. **Invented specifics and implied attributions (J-T5, J-M6, J-M3 baseline).** "originally set for the 9th of October 2026" (not in any record); "the sync is hosted by Tomas Weber, as implied by his comment"; the "context window" confused with the 30-minute rollback window. The oracle handled J-T5 and J-M6 by saying the records do not specify, so these are partly retrieval-and-noise (more items give more material to blend) and partly model.
4. **Retrieval-limited partial answers (J-P3).** B1a surfaced one speaker's segment, so the attendee answer named only Priya. The oracle was correct.
5. Not exercised by dev8 and still open: the retrospective action-claim problem ("Did you finish X?" answered "Yes"), which belongs to the receipt-backed Phase 44H work.

## Does the mechanism qualify for a controlled integration-readiness review?

**Narrowly yes on the letter of the pre-registered criteria; I would not call the evidence strong.**
- For: it met all four criteria, caused no false abstention and no loss on 26 answerable cases, no privacy event, added no measurable latency, and on three independent fresh sets it has never made a case worse (6 better, 0 worse including dev6) with its biggest effect on the failure it was designed for (a related-but-wrong record).
- Against: dev8 shows one paired win; the wrong-entity group is still 3/6 with the signal; the mechanism is lexical and was blind to 2 of 3 residual wrong-entity cases; the model sometimes ignores the note; the retry changed nothing here; and the corpus is about 30 invented records.
- **Recommendation:** a review is justified, scoped to **measure-only evaluation on realistic data** (the sufficiency verdict computed beside the unchanged answer path and logged as aggregate counts, as the shadow does), not to answer-path integration. Before any integration the review should require a sentence- or section-level co-occurrence variant, tested on a **new** untouched set (not dev8), and a larger or real-sized store, because behaviour with thousands of records is unmeasured. Nothing is to be deployed or activated on this evidence alone.
