# Phase 44 groundedness: dev12 one-shot acceptance record (2026-10-12)

Owner approval, 2026-10-12: *run the frozen dev12 one-shot with the registered arms; do not add a partial-reply arm or change thresholds; report the listed items; preserve dev12 as consumed; stop afterwards.* Protocol and pre-registered guardrails: [phase-44-groundedness-dev12-protocol.md](../phase-44-groundedness-dev12-protocol.md). **dev12 is now a consumed acceptance set: it is not to be rerun or tuned against.** Production is unchanged: the 7B is the default, the 44H boundary is active, indexing is `false`, retrieval and shadow are off, 44F is unimplemented; nothing here is deployed or wired into an answer path.

## Execution

- **Before running:** all **25** manifest hashes verified unchanged (`freeze_check.py dev12_freeze.json`; the dev8 and dev10 manifests also verified); the one-shot guard refused the run without a decision point and without the approval variable, and `dev12_runs.jsonl` did not exist; the scratch Postgres was a **fresh container**, loopback-only (`127.0.0.1:55444`), holding only the invented corpus (the production database was not touched); the 7B server was idle; the arms were exactly those registered.
- **Run:** commit `5301bee`, production 7B (`reachy-local`, Qwen2.5-7B-Instruct-AWQ), temperature 0, seed 44, budget 1,500, scorer v2, 91 cases x 9 arms = 819 rows. Logged once in `dev12_runs.jsonl`; a second attempt is refused. Raw results `results/dev12-acceptance-7b.json`; tables `results/dev12-acceptance-analysis.txt` (`analyze_g.py`), `results/dev12-acceptance-extra.txt` (`analyze_dev12_extra.py`), `results/dev12-acceptance-pairs.txt` (`analyze_dev12_pairs.py`). Nothing (components, thresholds, scorer, cases) was changed after the results.

## Headline

**C1 filter + C2 note (with or without the C3 attendee route) passes all five owner guardrails on the untouched held-out set:** fully correct 60 -> 70 (71 with C3) of 91, unsupported material claims 15 -> 9, false abstention 6 -> 4 (3), answerable fully correct 29 -> 41 (42), 17 (18) paired wins against 7 losses, no citation to a nonexistent or unauthorised span. The deterministic UNESTABLISHED reply cuts unsupported claims to 4 but fails guardrails 2, 3 and 4 (+18 false abstentions); C4 + C5 fails guardrails 2 and 3. Oracle evidence reaches 81 of 91 with 3 unsupported claims, so selection plus a note closes roughly half of the gap to perfect evidence.

## Overall results (91 cases, 54 answerable, 37 unanswerable)

| Arm | fully correct | unsupported material claims | false abstentions (answerable) | answerable fully correct /54 | unanswerable handled /37 | wins / losses / ties vs B0 |
|---|---|---|---|---|---|---|
| **B0 baseline (B1a)** | 60 | 15 | 6 | 29 | 31 | |
| C1 filter | 69 | 10 | 4 | 40 | 29 | 16 / 7 / 68 |
| C2 note | 66 | 11 | 6 | 35 | 31 | 8 / 2 / 81 |
| **C1 filter + C2 note** | **70** | **9** | **4** | **41** | 29 | **17 / 7 / 67** |
| C1 filter + C2 note + C3 | 71 | 9 | 3 | 42 | 29 | 18 / 7 / 66 |
| C1 filter + C2 reply + C3 (high conservatism) | 56 | 4 | 24 | 23 | 33 | 7 / 11 / 73 |
| C4 + C5 | 53 | 7 | 10 | 23 | 30 | 2 / 9 / 80 |
| oracle (context) | 81 | 3 | 0 | 44 | 37 | 21 / 0 / 70 |
| oracle + C4 + C5 (context) | 75 | 3 | 1 | 41 | 34 | 18 / 3 / 70 |

Paired sign tests (two-sided; wins vs losses): C1 + C2 note 17 vs 7, p = 0.064; with C3 18 vs 7, p = 0.043; C1 alone 16 vs 7, p = 0.093; C2 note alone 8 vs 2, p = 0.109. The effect is consistent and not strongly significant at this size; all pairs of interest have at least 12 discordant cases.

## Guardrails, per arm (owner-fixed before freezing; "pass" requires all five)

| Arm | 1 fewer unsupported | 2 false abstention +<=1 and <=3 pp | 3 net answerable loss <=1 | 4 specific correction | 5 zero bad citations | Verdict |
|---|---|---|---|---|---|---|
| C1 filter | 10 < 15 pass | -2 (-3.7 pp) pass | net gain 11 pass | 9 pass | 0 pass | **pass** |
| C2 note | 11 < 15 pass | +0 pass | net gain 6 pass | 6 pass | 0 pass | **pass** |
| **C1 + C2 note** | 9 < 15 pass | -2 (-3.7 pp) pass | net gain 12 pass | 10 pass | 0 pass | **pass** |
| C1 + C2 note + C3 | 9 < 15 pass | -3 (-5.6 pp) pass | net gain 13 pass | 10 pass | 0 pass | **pass** |
| C1 + C2 reply + C3 | 4 < 15 pass | **+18 (+33 pp) fail** | **net loss 6 fail** | **0 fail** (fixed templates are blanket refusals) | 0 pass | **fail** |
| C4 + C5 | 7 < 15 pass | **+4 (+7.4 pp) fail** | **net loss 6 fail** | 1 pass | 0 pass | **fail** |

