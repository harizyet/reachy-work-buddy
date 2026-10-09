# Phase 44: scoped readiness review of the revised C1 + C2, dev14 acceptance record (2026-10-12)

Protocol and pre-registered reading: [phase-44-scoped-readiness-protocol.md](../phase-44-scoped-readiness-protocol.md). **dev14 is consumed:** run once, not to be rerun or tuned against. dev12's primary scores, paired regressions and five ambiguous-gold cases are unchanged and preserved ([record](phase-44-groundedness-dev12-acceptance-2026-10-12.md)). Nothing is deployed or activated: the 7B is the default, the 44H boundary is active, indexing is `false`, retrieval and shadow are off, 44F is unimplemented, the backup work is parked.

## Execution

Before the run: all 34 dev14 manifest hashes verified (and the dev8, dev10, dev12 manifests); the guard refused the run without a decision point and without the approval variable; no `dev14_runs.jsonl`; the scratch Postgres was a loopback-only container holding only invented data; the 7B was idle. Run: commit `c5f1ebd`, 7B at temperature 0, seed 44, budget 1,500, scorer v2, 101 cases (62 answerable) x 7 arms = 707 rows, logged once. Results `results/dev14-acceptance-7b.json`; tables `results/dev14-acceptance-analysis.txt`, `results/dev14-acceptance-extra.txt`. Nothing was changed after seeing results.

## Headline

**The revised candidate (C1 with quarantine + C2 annotation) lowers unsupported claims the most of any arm so far (11 -> 3) and raises fully correct from 67 to 80 of 101, but it FAILS two of the five guardrails: false abstention +5 (+8.1 pp) and 14 citations to a nonexistent id.** It therefore does not meet the bar for integration readiness as built. The C2 annotation on its own passes all five guardrails but its effect is small. The old frozen v1 comparator also misses guardrail 2 narrowly on this set (+2, +3.2 pp).

## Results (101 cases, 62 answerable, 7B)

| Arm | fully correct | unsupported claims | false abstention | answerable fully correct /62 | wins / losses / ties vs B0 | G1 | G2 | G3 | G4 | G5 | all |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **B0 baseline** | 67 | 11 | 10 | 35 | | | | | | | |
| frozen v1 (C1 filter + C2 note) | 77 | 5 | 12 | 41 | 15 / 5 / 81 | pass | **fail** (+2, +3.2 pp) | pass | pass | pass | **no** |
| revised C1 quarantine (`r1q`) | 73 | 6 | 14 | 40 | 12 / 6 / 83 | pass | **fail** (+4, +6.5 pp) | pass | pass | **fail** (7) | no |
| revised C2 annotation (`r2`) | 69 | 9 | 10 | 35 | 4 / 2 / 95 | pass | pass (+0) | pass | pass | pass | **yes** |
| **candidate `r1q + r2`** | **80** | **3** | 15 | 44 | **19 / 6 / 76** | pass | **fail** (+5, +8.1 pp) | pass (net gain 9) | pass (11) | **fail** (14) | **no** |
| candidate + C3 route | 80 | 3 | 15 | 44 | 19 / 6 / 76 | same as candidate | | | | | no |
| oracle (context) | 89 | 4 | 2 | 50 | 25 / 3 / 73 | | | | | | |

Significance, on the registered case set with no exclusions: candidate vs B0 19 wins vs 6 losses, two-sided sign p = 0.015; v1 vs B0 15 vs 5, p = 0.041; candidate vs v1 11 vs 8, p = 0.65 (**not distinguishable from the old v1**); `r1q` alone 12 vs 6, p = 0.24; `r2` alone 4 vs 2, p = 0.69.

Per label (fully correct, B0 -> candidate): established 25 -> 25 of 34; conflicted 2 -> 7 of 10; wrong entity 20 -> 22 of 24; no record 7 -> 9 of 10; unauthorised 5 -> 5; partial / two-part 8 -> 12 of 18 (oracle 14). On design relations (88 cases) the candidate scores 70 against 57 with 3 unsupported claims against 9; on the three new relations (13 cases) it scores 10 against 10.

## Why the candidate fails

1. **Guardrail 5, 14 citations to a nonexistent id: the quarantine block invites use.** All 14 occur in replies where the revised C1 found no asserting record, so the evidence message held no evidence blocks, only the quarantined "related context" lines. The 7B treated those lines as evidence ("as stated in the related context [E1]", "...[E1]") and cited an id that does not exist. Some of those statements were even true (a storage limit read from the quarantined line), which shows why a quarantine written as readable text is not a quarantine. The design lesson is that an unciteable block is not enough: the model needs no id to *use* the content.
2. **Guardrail 2, +5 false abstentions:** 3 two-part questions where the model refused both halves although the owner half was supported ("Whose job is the Lattice store, and what size limit does it have?": the lexicon has no cue for "job"), 1 retry-limit conflict question whose paraphrase was not recognised, and 2 questions about the new relations (generic path), where C1 dropped the gold record (gold retained for the 6 answerable new-relation cases: 1 of 6 against 5 of 6 for B1a).
3. **Three new unsupported assertions remain** (D14-055 and D14-061, a related record taken as the answer; D14-076, a scorer false positive, below).

