# Phase 44E conflict-omission detector: local development findings (2026-10-10)

Development only, on new cases and hand labels. **Not an answer gate and not on any live path.** The detector looks at the question, a reply and the evidence the reply was given, and reports when evidence items disagree about a quantity the question concerns and the reply states only some of the values. Code: `benchmarks/answer_quality/aq/conflicts.py`, evaluation `conflict_eval.py`, results `results/conflict-detector-eval.json`.

## Method

New development cases `cases_dev4.json` (15; none shares a question with dev, dev2, dev3 or the holdout): six conflicts, three temporal (an older version differs, or the question is scoped to one version), six numeric controls (several numbers in the evidence that answer different questions). The local 7B answered each with plain B1a and with the oracle context, two runs: 60 replies, 30 distinct. **Independent labels:** I read each distinct reply against its evidence and wrote three labels per reply (does it leave out a side of a real disagreement; which evidence ids truly disagree; which differences are explained by an older version) in `conflict_labels_dev4.json` before any detector was run on these replies. One labeller, 30 labels, 7 positive: small and not independent of me as author, but independent of the detector and of the case scorer.

Versions: **v1** the detector of the earlier experiment (any two items sharing two words and giving different quantities of one kind). **v2** adds topical restriction (both items must share two content words with the question), a requirement that the two numbers are numbers of the same thing (shared words around the quantity), scoping (questions that name a source or version are not flagged), older-version recognition (an archived or "used to be" item is not required to be repeated), number-word, hyphen, range and "half an hour" normalisation, dates and citation ids ignored, and identification of the disagreeing item pairs. **v3** is v2 with the topical test relaxed (one shared word with the question is enough if the pair shares three words of context).

## Results (60 reply rows, 30 distinct; all three versions ran on the same labels)

| | Precision | Recall | False positives (rows) | Disagreeing pairs reported that are real / found of 20 real | Flags raised only for a temporally explained pair | Median / p95 runtime per reply |
|---|---|---|---|---|---|---|
| v1 | 0.31 | 0.57 | 18 | n/a (no pairs) | n/a | 0.06 / 0.11 ms |
| **v2** | **1.00** | **0.43** | **0** | 6 of 6 / 6 of 20 | 0 | 0.41 / 1.06 ms |
| v3 | 0.83 | 0.71 | 2 | 12 of 14 / 12 of 20 | 0 | 0.50 / 1.27 ms |

A hand-written stress set of 20 reply variants (number words, hyphens, ranges, "half an hour", wrong or partial reporting): v1 18 of 20, v2 and v3 20 of 20.

Findings:
- **False positives were the problem of v1:** it flagged replies that were correct because the evidence also held unrelated numbers (a ten-minute watch beside a 30-minute rollback beside a 60-minute window). The same-thing and topical tests remove all of them in v2.
- **Recall is limited by vocabulary, not by arithmetic.** The misses are questions that paraphrase the evidence ("give up after ten tries" against "retried up to 5 times"; "undo a bad deploy" against "roll back"): without understanding, a question and an item cannot be tied. v3 recovers some of that at the price of false warnings on questions that merely mention a shared word. Neither version can be called reliable on paraphrase.
- **Contradictory-source identification:** when v2 or v3 flag a reply, the pairs they name are real disagreements (6 of 6 and 12 of 14).
- **Temporal consistency:** no flag was raised solely because of an older or archived version (0 of 7 rows that have such a pair), but the detector rarely *names* the temporal pair (0 of 7 exactly as labelled; it is mostly suppressed by scoping), so the temporal explanation is silent rather than reported.
- **Runtime:** under 1.5 ms per reply at nine evidence items, negligible against a 1 to 3 second model reply.
- A false-positive example worth keeping: v3 flagged "How long do I watch the dashboard after deploying Lantern?" over the 30 and 60 minute items because both mention deploying.

## Recommendation

Keep v2 as the precision-first warning (flag to the owner that sources disagree, never withhold an answer), and use v3 only if a higher recall is worth about one false warning in six flags. Do not use either as an answer gate. Nothing is wired into any conversation path. Needs a larger independently labelled set and a second labeller before any reliance.
