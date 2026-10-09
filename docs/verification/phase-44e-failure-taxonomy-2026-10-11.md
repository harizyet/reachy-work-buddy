# Phase 44E failure taxonomy (2026-10-11), Stage 1 of the controlled-use milestone

Source: the 21 reviewed answers ([blind review](phase-44e-blind-review-2026-10-10.md)) and the first-look rows where B1a or B1b was not fully correct ([first-look report](phase-44e-first-look-2026-10-09.md)). The owner reviewed the 21 answers and **broadly agrees** with the independent assessment. The submitted ratings are unchanged; the rating-finalization sheet below lets the owner confirm or override each item. **The review is now an informed one, not a blind one:** the key was unsealed when the comparison ran, and the comparison report names the system behind several items; the sealed key file stays outside the repository and the original evaluation artifacts are untouched.

## Finalizing the ratings (no key disclosure)

`benchmarks/answer_quality/blind_finalize.py sheet` produces `blind_review/phase-44e/owner-confirmation.md` (each item's question, answer, the submitted rating and its note, with no system name, case id or score) and `owner-confirmation-template.csv` (`item,q1_owner,q8_owner,note`; an empty cell accepts the submitted value). `blind_finalize.py merge` applies the owner's overrides to a copy (`ratings-final.csv`), after which `blind_compare.py` reruns the comparison on the final ratings. Nothing edits the submitted ratings, the sheet, the key or any first-look result (tested). Until the confirmation file arrives, the comparison on record is the one on the submitted ratings.

## Taxonomy

Primary class per answer that was not fully correct (15 of 21; a secondary class in brackets). Classes: **retrieval** (the right evidence was not in front of the model), **source attribution** (a fact is tied to the wrong source or actor), **inference** (a claim the evidence does not make), **conflict handling** (sources disagree and the answer drops or hides one), **abstention** (should have said "I don't have that" and did not), **instruction contamination** (stored instruction text repeated or mislabelled), and **scope** (a correct answer padded with unrelated material).

| Primary class | Items | Pattern |
|---|---|---|
| **Inference** (4) | R01, R10 (Lantern's model taken from Harbor), R14 (invented "superseded") , R15 (Dana's follow-up assigned to the owner) | A property or role carried to a subject whose records do not carry it. R01/R10 also belong with abstention; R15 also misplaces responsibility and has a retrieval cause (the tasks were not retrieved). |
| **Retrieval** (3) | R02 (wrong meeting for an attached-meeting question), R19 (filler lines for a person question), R20 (filler lines for a status question) | Generic or structured questions answered from transcript filler. R19 and R20 are honest answers to the wrong evidence. |
| **Instruction contamination** (3) | R12 (distractor note pulled in), R16, R21 (planted text repeated and called a "system instruction") | R16 occurs with perfect evidence, so it is model behaviour, not retrieval. |
| **Source attribution** (1) | R05 | The 60-minute memory presented as the runbook, with the 30-minute runbook value dropped (conflict handling secondary). |
| **Conflict handling** (1) | R17 | 9 to 5 given, the conflicting 8 to 6 memory omitted. |
| **Abstention** (1) | R08 | No evidence at all; an invented approval period. |
| **Scope** (2) | R07, R09 | A correct answer mixed with unrelated facts (R07); a partial answer plus a negative claim about what was not done (R09, instruction contamination secondary). |

The six answers rated fully correct (R03, R04, R06, R11, R13, R18) were simple lookups, a correct abstention, a permitted sensitive answer, and an accurate report of a 30 against 60 minute conflict.

First-look rows where B1a or B1b was not fully correct, by class (automatic scoring, 15 rows over 11 cases): retrieval 8 (B-S4, B-C4, B-R2 and B-R3 for both, B-I3 for both, B-A1 for both counted by case), inference or abstention 2 (B-N4 for both), conflict handling or attribution 2 (B-T3 for B1a, B-T4 for B1b), scorer label strictness 1 (B-C1 for B1b). **Retrieval is the largest class in the automatic data; inference and contamination are the largest in the human data**, which is the point of the review: retrieval failures are visible to a scorer, the others are not.

## Where each class goes

| Class | Addressed by | Status |
|---|---|---|
| Retrieval of structured and broad queries | Deterministic routing of status and person questions to the authoritative stores | Built for tasks, reminders and person questions; evidence in the [answer-quality record](phase-44e-answer-quality-2026-10-11.md) |
| Source attribution, inference (subject and property), unsupported recency claims | Deterministic evidence checks | Prototype, small samples; same record |
| Conflict handling | Conflict-omission detector (v2, v3) | Experiment only, not a gate |
| Abstention | Restrict what is shown; fixed replies on restricted channels | Partly addressed |
| Instruction contamination | Evidence delimiting, the instruction label, and a contamination check | Following is bounded structurally; volunteering and mislabelling planted text is open |
| Scope, negative claims | Out of scope for now; negative claims are a Phase 44H design question | Open |
