# Phase 44: selective partial answering, development and acceptance protocol (PROPOSAL, 2026-10-12; Stage A built, nothing else implemented or deployed)

> **Stage A status (owner-approved 2026-10-12):** corpus, scorer, validation and the two protocols below are built; results are in [the Stage A record](verification/phase-44-selective-stage-a-2026-10-12.md). Sections 12 and 13 supersede sections 7 and 8 where they differ (ten owner criteria, sub-claim registry statuses including ORDER_UNSUPPORTED). No response policy exists. (2026-10-10: the scorer-based reading of criteria 1 and 7 to 9 is superseded by the deterministic measures of the [integration plan](phase-44-selective-answering-integration-plan.md); the ten criteria themselves and dev16's unfrozen status are unchanged. Absence semantics: rubric v5.)

Owner direction, 2026-10-12: *protocol design approved: answer the supported sub-claims while explicitly identifying unsupported or conflicting sub-claims; test mixed evidence, multi-part questions, conflicting records, unknown actors, negative claims and temporal/supersession assertions. Do not implement or deploy a partial-answering policy yet; return the protocol and acceptance criteria for review.* This page is that proposal. It changes no behaviour: the 7B is the default, the 44H boundary is active, indexing is `false`, retrieval and shadow are off, and C2 stays a calibrated annotation, never a hard-abstention gate.

## 1. Why this is the next question

The evidence so far says the 7B's dominant failures are no longer "answered something with nothing behind it" but **mixed** ones:
- dev12 and dev14-style two-part questions ("Who owns the Gantry scheduler, and what is its maximum message size?") are where both too much and too little help hurt. The frozen C1 fallback let the 7B keep the supported half (the owner) and say the other half is unknown, but also let it assert from related records. The deterministic UNESTABLISHED reply refused the whole question and cost +18 false abstentions. A blanket refusal discards the supported sub-claim; a blanket answer invents the unsupported one.
- Removing related records (the revised C1) is safe but also removes a supported partial fact ("scheduled jobs use the deep path" while the model for that path is not recorded). That is exactly a selective-answering case.
- Conflicts stay poor even with perfect evidence (3 of 10 on dev12): the model reports one side. Reporting both, with sources, is a sub-claim-level requirement.

The behaviour to measure is therefore **selective**: assert what the records establish, say what they do not, and show disagreement, in one reply.

## 2. Definitions

A **sub-claim** is one atomic assertion that a correct answer could contain, with a **gold status** from the fact registry:

| Status | Meaning | Correct reply behaviour |
|---|---|---|
| SUPPORTED | an authorised record states it | state it, tied to its source |
| UNSUPPORTED | no authorised record states it (never recorded, only recorded for a sibling, or only in an unauthorised record) | say it is not established; do not state or imply a value |
| CONFLICTED | two authorised records give different values | state both values with their sources; do not choose |
| HISTORICAL | recorded as past (archived, "as of March", retired) | state it as past; do not present it as current |
| NEGATIVE-SUPPORTED | a record states the absence or the opposite ("<subject> has no <X>", a different owner; a document that merely does not mention it is not enough, see the note below) | state the negative with its basis |
| NEGATIVE-UNSUPPORTED | absence would be an inference from silence ("Dana said nothing") | say the records shown do not establish it either way; do not assert the absence |

> **Absence semantics (2026-10-10, rubric v5).** NEGATIVE-UNSUPPORTED has two forms: a *scoped-search negative* (a record states what was searched; the reply may report that search with its scope, never world-level absence) and *unknown* (nothing in the records). Only NEGATIVE-SUPPORTED, an authoritative record stating the absence, permits "X has no Y". Definitions and rules: [Stage B design, section 3.1](phase-44-selective-stage-b-design.md#31-absence-semantics-rubric-v5-2026-10-10-evidence-contract).


A question has one or more sub-claims. A reply is judged per sub-claim, not as a block.

## 3. The reply contract under test

Plain text for the owner (voice rendering is out of scope here):
1. Supported sub-claims first, each with its source id.
2. A short statement of what is **not established**, naming the part ("the records do not say who approves Quartz security changes"), never a context-free refusal.
3. Conflicts shown as "X says A [E1]; Y says B [E2]", not resolved.
4. Past facts marked as past.
5. Nothing asserted without a source in the evidence shown; related-but-non-asserting records may be mentioned only as context.

## 4. Mechanisms to compare (each separable; none is implemented yet)

| Arm | What changes | Why it is in the comparison |
|---|---|---|
| **P0** baseline | B1a evidence, normal prompt | reference |
| **P1** contract prompt | adds the section 3 contract as an instruction; evidence unchanged | tests whether instruction alone makes a 7B selective |
| **P2** clause-scoped generation | the question is split into clauses (as C1 already does); each clause is answered by one generator call over **only that clause's asserting records** (and quarantined context), then the replies are concatenated in a fixed order; "not established" is **still said by the model**, informed by a hedged annotation | tests the cross-clause conflation hypothesis without a hard element |
| **P3** clause-scoped with template for unknown | as P2, but a clause whose C1 selection is empty is rendered by a template naming the part ("not established: <part>") | a deliberately harder arm, expected to be the conservative one; it can pass only if the guardrails hold, and C2's error rates make a pass unlikely; it is included because the owner asked to keep elements separable and measurable |
| **P4** P2 + C5-style span check | the generator also returns, for each sub-claim, the evidence id; a deterministic checker (source identity, authorization, span, relation, the C5 rules) drops claims it cannot verify and the reply says so | measures whether verification can be bolted onto selective answering without the JSON-generation cost seen in C4 (the generator is asked for ids only, not quotes; quote checking is done by code against the retrieved text) |

C1 (revised) and C2 (annotation) and C3 are inputs, switchable independently of P1 to P4. No arm uses a second free-text LLM verification pass.

## 5. Test families (each at least 25 acceptance cases)

1. **Mixed evidence** (supported + unsupported in one question): "Who owns the Ferry queue, and how big can a message be?"
2. **Multi-part questions** (2 to 3 clauses, different relations/subjects, some supported, some not): "When is the Cedar budget approved through, who leads Cedar, and who is on call?"
3. **Conflicting records** (two authorised sources, different values; with and without a third dated record that does not order them): both sides with sources.
4. **Unknown actors** ("Who approved...", "Who is assigned...", "Who attended..." where no record names the actor; or the actor is named only for a sibling project): do not name anyone.
5. **Negative claims** ("Is there a record that...", "Did X say...", "Does the document mention..."): NEGATIVE-SUPPORTED vs NEGATIVE-UNSUPPORTED separation; absence is claimed only when a record supports it.
6. **Temporal / supersession** (archived versions, "as of" memories, retired values; plus undated disagreements): past marked past; no invented ordering; no "newer" claim without a dated basis.

Cases are generated from a **sub-claim registry** extending the fact registry (every sub-claim has a status and its gold sources), so labels are never typed twice. The generator keeps the duplicate-fact validator introduced after dev12 (no two established facts for one subject and relation) and adds a check that each CONFLICTED sub-claim has exactly two sources and each NEGATIVE-SUPPORTED one has a stating record.

## 6. Scoring (deterministic, frozen before any design run)

Per sub-claim, from the reply text and registry-derived patterns:
- **SSR** supported-sub-claim recall: the supported value is stated (registry value patterns, alternatives for numerals and names).
- **USL** unsupported-sub-claim leak: a value for an UNSUPPORTED sub-claim is asserted (forbidden patterns derived from sibling values, and question-position-safe so that a correct "not established" that echoes the question's words is not counted, a defect seen on dev12).
- **EIR** explicit-identification rate: for each UNSUPPORTED or CONFLICTED sub-claim, the reply names the part as not established or shows both values (cue patterns plus the sub-claim's subject or relation word within one sentence).
- **CON** conflict handling: both values present and each tied to a source id.
- **HIS** history handling: a HISTORICAL value is not stated as current (no "is now", "currently" attached to it).
- **NEG** negative-claim handling: an absence is asserted only for NEGATIVE-SUPPORTED sub-claims.
- **BLK** blanket-refusal rate on questions that have at least one SUPPORTED sub-claim.
- **CIT** citations: every cited id exists in the turn and is authorised (code check); where P4 returns ids, the C5 identity/authorization/span/relation rules.
Unsupported material claims (the existing measure) remain reported for continuity. The scorer is written, unit-tested on hand-labelled replies, and frozen **before** the design set is run. A random sample of 30 replies is also available for the owner's read (not a pass/fail input), and the scorer's disagreements are listed beside the automatic scores, never used to alter them.

## 7. Data and process (same discipline as dev8 to dev14)

1. **Stage A, generator and scorer (no model).** Sub-claim registry, paraphrase banks written and hashed first (design bank, unseen bank), the scorer and its tests, the duplicate-gold validator. Freeze scorer and banks.
2. **Stage B, design set (dev15, at least 120 cases, at least 20 per family, design relations and projects, design bank).** Used to develop P1 to P4. All tuning happens here.
3. **Stage C, freeze.** Mechanisms, prompts, thresholds, scorer, cases and the reading hashed; acceptance set (dev16) authored from the **unseen bank, held-out relations and held-out projects** before Stage B results are read. Untouched, one run, guarded like dev8 to dev14.
4. **Stage D, one-shot acceptance** on the 7B with the registered arms plus the best previous candidate (revised C1 + C2 annotation) as a comparator.
5. **Stop.** Report; any integration is a separate owner decision.

Size guidance: at least 150 acceptance cases (at least 25 per family, at least 90 with at least one UNSUPPORTED or CONFLICTED sub-claim) so that a 30% relative reduction in USL from a baseline leak rate near 25% is detectable with paired tests; the number of discordant pairs is shown with every comparison.

## 8. Proposed acceptance criteria (for the owner to fix before Stage C)

A candidate arm must satisfy **all** of these on the acceptance set, judged against P0 on the same cases:
1. **USL:** strictly fewer unsupported sub-claims asserted than P0, and no family worse than P0.
2. **SSR:** supported-sub-claim recall no lower than P0 minus 1 case and minus 3 percentage points overall, and no family more than 5 percentage points lower (a selective policy that gains safety by dropping supported content fails).
3. **EIR:** at least 70% of UNSUPPORTED and CONFLICTED sub-claims explicitly identified (P0's rate reported next to it).
4. **CON:** both values with sources in at least as many conflict cases as P0, and at least 60% of them.
5. **BLK:** blanket refusals on questions with a supported sub-claim not above P0 plus 1 case.
6. **False abstention** on fully supported questions: no more than one additional case and three percentage points (as in the earlier guardrails).
7. **CIT:** zero accepted citations to a nonexistent or unauthorised source; where P4 applies, zero claims accepted that fail identity, authorization, span or relation.
8. **HIS and NEG:** no more invented current/ordering claims and no more asserted absences without a basis than P0.
9. **Latency:** median model-call plus preparation within 1.5 times P0 (P2 to P4 use one call per clause; the cost is reported, not hidden).
10. **Transparency:** all regressions and paired outcomes by case id; the original statistics reported; no significance claimed from post-hoc exclusions.

## 9. Out of scope

Voice rendering; any production wiring; C4's JSON generation (paused); the deterministic C2 reply as a gate (rejected); a second free-text LLM verifier; retrospective action claims ("Did you finish X?"), which stay with the receipt-backed Phase 44H work.

## 10. Risks and how the protocol handles them

- A 7B may ignore the contract (P1) or may mis-split clauses (P2 to P4): clause splitting is deterministic and tested; its error rate is reported as a component result before any end-to-end run.
- Template or checker elements may over-withhold: criteria 2, 5 and 6 are there to fail such an arm.
- "Unknown" phrasing may be mistaken by the scorer for refusal: BLK and EIR use sub-claim-level cues, with the dev12 echo defect designed out and listed disagreements.
- Over-fitting to the invented corpus: unseen bank, held-out relations and projects, hashed before design, one-shot acceptance.
- Author bias: the same author writes banks and lexicon; this is disclosed, and the owner's read of a sample is offered.

## 11. Decisions requested

1. Approve the sub-claim statuses and the reply contract (sections 2 and 3).
2. Approve arms P0 to P4 (or remove P3/P4).
3. Fix the acceptance numbers in section 8 (or amend them).
4. Approve building the sub-claim generator and scorer (Stage A) as the first step.

## 12. Stage A development-set protocol (dev15)

- **Data:** `cases_dev15.json` (173 questions, design relations and projects, design bank). Everything may be developed and tuned here: mechanisms, prompts, thresholds. Arms: B1a baseline with the 44H boundary, oracle (diagnostic ceiling, never a candidate), revised C1, C2 annotation and C3 each separately switchable, then any new mechanism the owner approves in Stage B.
- **Scorer:** `selective/scorer.py` is frozen once the fresh adjudication in the Stage A record, section 3, is done; until then it may change only to fix a documented defect, with the case added to `scorer_cases.py` and the change listed. Disagreements between the scorer and a reader are listed beside the automatic scores and never used to alter them.
- **Decision rules:** each candidate is reported against B1a on dev15 with paired outcomes by case id, discordant counts, Wilson or zero-event bounds, and criteria 1 to 10 from `evaluator.py`. dev15 results are design evidence; no claim is made from them.
- **No use of consumed sets:** dev8, dev10, dev12 and dev14 are never rerun or tuned against; dev16 and bank D are not run on a model during development.

## 13. Stage A one-shot acceptance protocol (dev16, NOT yet frozen)

- **Candidates:** `cases_dev16.json` (218 questions, held-out relations `release_day`, `escalation_contact`, `approver`, held-out projects juniper, pinnacle, thistle, umbra, unseen bank D with the disclosed amendment in the Stage A record, section 1). It is not frozen and no freeze manifest exists. It is frozen only after the owner approves the amendments below, the fresh scorer adjudication is done, and the mechanism, prompts and thresholds are fixed.
- **Freeze:** at that point a `dev16_freeze.json` manifest hashes the cases, bank files, scorer, evaluator, mechanism code and this section; `freeze_check.py` and a test cover it. One run only, guarded by a decision-point file, `AQ_DEV16_APPROVAL`, the manifest and a single run log (the dev8 to dev14 pattern). A failed or aborted run is not repeated without an owner decision.
- **Reading, fixed before the run:** the ten criteria in the Stage A record, section 5, in their amended operational forms; the registered pass rule is all ten; every failure is reported by case id; no post-hoc exclusions; the original statistics are reported even if a scorer disagreement is later documented.
- **Hold-out hygiene:** the candidate must not be read by any author before the freeze except by the generators; the tuned mechanism is chosen on dev15 only.

### Decisions requested

1. Approve or amend the operational forms of criteria 4, 6, 7, 8, 9 (record, section 6).
2. Approve enlarging the world for criteria 7 to 9, or the bound-reporting form.
3. Approve the date-semantics rule and the question-level definition of "fully correct".
4. Approve a fresh scorer adjudication (second rater welcome) before any freeze.
5. Decide whether to proceed to Stage B (mechanism design), noting that the oracle ceiling means filtering evidence alone cannot satisfy criteria 2 and 7, and that the design must separate discovery from admissible answer evidence.
