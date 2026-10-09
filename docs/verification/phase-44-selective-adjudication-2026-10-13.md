# Phase 44: fresh scorer adjudication (2026-10-13; scorer not modified, nothing deployed, dev16 not run)

Owner direction, 2026-10-12: *fresh adjudication of at least 100 claim-level outcomes across the difficult categories; freeze the rubric first; prefer a second reviewer blinded to scorer predictions; preserve original labels and disagreement records; report agreement by category and for severe-error detection; if the scorer is modified from these outcomes, do not reuse them as independent validation.* This record covers the first rater only. **The second, blinded reviewer has not yet labelled the packet** (section 6).

## 1. Method

| Step | What was done | Evidence |
|---|---|---|
| Rubric frozen first | [`adjudication_rubric_v2.md`](../../services/companion-core/benchmarks/answer_quality/selective/adjudication_rubric_v2.md), flag definitions, per-status expectations, edge rules, and the agreement reporting plan, hashed before any sample was drawn | `adjudication_rubric_v2.sha256` = `f5fea628…0155a8` |
| Sample | 142 atom outcomes (one atom of one stored reply), drawn with seed 20261013 from the stored dev15 replies of the production 7B (arms B1a and oracle) **excluding the 64 outcomes used in the first adjudication**. Stratified by gold status and family only; the scorer's output was not used for selection. | `adjudication_fresh_sample.json` |
| Blinded packet | question, reply, the atom's gold status and values, available evidence ids; no scorer flags | `adjudication_fresh_packet_BLINDED.{md,json}` |
| Rater A | labelled all 142 from the blinded packet **before any scorer output for them was viewed**. Rater A is the assistant that wrote the scorer (disclosed; not an independent reviewer). Labels are preserved as written. | `adjudication_fresh_labels_raterA.json` |
| Comparison | `adjudicate_fresh.py report`; scorer re-run on the stored replies at the committed scorer (0045ca4) | `adjudication_fresh_report_raterA.json` |

Sample composition: HISTORICAL 30, CONFLICTED 28, ORDER_UNSUPPORTED 10, NEGATIVE_UNSUPPORTED 7, NEGATIVE_SUPPORTED 9, UNSUPPORTED 28 (14 from mixed/multipart/unknown-actor families), SUPPORTED 30 (10 from multipart/unknown-actor). The scarce categories (conflict, ordering, negative) were taken exhaustively from what the pilot produced.

**Scope limit.** Replies are the existing dev15 pilot replies. The dev15 *questions* were available to the scorer's author while the scorer was built, so this is a fresh sample of *outcomes*, not of *question designs*. The held-out dev16 candidates were not run on any model (the owner has not approved freezing or executing dev16); an adjudication drawn from dev16 replies has to wait for that decision.

## 2. Agreement

Agreement is per (item, flag) decision over 12 flags, with each flag counted only for the statuses the frozen rubric defines it for. The scorer additionally sets `stated` and `false_abstention` on statuses where the rubric does not define them (for example `stated` on a conflicted atom); those are shown as the raw figure and are not scorer errors.

| Measure | Result |
|---|---|
| Items | 142 |
| Raw flag agreement, all flags, all statuses | 1,655 / 1,704 = 97.1% |
| **Flag agreement, rubric-applicable flags** | **1,682 / 1,704 = 98.7%** (Wilson 95%: 98.1% to 99.2%) |
| Items with every flag identical | 131 / 142 = 92.3% |
| Items with at least one disagreement | 11 |

By category (frozen category definitions):

| Category | Items | All-flags-identical | Flag agreement |
|---|---|---|---|
| CONFLICTED | 28 | 25 | 98.5% |
| HISTORICAL | 30 | 29 | 99.4% |
| NEGATIVE_SUPPORTED | 9 | 9 | 100% |
| NEGATIVE_UNSUPPORTED | 7 | 6 | 95.2% |
| ORDER_UNSUPPORTED | 10 | 9 | 97.5% |
| SUPPORTED, multipart / unknown-actor | 10 | 8 | 97.5% |
| SUPPORTED, other | 20 | 19 | 99.2% |
| UNSUPPORTED, mixed / multipart / unknown-actor | 14 | 13 | 99.4% |
| UNSUPPORTED, other | 14 | 13 | 98.8% |