## Pre-registered recall targets on unseen paraphrases

- **Relation recognised on bank B (unseen) questions of the design relations: 27 of 32 = 84%, against the 85% target: missed by one question** (all design-relation questions with ESTABLISHED or CONFLICTED labels: 33 of 38 = 87%). Misses are phrasings with no cue in the lexicon ("Whose job is...", "Who joined...", "...supposed to look over").
- **Gold retention by the revised C1 on the same questions: 23 of 32 against 22 of 32 for B1a's top 10 (+3.1 pp), target at least minus 5 pp: met.**
- New relations (generic path): not met in practice (1 of 6 retained).
- The same-author caveat from the protocol applies: bank B was hashed before the lexicon existed, but one author wrote both.

## C2 as a calibrated annotation (candidate arm, 101 questions)

Precision per predicted state: UNESTABLISHED 32 of 61 (52%), ESTABLISHED 22 of 30, CONFLICTED 7 of 7, PARTIAL 3 of 3. Recall per label: UNESTABLISHED 32 of 39, ESTABLISHED 22 of 34, CONFLICTED 7 of 10, PARTIAL 3 of 18. **29 of 62 answerable questions were wrongly called UNESTABLISHED** (mainly the new relations, two-part questions and unseen paraphrases). The calibration says what the annotation is good for: a hedged hint (as `r2` alone, whose effect is small and safe) and certainly not a gate, which would have withheld nearly half of the answerable questions.

## Timing of the complete path (7B, serial; ms)

| Arm | preparation median | model call median | end to end median / p95 | prompt tokens |
|---|---|---|---|---|
| B0 | 29.6 | 1,151 | 1,169 / 2,433 | 911 |
| frozen v1 | 23.7 | 941 | 957 / 2,055 | 537 |
| **candidate** | 18.6 | 932 | **954 / 1,984** | **437** |
| oracle | 2.5 | 579 | 584 / 1,159 | 396 |

Stages of the revised path: retrieval of 30 candidates median 14.9 to 17.2 ms (the baseline's retrieval of 10 is part of its 29.6 ms preparation), **C1 selection median 2.5 ms (p95 4.9 to 7.3)**, C2 0.01 ms, builder 2.4 ms. The selection cost is negligible; the candidate's end-to-end latency is about 18% below the baseline's because the prompt is more than halved.

## Scorer notes and defects found (primary scores unmodified)

- **D14-076** (unsupported): the reply abstains and quotes the record's own date ("the record I have is from May 1, 2026, stating that Bruno Keller is the Quartz lead"); the month pattern read it as an invented vacation date. A false positive. Annotated unsupported claims for the candidate: 2 instead of 3.
- **Gold ambiguity from my own generator again, in a different form:** v3 added a `storage_limit` relation ("limited to N GB per tenant"), and the two-part questions ask for a "size limit" or "how large may one message be": the storage quota can be read as the answer, so the unsupported-part gold of the 9 `owner+max_message_size` questions is ambiguous. It affects every arm; the candidate's replies "it has a size limit of 90 GB per tenant" are the model doing exactly that. Not corrected in the frozen set; the validator `check_unique` does not catch semantic overlap between relations.
- **C3 did nothing:** `routes.py` (frozen and unchanged) reads questions with the original lexicon, so "Who joined the Vesper planning session?" and "took part" never reached the route; the candidate + C3 arm equals the candidate. A known defect to fix in the next revision (the revised lexicon is not used by C3).
- Genuine failures that look like disagreements: conflicts answered with only one value (D14-042), a related record taken as the answer (D14-055, D14-061).

## Conclusion and what the review would need next

The revised candidate **does not qualify for integration readiness as built.** It is a real improvement on unsupported claims and correctness (p = 0.015 against the baseline) and on prompt size and latency, but it is not distinguishable from the old v1 (p = 0.65), and it fails the false-abstention guardrail and the citation guardrail. What it shows for the next iteration, none of which has been built:
1. **The quarantine must not give the model readable content with values** (titles only, or a structured count of related records, or nothing); then re-test guardrail 5.
2. **A generic-path rule that does not drop gold when the relation is unknown** (the decline behaviour, which failed on dev13 for the other reason, needs a different formulation).
3. **Lexicon recall:** cues for "job", "joined", "took part"-style paraphrases, measured on a new unseen bank; C3 must use the revised lexicon.
4. **Two-part questions** are where the false abstentions concentrate; that is the selective-answering protocol ([proposal](../phase-44-selective-answering-protocol.md)).
5. **Generator:** check semantic overlap between relations (storage limit vs message size) as well as duplicates.
Any of these needs a new development set and a new untouched acceptance set; dev13 and dev14 are spent for design purposes. **No production decision follows from this record.**
