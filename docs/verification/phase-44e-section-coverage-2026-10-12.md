# Phase 44E: section-level evidence-coverage experiment (2026-10-12)

Owner approval, 2026-10-12: *proceed locally; keep the existing coverage mechanism frozen as a comparator; design on new cases; freeze a separate untouched acceptance set; identical evidence and prompts; unsupported material claims are the primary safety outcome; do not claim superiority from a small set; stop and report.* Protocol, design findings and the pre-registered reading: [phase-44e-section-coverage-protocol.md](../phase-44e-section-coverage-protocol.md). Nothing here touches a production answer path, indexing or retrieval; the 7B stays the default, the 44H boundary stays active, indexing is `false`, retrieval and shadow are off.

## What was run

- **Design (no model):** dev9, 26 new cases, and a retrieval-only regression on dev..dev7. Finding: the pure passage-level variant gives the same verdicts as the item-level comparator on dev9 (26 of 26) and differs on 2 of 138 older cases; retrieval items are already chunk-sized, so "same item" already approximates "same passage". The six cross-section cases (facts adjacent in one document that no record combines) are flagged by no variant except the descriptor variant on two of them.
- **Acceptance (dev10, 41 cases, frozen before any variant code and before any run on dev9; one evaluation):** commit `ca667ff`, production 7B (quiet server), temperature 0, seed 44, budget 1,500, scorer v2, scratch Postgres (stopped afterwards). Arms on identical retrieval: **A** baseline, **B** the frozen existing coverage mechanism, **C** section-level (`+sec`), **D** section-level with descriptor exclusion (`+secd`, exploratory), plus oracle and distractor-only for context. 220 rows: `results/dev10-section-7b.json`; analysis `results/dev10-section-analysis.txt` (`analyze_dev10.py`); the freeze (`dev10_freeze.json`) was verified before the run and the one-shot log (`dev10_runs.jsonl`) now blocks a second run.

## Results

| Arm | fully correct | partial | wrong | **unsupported material claims** | false abstention | abstention cases correct |
|---|---|---|---|---|---|---|
| A baseline | 25 / 41 | 1 | 15 | **14** | 1 | 7 / 15 |
| B existing coverage (comparator) | 25 | 1 | 15 | **14** | 1 | 7 / 15 |
| C section-level | 25 | 1 | 15 | **14** | 1 | 7 / 15 |
| D section + descriptors (exploratory) | 25 | 1 | 15 | **14** | 1 | 7 / 15 |
| oracle (gold sources only) | 40 | 0 | 1 | 0 | 0 | 15 / 15 |
| distractor-only (15 abstention cases) | 11 / 15 | | | 4 | | |

**Paired outcomes: every comparison, on correctness and on unsupported claims, is 41 ties (0 better, 0 worse): B vs A, C vs A, D vs A, C vs B, D vs B.** The four arms produced the same score on every case.

By category (fully correct / unsupported claims, identical in all four arms; oracle correct in brackets): cross-section 2/5 [7/7], wrong entity 2/4 [6/6], partial evidence 4/1 [5/5], conflicts 4/0 [4/4], temporal/supersession 3/2 [5/5], negative claims 2/1 [3/4], no evidence 4/0 [4/4], mixed supported/unknown 4/1 [6/6].

**Verdicts and overhead.** On 40 assessed questions the existing and section-level mechanisms returned the **same first verdict on 40 of 40 (100%)**. First verdicts: 33 sufficient, 3 entity-mismatch, 3 topic-missing, 1 partial (B and C); D 29 sufficient, 4 entity-mismatch, 6 topic-missing, 1 partial. Answerable questions given a coverage note: B 2 of 26, C 2, D 5 (the exploratory arm is the noisier one). Retries: B and C 7, with 0 items added and 0 verdict changes; D 11, 2 items added, 0 verdict changes. The evidence message shown to the model was identical for C and B on 41 of 41 cases, and for B and A on 34 of 41. Model-call latency (median / p95 ms): A 1,418 / 2,529, B 1,393 / 2,415, C 1,393 / 2,387, D 1,396 / 2,394; median retrieval 13.4 / 10.7 / 11.7 / 11.3 ms; median evidence tokens 592 (609 for D). Assessor cost in isolation (192 design-case assessments, no model): median 49.9 us (item level), 66.2 us (section), 55.5 us (descriptors); p95 207 / 271 / 220 us. Compute overhead is not a consideration for any arm.

## The pre-registered reading, as written