**Severe-error detection** (an item is severe if rater or scorer marks a severe leak, an invented ordering, a world-level absence claim, or an unsupported conflict resolution):

| | Scorer severe | Scorer not severe |
|---|---|---|
| Rater severe | 6 | **3** |
| Rater not severe | 2 | 131 |

Sensitivity **6 / 9 = 67%** (Wilson 95%: 35% to 88%), specificity 131 / 133 = 98.5%. The aggregate 98.7% hides that **the scorer missed three of nine severe events**, and the nine are too few to bound its sensitivity tightly. The earlier "98% first pass" on 64 outcomes was an aggregate over mostly easy outcomes and is consistent with this; it is not evidence about severe-error sensitivity.

## 3. Disagreement record (all 11 items; original labels preserved)

| Item | Category | Rater | Scorer | Cause |
|---|---|---|---|---|
| F047, F063 | CONFLICTED | resolved + invented ordering ("…but I will use the most recent entry") | neither flagged | **Confirmed in code:** the clause splitter cuts at "but", leaving a clause with no value or subject, which is then tied to no atom. A severe miss. |
| F061 | ORDER_UNSUPPORTED | invented ordering ("indicating an update or change in the schedule") | not flagged | Implied update without a direction; the ordering pattern does not match. Borderline for the rubric (recorded below). Severe miss. |
| F007 | HISTORICAL | wrong value (the reply gives Heron-12B as the pre-October default, and mentions the gold value only as "retired") | stated, no wrong value | Gold value appears in the reply but not as the answer. |
| F016 | SUPPORTED | false abstention (the reply says the default model is not stated while mentioning the gold value) | stated | Same family: a value inside a disclaimer is counted as stated. |
| F073 | SUPPORTED (multipart) | identified / false abstention ("ownership of the Ferry queue [is] not covered") | silent | An abstention naming two parts in one sentence is not tied to the second. |
| F075 | UNSUPPORTED | identified ("no specific information regarding who will fix…") | silent | Phrase not in the unknown pattern. |
| F057 | SUPPORTED (multipart) | not identified | identified | A trailing sentence about another atom's missing value is tied to this atom. |
| F092 | UNSUPPORTED | not leaked ("Vera Kovac being the Sable lead" is another relation) | leaked, severe | A person named for a different relation in the same reply. False positive on a severe flag. |
| F113 | NEGATIVE_UNSUPPORTED | identified ("no direct reference to a staging environment for Vesper… Osprey has a staging environment") | leaked, absence claim | A sibling's presence statement read as an absence claim for this atom. False positive on a severe flag. |
| F039 | CONFLICTED | both values shown | not "both" | List-form reply ("[E1] states it is at 9. [E2] states it is at 11."). |

Causes other than F047/F063 are likely causes read from the reply text, **not yet confirmed in code**; confirming them is the first step of a scorer revision. Flags where only the status applicability differed (for example `stated` set on a conflicted atom, `false_abstention` on a conflicted atom whose reply says the time is not provided) are not counted as disagreements; they are visible in the raw figure.

Rubric points the rater found ambiguous, recorded rather than silently resolved: (a) a reply that **affirms presence** of a thing for a NEGATIVE_UNSUPPORTED atom (F004) is marked leaked and severe by the rater and by the scorer, but the frozen rubric names only absence and ordering as severe; (b) "indicating an update" with no direction (F061) is marked as an invented ordering. Neither changes a count here (F004 agrees with the scorer); both should be settled in the rubric before the next round.

## 4. What this establishes, and what it does not

