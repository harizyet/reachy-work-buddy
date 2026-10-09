# Phase 44E: evidence sufficiency and groundedness (development, 2026-10-12)

Owner decision, 2026-10-12: groundedness is the immediate Phase 44 quality priority. *"Prepare/evaluate the evidence-sufficiency mechanism on fresh development data... Prefer abstention or bounded retrieval retry over unsupported assertions. Do not tune against the consumed holdout."* This is development evidence on invented data with the production 7B (`reachy-local`, Qwen2.5-7B-AWQ) at temperature 0, seed 44. Nothing is deployed; production indexing, retrieval and shadow stay off. The consumed first-look holdout was not read or scored.

## What was built

| Part | Where | What it does |
|---|---|---|
| Evidence-sufficiency assessor | [`knowledge/sufficiency.py`](../../services/companion-core/src/companion_core/knowledge/sufficiency.py), 13 unit tests | Before a model sees retrieved evidence, a deterministic lexical check of whether it speaks to the question: `none`, `entity_absent` (a name in the question appears in no item, or only a family member does: "Falcon-3B" vs "Falcon-7B"), `entity_mismatch` (the asked-about aspect is held only by items that never mention the asked-about thing), `topic_missing` (the thing is named but none of the question's other words appear), `partial` (an identifier-like word such as "p95" appears nowhere), `sufficient`. No model, no learning. |
| Coverage note | harness conditions `+suff` | A one-line, code-written note inside the evidence message ("Automatic check: no record below mentions Falcon-3B (the records name Falcon-7B, which are different)"). It states a fact about the shown evidence; it gives no instruction. |
| Bounded retry | `+suff` | When the verdict is not `sufficient`, one second retrieval with a focused query (the named things plus the words no item held); up to 3 new items are merged; the verdict is recomputed. |
| Deterministic abstention | `+gate` (opt-in) | A fixed reply when the evidence is `none`, every named thing is absent, or the aspect is held only for another entity. |
| Post-generation checks | `aq/postcheck.py`, measured only | Unsupported specifics, unsupported denials, invented recency, property-with-subject, plus the earlier `aq/checks.py`. |

Paraphrase is deliberately not a gap. A first version flagged any unmatched question word and wrongly flagged 56 of 83 answerable development questions ("date", "long", "keep" rarely appear verbatim in the evidence that answers); ordinary words now never produce a verdict, and numbers the question merely offers ("Is it 45 minutes?") are not subjects. Final assessor on the evidence a perfect retriever would give ([`sufficiency_eval.py`](../../services/companion-core/benchmarks/answer_quality/sufficiency_eval.py), no model): of 83 answerable development questions 67 read `sufficient` (16 get a note, 15 of them `topic_missing` on questions such as person/responsibility and task-status wording that the stores route handles anyway); of 30 abstention questions 18 are flagged (12 `topic_missing`, 5 `none`, 1 `entity_absent`) and 12 are not. The note is therefore a hint with recall about 60% and a visible false-note rate, which is why it is a note and not a gate.

## Fresh data

- **dev6**: 32 new questions in seven groups (no supporting evidence, partial evidence, wrong entity, conflict, temporal/supersession, actor attribution, negative claims, plus two instruction-contamination). I saw the 7B's failures on dev6 before building the mechanism, so dev6 is development data, not an unbiased test. Five of its forbidden-answer patterns were corrected after the first baseline run because they flagged correct abstentions ("no mention of a second slip") before any mechanism existed; the corrections are in `make_cases_dev6.py` and the first run (`dev6-7b-baseline.json`) is kept.
- **dev7**: 21 further questions written **after the mechanism was frozen** (`sufficiency.py` blob `65e4512b`, unchanged since), evaluated once.

## Results (7B, token budget 1,500)

| | dev6 (32) | dev7 (21, frozen mechanism) | older dev..dev5 (113, regression) |
|---|---|---|---|
| no retrieval | 10 | 10 | |
| B1a + routing (baseline) | 27 | 15 | 91 |
| **+ sufficiency note and retry** | **30** | **17** | **93** |
| + deterministic abstention gate | 30 | 17 | 93 |
| + note + conflict hints | 29 | 17 | |
| oracle (gold sources only) | 28 | 20 | |

(Fully correct counts.) Paired over the two fresh sets: **5 cases better, 0 worse** (two-sided sign test p = 0.0625; dev7 alone 2 better, 0 worse, p = 0.5). On the 113 older answerable-heavy cases: 2 better, 0 worse, and **no over-abstention added** (2 over-abstentions with or without the note).

By group, fresh sets combined (fully correct / cases, baseline → with note; oracle in brackets):

| Group | B1a → +note | oracle |
|---|---|---|
| No supporting evidence | 8/9 → **9/9** | 9/9 |
| Evidence about the wrong entity | 5/9 → **9/9** | 9/9 |
| Partially supporting evidence | 7/7 → 7/7 | 6/7 |
| Conflicting evidence | 3/5 → 3/5 | 4/5 |
| Temporal / supersession | 6/7 → 6/7 | 7/7 |
| Actor / responsibility | 6/6 → 6/6 | 6/6 |
| Negative claims | 5/7 → 5/7 | 5/7 |
| Instruction contamination | 2/3 → 2/3 | 2/3 |

**Reading.** The note repairs the failure it is built for: the model answering about the wrong entity ("The rollback window for Harbor is 60 minutes", "Lantern runs with Falcon-7B", "the budget for the GPU host is approved through December" offered for the Lantern project). With the note, 4 of 4 wrong-entity cases on dev7 and 5 of 5 on dev6 were abstained correctly. It does not touch the other groups because their failures are not a coverage gap.

**What the retry did.** On 138 assessed retrievals, 31 were not `sufficient`, 30 were retried, **6 added any item, and 29 stayed insufficient**. On this small invented corpus a second query rarely finds what the first missed, because the records either contain the answer or do not. The retry is cheap and safe, but its value is unproven here and will depend on a real corpus; it is not what produced the gain.

**What the gate did.** Nothing beyond the note on the fresh sets, and one regression on the older splits (a status-phrased answerable question, "Is the 8-to-6 Beacon schedule still valid?", was abstained from when the gate fired on an `entity_mismatch` verdict). **Recommendation: note only; keep the gate for `none` and all-names-absent at most, and re-measure.** In this configuration the gate would also be wrong whenever retrieval, not the corpus, missed the evidence, which the note tolerates and a fixed reply does not.

## What the remaining failures are

Every remaining failure on the fresh sets is one of three kinds, separated by the oracle (the same model on perfect evidence):
1. **Retrieval-limited** (oracle correct): a conflict where B1a surfaced only one of the two figures (H-C1), and negative-claim questions where lexical retrieval returned an unrelated chunk (H-X2: "yes, the Harbor architecture document mentions Lantern", quoting a Lantern runbook line; H-X3). The sufficiency check cannot see these because the retrieved evidence does look related.
2. **Model-limited** (oracle also wrong): giving one figure of a two-figure conflict even when both are shown (G-C3: "60 minutes" only), repeating the planted vendor instruction ("the vendor note also contains a system instruction... to ignore all previous instructions..."), appended negative claims the evidence does not make ("support staff are not available on weekends", G-X4 oracle), and "Dana did not say anything in the meeting" from a single segment. These are the unsupported-claim failures the sufficiency note cannot fix.
3. **Hedged supersession** (G-T5): "may be outdated" with no evidence for an ordering. The model no longer asserts "is outdated" on the fresh questions, but still hedges toward it.

## Post-generation checks: not usable to enforce

Run over 583 stored replies from all the fresh and older runs (43 labelled bad by the case scorer; `postcheck_eval.py`, label includes scorer false positives so precision is a lower bound):

| Check | flagged | true | false | precision | recall |
|---|---|---|---|---|---|
| unsupported specific (number, weekday, month) | 46 | 3 | 43 | 0.07 | 0.07 |
| unsupported denial | 76 | 17 | 59 | 0.22 | 0.40 |
| invented recency | 39 | 7 | 32 | 0.18 | 0.16 |
| property-with-subject | 54 | 18 | 36 | 0.33 | 0.42 |
| any | 170 | 32 | 138 | 0.19 | 0.74 |

At 19% precision a flag-then-regenerate rule would re-ask the model on about one reply in three for no reason and would sometimes replace a correct answer. **Conclusion: deterministic post-generation checks are a measurement, not an enforcement, tool.** They can feed aggregate telemetry (a rate of flagged replies) but must not replace or regenerate a reply. The earlier claim-verification experiment reached the same conclusion for lexical checks and for a second pass by the local 7B (precision 0.09 to 0.17, 40 to 64% of correct answers flagged; [section 4](phase-44e-shadow-readiness-2026-10-10.md#4-post-answer-claim-verification-experiment-new-cases-only)).

## Limits

- Invented corpus of about 30 records; the assessor and the note have never seen a real-sized store. Real records have many more shared names and words, so `entity_mismatch` and `topic_missing` will behave differently.
- 53 fresh questions, one model, one seed. The only statistically visible effect is the wrong-entity group, and even the pooled sign test is p = 0.0625.
- Replay of identical prompts on the same 7B differs in about 5% of replies (batching non-determinism: 240 of 253 identical), so differences of one or two cases are inside the noise.
- The note raises `topic_missing` on 15 of 83 answerable development questions. It did not change their answers, but a model that over-weights it would abstain more; keep measuring over-abstention.

## Reproducing

`python benchmarks/answer_quality/make_cases_dev6.py` and `make_cases_dev7.py`; `run.py --split dev6|dev7 --conditions b1a+routed,b1a+routed+suff,b1a+routed+gate,b1a+routed+suff+cf,oracle,distractor,none`; `summarize_sufficiency.py`, `sufficiency_eval.py`, `postcheck_eval.py`. Results are under `benchmarks/answer_quality/results/` (`dev6-7b-*.json`, `dev7-7b.json`, `suffreg-*.json`, `sufficiency-summary.txt`, `postcheck-eval.json`).