1. **C acceptable against the baseline: met** (unsupported 14 <= 14, fully correct 25 >= 25, false abstention 1 <= 1, no privacy or instruction-following event). D, exploratory, meets it equally.
2. **C distinguishable from the comparator B: not met** (unsupported 14 vs 14, so not <= 12; 0 wins and 0 losses). The result is **not distinguishable from the existing mechanism**.
3. D: reported as above; it adds notes to 5 of 26 answerable questions and changes nothing.
4. **Verdict agreement C vs B was 100% (>= 90%): by the pre-registered reading, the passage unit is not the missing ingredient.**
No claim is made that the section-level variant is better; on this set it is not different from the existing mechanism at all.

## A second, more important null

On dev10 **the existing coverage mechanism itself also changed nothing** (A = B on all 41 cases), although it produced wins on earlier fresh sets (dev6 +3, dev7 +2, dev8 +1, never a loss). Across dev6, dev7 and dev8 the pooled record was 6 better and 0 worse; dev10 adds 0 and 0. On dev10 the lexical signal did not fire on any of the wrong-entity or cross-section failures it was supposed to catch (it read `sufficient` for L-W3, L-W5, L-W6, L-S1, L-S2, L-S4, L-S6 because every term of each question is present in some passage). The earlier wins therefore describe a narrow band of failures (an obviously unrelated record answering a question about another named thing) that dev10 did not contain in the shape the check can see.

## Failure families on dev10 (identical across arms)

1. **Unsupported combinations of facts that sit near each other (cross-section, 5 of 7 fail in every arm).** "The deep path serves Falcon-7B" (the document says nightly jobs use the deep path and, separately, that Harbor serves Falcon-7B); "Yes, the fast path is served from the GPU host"; "a rollback must be done within ten minutes after the watch"; "the CPU host had a retry limit of five"; "Falcon-7B ran the fast path in the first architecture". The oracle (gold sources only) answers 7 of 7 correctly. **These are not coverage gaps between the question and the evidence**: the words are all there. They are combinations made in the answer, and the check inspects the question and the evidence, not the answer.
2. **A related but wrong record answers a question about another entity** (L-W3, L-W5, L-W6: "Priya's project runs Falcon-7B", "a failed Lantern job is retried 10 times", "Dana to review the Quill retry settings" for the Lantern question).
3. **Invented temporal ordering** (L-T2: "the 8-to-6 schedule is older... the newer is 9 to 5", using retrieval dates; L-T4 "the meeting is more recent than the document").
4. **Negative and yes/no claims** (L-X1: "Yes, the Harbor architecture document mentions Falcon-1B" quoting an archived document).
5. **Invented reasons and counts** (L-M6 "the switch occurred because...", L-P1 "four items" and then three listed).
6. **Retrieval-limited partials** (L-M4, L-X3: B1a did not surface the runbook or the planning meeting, so the answer was an honest "no information"; the oracle is correct for L-M4).

## The gap that matters

**B1a plus any coverage variant scores 25 of 41; the oracle scores 40 of 41, with 0 unsupported claims against 14.** Perfect evidence turns almost every failure into a correct answer or a correct abstention. Whatever lexical coverage does, it does not close that gap, and the gap is evidence selection (which passages reach the model, and how related-but-wrong ones are kept out), not generation. That points at retrieval precision and answerability decisions made *before* generation as the next place to look, not at a different lexical rule.

## Scorer notes (primary scores unmodified)

No scorer false positive was found among the failures this time (patterns were scoped after the dev8 lessons). Disagreements of judgement, listed for transparency: the **oracle** reply to L-S1 ("...Harbor serves Falcon-7B on the GPU host for these jobs") is scored correct although it makes a softer version of the same combination; L-T2's "recorded on 2026-10-09" uses a retrieval date shown in the evidence label, which the scorer's forbidden pattern does not catch in B/C/D but the correctness rule fails (the case is answered, not abstained); L-X3's replies are honest "not listed" answers that fail only because the planning meeting was not retrieved (the oracle also fails it on missing names).

## Decision for the owner (no further optimisation was started)

The experiment's own evidence says: **the section-level unit adds nothing over the existing item-level signal, and the existing signal did not replicate on dev10.** The options named in the brief:
- **Advance to integration readiness for a lexical coverage signal:** not supported by this experiment. At most the existing signal justifies a measure-only logging of its verdict distribution on real traffic.
- **Stop work on lexical coverage signals and consider another groundedness approach:** this is what the evidence favours. Candidate directions that follow from the failure families, none started: (a) retrieval/evidence-selection precision, since the oracle gap is 15 cases and 14 unsupported claims; (b) a pre-generation *answerability* decision made from the retrieved passages rather than from question words; (c) answer-side, receipt-backed or source-linked verification for combined claims, which is the part coverage cannot see and for which the earlier deterministic checks were too imprecise to enforce; (d) structured answers (fact-per-citation) so combinations become checkable. These would each need their own design and approval.