C5 at claim level: the model produced 51 raw claims in the C4 + C5 arm, 49 passed all four checks, 2 were rejected (one quote not in the cited item, one claim value not in its span), and **no rejected claim was accepted anywhere**; the oracle + C4 + C5 arm produced 43 claims, 42 valid, 1 rejected. One citation outside the registered candidates was found: the oracle arm cited a nonexistent id in a refusal ("I do not have that information [E1]", D12-053); guardrail 5 applies to candidates, and it is reported because it is exactly the kind of model-written citation that is not proof.

## Per-category results (fully correct / n)

| Arm | established | conflicted | wrong entity (unanswerable) | no record | unauthorised | partial / two-part |
|---|---|---|---|---|---|---|
| n | 28 | 10 | 22 | 10 | 5 | 16 |
| B0 | 23 | 2 | 19 | 7 | 5 | 4 |
| C1 filter | 23 | 3 | 17 | 7 | 5 | 14 |
| C2 note | 23 | 4 | 19 | 7 | 5 | 8 |
| C1 + C2 note | 23 | 3 | 17 | 7 | 5 | 15 |
| C1 + C2 note + C3 | 24 | 3 | 17 | 7 | 5 | 15 |
| C1 + C2 reply + C3 | 18 | 3 | 18 | 10 | 5 | 2 |
| C4 + C5 | 18 | 2 | 17 | 8 | 5 | 3 |
| oracle | 28 | 3 | 22 | 10 | 5 | 13 |

Reading: the gain is concentrated in the **partial / two-part and cross-sentence questions** (4 -> 15 of 16), which are exactly the questions where distractors from sibling projects made the 7B join facts that no record joins. Conflicts stay poor in every arm including the oracle (3 of 10): reporting both sides is a **generation** failure the milestone's components do not address. **Wrong-entity questions got slightly worse with C1** (19 -> 17), see below.

## Where C1 helped and where it hurt

Records shown fell from 8.6 to 3.1 and **non-gold records shown from 8.0 to 2.4**. Against the baseline: 16 cases improved and 7 regressed.

**Improvements (16).** 10 partial / two-part cases ("Which model sits behind the Sable deep path?", "Whose job is the Gantry scheduler, and what size limit does it have?") where non-gold records fell from 9 or 10 to 1 to 3; 3 established paraphrase questions ("Whose job is it to look after the Ferry queue?", non-gold 10 -> 3); 1 conflict (the Relay retry count, both values now reported); 2 unanswerable wrong-entity cases (the Sable and Thistle model-decision questions).

**Regressions and gold removal (7 cases).**
- **Gold evidence removed by the filter in 3 cases** (D12-003 "How long does the Osprey budget run?", D12-019 "Which model did the Vesper team agree to keep?", D12-023 "Which people took part in the Marlin planning?"; the last was already wrong in the baseline): all three are **unseen paraphrases or held-out relations** that the written lexicon does not recognise ("run", "agree to keep", "took part"). This is the recall cost of a hand-written lexicon on unseen phrasing.
- **New unsupported assertions in 4 unanswerable cases** (D12-042, 052, 053, 054): when C1 finds no asserting record it falls back to showing a few "related" records, and the 7B then asserts from them ("Thistle serves Kestrel-9B" as the decision; "the Umbra budget is approved through October"). **This is a design weakness of the C1 fallback, found here and not fixed** (the protocol forbids tuning on dev12): unsupported claims rose by 4 in this group while falling by 10 elsewhere.
- **1 case is a gold ambiguity artefact** (D12-011, below).

## C2 answerability decisions (computed with no generator; on the C2-note arm)

- **False UNESTABLISHED (answerable-labelled questions called unestablished): 23 of 54**, of which 11 are the "which model sits behind the deep path" questions (the label PARTIAL says the record answers part; as asked, the proposition is indeed unestablished, so these are a labelling nuance, not a clear error), 3 two-part size questions, and **9 true false positives** on established questions (deadline 3, owner 3, on-call 1, decision 1, lead 1: paraphrase and held-out relations). With the note, those 23 questions were answered correctly 11 times against 7 for the baseline, so the note did not make the 7B over-abstain.
- **Missed UNESTABLISHED (unanswerable called established, conflicted or partial): 15 of 37**: 8 attendee questions (C2 deliberately defers `attends` to C3), 4 budget questions, 3 decision questions; 4 of the 15 involve held-out relations. The note on these missed cases did not change the outcome (unsupported 1 against 1).
- **Detected correctly:** all 10 no-record and all 5 unauthorised questions, 7 of 22 wrong-entity.
- Dev11 reported 8 false UNESTABLISHED among answerable questions and 0 missed (17 of 17 detected) with a design-tuned lexicon; on held-out data the misses appear (15 of 37). That asymmetry is the generalisation cost of the lexicon.