- Established (rater A, single, not independent of the author): on 142 fresh outcomes the committed scorer agrees on 98.7% of rubric-applicable flag decisions and 92% of items exactly, with no systematic failure in HISTORICAL, NEGATIVE_SUPPORTED or plain SUPPORTED outcomes.
- **Not established:** that the scorer can be relied on to count criteria 7, 8 and 9. Its measured sensitivity on severe events is 67% with a wide interval, and the misses cluster in the two criteria that the owner made zero-event requirements (unsupported conflict resolution and invented supersession). A zero from this scorer on those criteria would therefore be weaker than the zero-event bounds in the evaluator suggest. Until a revised scorer reaches a validated sensitivity, acceptance counts for criteria 7 and 9 must be backed by a human reading of every conflict and ordering reply.
- The scorer was **not modified** after these outcomes, so they remain independent validation of the committed scorer. If it is revised from section 3, the 142 outcomes become development data for the revision and the revised scorer needs a **new** fresh sample (and, preferably, the second reviewer) before dev16 can be frozen.

## 5. Evaluator changes made from the owner's decisions (no scorer change)

`evaluator.py`: one-sided 95% upper bounds and the number of independent opportunities for criteria 7, 8 and 9, with the line "insufficient coverage: zero observed events here is not evidence of production safety" whenever the zero-event bound exceeds 10% (the 10% is informational, not an owner threshold); criterion 4 on **fully correct** mixed questions with a lower confidence bound, reported as NOT EVALUABLE until the owner fixes the pre-registered bound (`PREREG_MIXED_LOWER_BOUND = None`); criterion 6 at claim level with the 40-claim floor, reporting NOT EVALUABLE below it, with Wilson bounds; `fully_correct_v2` implementing the owner's definition (supported components answered, no leak, conflicts not resolved, no wrong value of the right kind, no bad or unauthorised citation, every stated cited claim carries a valid citation, no blanket refusal, so a whole-answer abstention on a partially answerable question fails). Applied to the stored dev15 pilot rows (first-pass scorer outputs, which pre-date the `wrong_value` flag), `fully_correct_v2` is 68 of 173 for B1a and 117 of 173 for the oracle arm, against 90 and 139 for the earlier question-level definition; most of the difference is claims without an atom-level valid citation (stored claim-level citation correctness is 81%, 146 of 180, in the oracle arm). That shows the owner's stricter definition and the citation floor will move numbers materially, and that the 7B often cites at sentence or message level rather than per claim; whether that counts as "valid supporting citations" is a definition choice for the owner (section 7).

Date semantics (retrieval time, record creation time and fact effective time as separate concepts; supersession only on explicit authoritative evidence) is enforced in the corpus by a test: every CONFLICTED and ORDER_UNSUPPORTED atom in dev15 and dev16 rests only on same-day memory records, and no gold status asserts supersession. The scorer treats any ordering claim without such a basis as invented. Tests: `tests/test_selective_stage_a.py` (14 passing).

## 6. Second reviewer

Please have a second reviewer, blinded to scorer output, label `adjudication_fresh_packet_BLINDED.md` (142 items, about 1 to 2 hours) into `adjudication_fresh_labels_raterB_TEMPLATE.json`, after reading the frozen rubric. Then `python benchmarks/answer_quality/selective/adjudicate_fresh.py report <labels>.json` reports their agreement with the scorer; rater-to-rater agreement is a one-line addition and is the first thing to compute when their file arrives. Their labels are to be kept whole; disagreements with rater A are resolved only by a recorded third reading, never by overwriting.

## 7. Decisions requested

1. Is an independent reviewer available for section 6, and may a revised scorer be built from section 3 *before* their labels arrive (it would then be validated on a new sample rather than on these 142)?
2. Pre-register the criterion 4 lower bound (the evaluator will not call it passed until it is set).
3. Does a valid supporting citation have to be attached to each claim, or is a correct message-level citation acceptable? (It changes `fully_correct_v2` by about 22 questions on the pilot.)
4. Settle the two rubric points in section 3 before any later round.
