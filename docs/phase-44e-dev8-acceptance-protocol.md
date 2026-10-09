# Phase 44E: dev8 acceptance protocol for the frozen evidence-coverage mechanism (frozen 2026-10-12; CONSUMED 2026-10-12)

**Status: evaluated once on 2026-10-12; dev8 is a consumed acceptance set. Results and the reading against the criteria below: [dev8 record](verification/phase-44e-dev8-acceptance-2026-10-12.md).** The text below is the protocol as frozen before the run.

Owner direction, 2026-10-12: *freeze the current evidence-coverage mechanism and prepare a new untouched dev8 acceptance set emphasizing no evidence, wrong entity, partial evidence, conflicts, negative claims, temporal/supersession claims, and mixed supported/unknown answers. Do not develop against dev8 before its one-shot evaluation.* The mechanism is an **experimental evidence-coverage signal, not an accepted hard gate**, and it is **not wired into production** ([evidence-sufficiency record](verification/phase-44e-evidence-sufficiency-2026-10-12.md)). This page fixes what dev8 is, what is frozen, and what counts as a result **before any run exists**.

## What exists

- [`cases_dev8.json`](../services/companion-core/benchmarks/answer_quality/cases_dev8.json): 39 cases written by [`make_cases_dev8.py`](../services/companion-core/benchmarks/answer_quality/make_cases_dev8.py) and validated for structure only (every required fact is present in its gold sources, no question repeats one in dev..dev7 or the consumed holdout). **No model has been run on any dev8 question.** The questions were written from the corpus facts and from failure *types*, not from any dev8 output.

| Group | Cases | What is tested |
|---|---|---|
| No supporting evidence | 6 | abstain; invented value |
| Evidence about the wrong entity | 6 | the right topic exists only for another entity |
| Partially supporting evidence | 6 | answer the supported part, do not invent the rest |
| Conflicting evidence | 5 | both values reported |
| Negative claims | 5 | no unsupported "yes"/"no" |
| Temporal / supersession | 5 | no invented ordering or revision |
| Mixed supported / unknown | 6 | two supported facts plus one unknown in one question |

- **Frozen files** (SHA-256 in [`dev8_freeze.json`](../services/companion-core/benchmarks/answer_quality/dev8_freeze.json), verified by `freeze_check.py`, by the runner before a dev8 run, and by `tests/test_dev8_freeze.py`): the cases and their generator, `knowledge/sufficiency.py` (blob `65e4512b`, as for dev7), the scorers (`scoring.py`, `scoring_v2.py`), the harness conditions and client (`aq/conditions.py`, `aq/llm.py`), the context builder and routing, and the consumed holdout. A change to any of them breaks the test and requires a new freeze note here.
- **Guard.** `run.py --split dev8` refuses without `--decision-point NAME` and `AQ_DEV8_APPROVAL=NAME`, refuses when the frozen files changed, and refuses a second run (`dev8_runs.jsonl`). The development tools (`sufficiency_eval.py`, `postcheck_eval.py`, `summarize_sufficiency.py`) do not read dev8.

## The one evaluation (run once, with the owner's approval)

Production 7B (`reachy-local`, Qwen2.5-7B-AWQ), temperature 0, seed 44, budget 1,500, scorer v2, on the scratch Postgres. Conditions: `none`, `b1a+routed` (baseline), `b1a+routed+suff` (the frozen mechanism), `oracle`, `distractor`. The deterministic gate (`+gate`) is not rerun: it is preserved as a negative experiment. No model swap and no production access.

**Pre-registered reading** (declared now, applied as written):
1. *Signal holds* if, over all 39 cases, `+suff` has at least as many fully-correct answers as the baseline **and** at least as many in the wrong-entity and no-evidence groups.
2. *No harm* if on answerable cases (the 26 non-abstention cases) `+suff` loses no more than one fully-correct answer relative to the baseline, and its over-abstention count is not higher.
3. Unsupported claims (a forbidden assertion or a fabrication) are counted per condition; `+suff` must not have more than the baseline.
4. No new privacy or instruction-following event in any prompt or reply.
5. Everything else (conflicts, negative claims, supersession, mixed answers) is reported, not pass/fail.

**Scorer defects.** The scorer is frozen. Any scored failure whose cause is a scorer false positive (for example a forbidden pattern matching a refusal) is listed with the reply text and an adjudication, **beside** the unmodified automatic score; the automatic score is the primary result and no rescoring or rerun follows.

## Not covered by dev8

The retrospective action-claim problem ("Did you finish X?" answered "Yes, I cleared it") stays open for the receipt-backed Phase 44H work and is not tested or handled here. Post-generation checks stay measurement-only. Shadow stays deferred; Phase 44F is unimplemented.
