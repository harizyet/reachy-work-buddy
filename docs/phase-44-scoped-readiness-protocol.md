# Phase 44: scoped integration-readiness review of the revised C1 + C2, protocol (frozen 2026-10-12; dev14 RUN ONCE and CONSUMED 2026-10-12)

**Result: [dev14 acceptance record](verification/phase-44-scoped-readiness-dev14-2026-10-12.md): the revised candidate fails guardrails 2 and 5 and does not qualify as built.** The protocol below is as frozen.

Owner decisions after dev12 (2026-10-12): C1 + C2 qualifies for a scoped integration-readiness review, **not** production deployment. Address: (1) remove or quarantine the related-record fallback; (2) a recall target on genuinely unseen paraphrases; (3) timing of the complete path; (4) fix the generator's duplicate-gold defect; (5) evaluate the frozen revised candidate on a new untouched set without retuning on dev12; (6) keep C1, C2, C3 separate; (7) C2 is a calibrated annotation, not a gate; (8) keep the original dev12 statistics and claim no significance from post-hoc exclusions. Nothing here is activated: the 7B is the default, 44H is active, indexing is `false`, retrieval and shadow are off.

## What changed (revised modules, `knowledge/grounding/revised/`; the dev12-frozen originals are untouched)

- **Fallback:** the "related records shown when nothing asserts" behaviour is gone. Variants developed on dev13: **remove** (`r1`, show nothing), **decline** (`r1d`, show the baseline when the relation is unrecognised), **quarantine** (`r1q`, related records only inside a clearly labelled, non-citable "does NOT state what was asked" block, with no evidence id and with instruction-like text left out).
- **Lexicon:** a general synonym lexicon for 12 relations (it now includes on_call, budget_through and deadline) plus weak-cue weighting; a meeting speaker's name no longer counts as "another actor" (a defect that had suppressed meeting-based relations).
- **C2:** same computation, hedged annotation text ("an estimate that may be wrong"), a `calibration()` utility, and **no** deterministic reply.
- **Timing:** every stage is timed (30-candidate retrieval, C1 selection, C2, builder, model call, end to end).
- **Corpus v3:** a new seed and assignments, **unique facts per (subject, relation)** enforced by `check_unique` (the v2 duplicates are the cause of the five ambiguous dev12 cases), three **new** held-out relations (release_day, escalation_contact, storage_limit) that nobody designed against, new held-out projects, and two paraphrase banks: bank A (design) and bank B (unseen), **bank B hashed (`bank_b.sha256`, commit 8a2abfb) before any revised lexicon existed.** Same-author caveat: "unseen" means unseen by the lexicon's design process, not written by an independent person.

## Development result that fixed the candidate (dev13, 71 design cases; design data, not acceptance)

| Arm | fully correct | unsupported claims | false abstention | guardrails 1 to 5 |
|---|---|---|---|---|
| B0 baseline | 51 | 11 | 1 | |
| frozen v1 comparator (C1 filter + C2 note, with the old fallback) | 59 | 4 | 2 | pass |
| revised C1 remove (`r1`) | 50 | 5 | 9 | fail (false abstention +8, net loss 5) |
| revised C1 decline (`r1d`) | 47 | 8 | 9 | fail |
| **revised C1 quarantine (`r1q`)** | 57 | 6 | 1 | fail only on one citation to a nonexistent id |
| C2 annotation (`r2`) | 54 | 9 | 1 | pass |
| **r1q + r2** | **58** | **6** | **1** | **pass** |
| r1q + r2 + C3 | 61 | 5 | 1 | pass |
| oracle | 63 | 2 | 1 | |

Pre-declared selection rule (written before the run): fewest unsupported claims subject to false abstention at most baseline + 1 and net answerable loss at most 1; ties prefer remove, then quarantine, then decline. **r1 and r1d fail the false-abstention constraint** (removing the related partial fact, for instance "scheduled jobs use the deep path", makes the model refuse); **r1q + r2 is the frozen revised candidate.** It is **not better than the old v1 on dev13** (58 and 6 unsupported against 59 and 4): the price of not presenting related records as evidence is a little accuracy, which is the point of the owner's condition. Component results, no model, 300 design questions: relation recognised on 262, gold retained by revised C1 in 187 of 220 against 203 for B1a's top 10 (16 of the 33 lost are the deep-path questions whose supported partial fact lives in the related record), non-gold records shown 8.3 -> 1.1, C2 calls 74 of 96 unestablished questions correctly and 16 of 204 answerable ones wrongly.

## The acceptance set: dev14 (frozen, untouched, one run)

`cases_dev14.json`: 101 cases over corpus v3 (62 answerable), balanced across 21 relations, built **only** from bank B phrasings of the design relations, every phrasing of the three new relations, and the four held-out projects. None of it was used for design; no model has run on it; `dev14_freeze.json` hashes the corpus, registry, generators, banks, cases, the whole `grounding/` package including `revised/`, the harness, the scorers and the analysis scripts. `run_g2.py --split dev14` refuses without a decision point, `AQ_DEV14_APPROVAL`, an unchanged manifest and a first run.

**Arms (registered):** B0 `b1a`; frozen v1 comparator `b1a+c1f+c2n`; revised C1 alone `b1a+r1q`; C2 annotation alone `b1a+r2`; **candidate `b1a+r1q+r2`**; candidate with attendee routing `b1a+r1q+r2+c3`; oracle (context). 7B, temperature 0, seed 44, budget 1,500, scorer v2, scratch Postgres.

## Pre-registered reading

A. **The owner's five guardrails** for each candidate arm against B0: (1) strictly fewer unsupported material claims; (2) false abstention among answerable cases at most +1 case and +3 percentage points; (3) at most one net loss of fully correct answerable cases; (4) at least one unsupported answer corrected without a blanket refusal; (5) zero citations to a nonexistent or unauthorised source span.
B. **Recall targets on unseen paraphrases** (the 'recall target' the owner asked to be established): on bank B questions of the design relations and design projects with ESTABLISHED or CONFLICTED labels, (i) the relation is recognised for at least **85%**, and (ii) the revised C1 retains the gold records for at least B1a's rate minus **5 percentage points**. The new relations (generic path) are reported separately with no target.
C. **Timing:** report, for every arm, preparation, model call and end-to-end medians and p95, and for the revised arms each stage (retrieval of 30 candidates, selection, C2, builder).
D. **C2 calibration:** the confusion matrix, precision per predicted state and recall per label on dev14, reported as annotation reliability; no gate is derived from it.
E. **Statistics:** the paired sign test on the registered case set is the only significance statement; any exclusion analysis (for example of a defective case) is labelled post hoc and gives no p-value claim. The dev12 statistics are unchanged and reported as originally.
F. Everything else in the earlier acceptance record format: per-label results, paired wins/losses/ties by case id, regressions, scorer disagreements listed beside unmodified scores, resource overhead.

The result informs a **separate** owner decision on whether any component advances toward measure-only integration; it deploys nothing.