## Scorer disagreements (listed; primary scores are unmodified)

1. **Generic no-record forbidden pattern ("signs off|reviewer|approves").** It fired on 3 questions (Sable, Umbra, Quartz security) in every arm where the reply correctly abstains but repeats the question's own words ("does not mention who approves Quartz security changes"): 3 false-positive unsupported claims per arm in B0, C1, C2, C1+C2 and C4+C5 (and 3 in oracle + C4 + C5). Annotated unsupported counts (question-echo hits removed): B0 12, C1 7, C2 8, **C1 + C2 note 6**, with C3 6, reply arm 4, C4 + C5 5, oracle 3, oracle + C4 + C5 0. The guardrail verdicts do not change (the annotated reduction is 12 -> 6 for the candidate against 15 -> 9 automatic).
2. **Ambiguous gold in 5 dev12 cases (my generator defect, found after the run):** the fact registry holds two facts for the same subject and relation for `deadline` (Dmitri Volkov: Monday in one note, Tuesday in another; Rania Said), `reviews` (Greta Lindqvist, Tara Brennan) and a `runs_on` duplicate, so D12-008, 010, 011, 013 and 022 have a required value that is only one of two valid ones. D12-011 is one of the 7 C1 regressions (the baseline mentioned the conflict, C1 gave "Monday"). Excluding all five from every arm: C1 + C2 note wins 17, losses 6 (p = 0.035), 66 vs 55 fully correct; C1 + C2 + C3 wins 18, losses 6; guardrails unchanged. This defect was not corrected in `cases_dev12.json` (frozen); it is disclosed for the next protocol.
3. Genuine failures that look like disagreements but are not: conflicts answered with only one of the two values (D12-029, 030, 033, 035, 034); "The Juniper deep path uses the Merlin-2B model" (D12-089, the cross-sentence join the milestone targets, still made once by the candidate).
4. Rendering: C4's "I don't have a record that establishes..." line is read by the scorer as an abstention, which inflates false abstention in the C4 arms when facts are missing.

## Latency and resources (7B, serial)

Model-call latency, median / p95 ms: B0 1,151 / 2,574; C1 filter 851 / 2,339; C2 note 1,206 / 2,681; **C1 + C2 note 864 / 2,260**; with C3 832 / 2,182 (9 questions answered without a model call); reply arm 0 / 1,360 (54 model calls skipped); C4 + C5 1,282 / 1,798; oracle 522 / 1,282. Prompt tokens, median: B0 934, C1 + C2 note 541 (-42%); completion tokens 37 vs 31. **Not measured in this run:** the CPU cost of retrieving 30 candidates instead of 10 and of the selection itself (the harness recorded 0 for those arms). On the design pool the selection operates on tens of sentences per question and is expected to be milliseconds, but that is unmeasured and must be timed before any integration review.

## Does C1 + C2 qualify for a scoped integration-readiness review?

**Yes, narrowly and with named conditions.** For: it passed all five pre-registered guardrails on untouched data with held-out relations, projects and paraphrases; it lowered unsupported claims (15 -> 9, 12 -> 6 annotated) and false abstention, raised answerable correctness by 12 cases, cut prompt size by 42% and median model latency by about a quarter, never accepted an unauthorised or nonexistent citation, and C2's note did not cause over-abstention. Against: 7 regressions (4 are new unsupported assertions from the "related records" fallback; 3 lose gold evidence to lexicon gaps on unseen phrasing); the gain is concentrated in one family (cross-sentence and two-part questions); conflicts are unaffected; C2 misses 15 of 37 unanswerable questions; the invented corpus is small; the selection cost is unmeasured; the p-value is 0.064 (0.035 once five ambiguous-gold cases are excluded); and the lexicon is hand-written.

**Not qualified:** the deterministic UNESTABLISHED reply (fails guardrails 2, 3 and 4, as predicted) and C4 + C5 (fails 2 and 3). **C5 is preserved** as an experimental deterministic claim/evidence validator: it did its job at claim level and is not blamed for the arm that failed. C4 JSON-generation optimisation is paused by owner decision.

**A scoped integration-readiness review should ask for, at minimum:** a fix of the C1 fallback that does not hand "related" records to the model as if they supported an answer (a new development protocol, not a patch on this result); a recall target for the lexicon on unseen paraphrase measured on new data; timing of the 30-candidate retrieval and selection; a re-run with the ambiguous cases corrected on a **new** untouched set; and measure-only evaluation on realistic data before any answer-path use. Nothing is deployed or activated.

## Deferred, per the owner

The **partial-reply policy** (selective answering of supported sub-claims) was not tried and does not contaminate this comparison; a separate development and acceptance protocol for it is the next proposal. PostgreSQL backup is a separate future phase; the existing recovery assets are retained and the untested backup draft is not deployed.
