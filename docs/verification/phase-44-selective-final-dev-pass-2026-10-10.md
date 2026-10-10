# Phase 44: selective answering, final development pass before dev16 readiness, 2026-10-10

Status: development record. **No model was used. dev16 was not opened, frozen or run. Nothing is wired, deployed, indexed or committed.** Source is `services/companion-core/src/companion_core/knowledge/answerability_b1/` (imported by nothing in production). Preceding record: [I-2 follow-up](phase-44-selective-i2-followup-2026-10-10.md) (its figures are the "before" of this page and are unchanged). The updated acceptance-readiness report is [phase-44-dev16-deterministic-criteria-draft.md](../phase-44-dev16-deterministic-criteria-draft.md).

## 0. What was approved, and what was not done

Approved (owner, 2026-10-10): one bounded follow-up iteration with five parts: (1) rendering, with a regression re-review of the frozen 51-item sample and a small prospective sample; (2) explicit value transitions in evidence admission; (3) prospective definitions of `release_day`, `escalation_contact` and `approver`, frozen with hashes before acceptance; (4) acceptance readiness (P0 plan, blinded adjudication, reconciliation of all ten criteria); (5) verification with before/after dev15 results, remaining false abstentions, and pre-existing failures kept apart from new ones.

Not done, by instruction: no I-3 model-written layer, no production wiring, no deployment, no indexing, retrieval or shadow activation, no Phase 44F, no new scorer (scorer v3 stays research-only), **no dev16 freeze or run**, no push.

## 1. Headline (dev15, 173 questions, 307 sub-claims, no model)

| | before this pass | after |
|---|---|---|
| Question-text-only path (T-new): exact states | 280/307 (91.2%) | **294/307 (95.8%)** |
| questions fully correct | 147/173 | **160/173** |
| false abstentions | 27 | **13** |
| Gold-spec path (G-registry): exact states | 282/307 | **296/307** |
| Original baseline G-old (old subject list, old decomposition) | 267/307 | 267/307 (reproduced) |
| Unsupported claims, wrong values, spurious structures, citation errors, authorisation failures | 0 | **0** |
| Renamed world (86 names replaced): replies identical | 173/173 | 173/173 |
| Template purity (withheld / conflicted claims contain only fixed words) | 147/147 | 133/133 (new patterns, section 4.3) |
| Partial answers: supported part answered / withheld part right | 77/80, 80/80 | 79/82, 82/82 |

Held-out relation questions (labelled set, section 6): first contact 50/52 exact with 1 invented structure; 52/52 after one documented fix (tuned on its own set). Original 164-question set: unchanged, 154/164 (93.9%), 1 invented structure.

Manual review (single reader, NO INDEPENDENT HUMAN REVIEW), section 7: the 51 previously inspected items went from 31 to 50 "clear", from 9 to 2 "incomplete" and from 15 to 7 minor implications, with 0 wrong and 0 material before and after. The prospective sample (28 dev15 questions and 14 fresh probes) found one real defect, fixed.

What this is not: **the dev15 results are a design-set measurement, not an acceptance result**, and the ten-criterion dry run passing on dev15 is not an acceptance pass (section 9).

## 2. Independence, stated plainly

- **Single rater.** Every manual judgement here was made by the author of the pipeline. There is no independent reviewer and no agreement statistic.
- **dev15 is the design set.** The cue vocabulary of the registry was written after reading dev15 questions (disclosed in the earlier record) and this pass tuned wording on dev15 replies. dev15 numbers say nothing about unseen phrasings.
- **The invented corpus is shared with dev16.** Before the held-out question set was written, the author had incidentally printed three *record* sentence forms of the held-out relations while searching the shared corpus for something else ("Escalate serious `<project>` incidents to `<person>`.", "`<person>` approved the `<project>` release.", and the budget sentences "approved through `<month>`"). No release-day record sentence was seen. The definitions of the three relations are therefore not blind to the record surface of two of them. They are blind to dev16's cases, questions and phrasings (`cases_dev16.json` and bank D were not read, listed or hashed).
- **Names in the labelled sets are not in the corpus**, and the phrasings are the author's own, so they share the author's blind spots.
- The review sample, the probes and the held-out question set were each fixed by hash **before** the text they would be judged against was rendered or measured. One qualification: the author had printed the rendered text of the 13 false abstentions and 16 template-check misses before drawing the prospective sample; its strata use gold structure only (relations and statuses), never a reply.

## 3. What changed (all source uncommitted)

**Rendering** (`contract.py`, `registry.py`, `types.py`):

- A record's own relative-time wording is kept: *"The person on call for Vesper is Ines Duarte [E120] (the record says "this month")."* Closed list (this/next/last/current/previous plus week, month, quarter, year, sprint, weekend; today, tonight, tomorrow, yesterday). If supporting records differ (one says "this week", another nothing), the claim is withheld instead of stated plainly.
- A decision is reported as a decision: *"The records say the decision for Vesper was to keep Kestrel-9B as the default model [E245]. They do not say whether it has been carried out."* Previously: "The planning decision for Vesper is keep Kestrel-9B ...".
- Agreement and readability: "support hours **are**"; "Ines Duarte reviews Conduit settings"; "On the design review day for Osprey, the records give ..." (the doubled "for" is gone); "next time away for the Marlin lead" (was "next days off").
- **Question order is kept.** Parts appear in the order asked; only *adjacent* not-established parts share one line. (The earlier text moved answered parts first.)
- The "unclear" wording no longer blames the records for a reading limit: *"One record about the default model of Cedar is worded in a way I cannot read safely, so I have not answered it."*

**Explicit value transitions** (`transitions.py`, `admission.py`, `states.py`): section 4.

**Three relations defined** (`registry.py`): section 5.

**Tooling** (benchmarks, not production): `p0_adjudication.py` (blinded adjudication and conversion to evaluator inputs), `candidate_freeze.py`, `criteria_diagnostics.py`, `i2b_failures.py`, `review_sample_b.py`, `review_packet_b.py`, `transition_probes.py`, `decomposition_heldout_set.py`; `i2b_eval.py` gets its own purity patterns (`i2_eval.py`, which produced the preserved first-run report, is untouched).

## 4. Explicit value transitions

### 4.1 What is read

A closed grammar over one sentence, no model. Each value gets the status the sentence's own words give it:

| status | read from | counts as the current value? |
|---|---|---|
| configured | a plain present or undated statement ("is", "as of October ... is") | yes |
| deployed | "switched/moved/changed/migrated/upgraded ... to", "rolled out", "deployed", "went live", "from X to Y", "X replaces Y", "replaced X with Y" | yes |
| decided | "decision is to", "decided", "agreed", "resolved", "voted" | **no** (reported as a decision) |
| planned | "will switch/move/...", "plans to", "going to", "scheduled to" | **no** (reported as a plan) |
| retired | the tail "; the X model has been retired/removed/deprecated/..." or the old side of "from X to Y" / "X replaces Y" | no, never an answer |
| rolled back | the old side of "rolled back from X to Y"; the new side ("rolled back to Y") is deployed | old side no |

The motivating sentence, found 4 times in the design corpus: *"As of October, the Cedar default model is Swift-20B; the Merlin-2B model has been retired."* It used to be unreadable (two models) and, because it contains "retired", past as a whole. The head ("... is Swift-20B") is now read as the current value and the tail is kept as a retired value with its own status.

### 4.2 What is deliberately not inferred

- **A decision is not a deployment.** "So the decision is to keep Kestrel-9B as the default model" no longer answers "What is Vesper's default model?". The question is withheld and the decision is reported: *"The records do not say the default model of Vesper. A record says Kestrel-9B was decided on for the default model of Vesper, but the records do not say it is in place [E245]."* This note is added only when no current record states that value as configured or deployed, and never to a question about the past (a defect the prospective review found and fixed; section 7).
- **A retired value is not "the previous setting".** "The Merlin-2B model has been retired" does not say Merlin-2B *was* the Cedar default, so it is never history on its own. A history question is answered from a record dated to that period ("As of March, the Cedar default model was Merlin-2B").
- **No supersession from record timestamps.** Two disagreeing records stay CONFLICTED whatever their creation times.
- **A retirement statement never resolves a conflict**, whoever wrote it (owner, third party, attendee): it is admitted like any statement but only ever *withholds*. A single live value that another record says is retired is not stated (the records disagree about whether it is in use); two live values stay CONFLICTED, which already chooses nothing.
- **Authorization boundaries are unchanged.** An unauthorised, stale-authorised or instruction-bearing record contributes nothing, in either direction (it cannot retire a value or hold one up).
- **Ambiguous transitions are withheld**, not half read: hedged ("maybe ... has been retired"), several values in the head, a negated retirement ("has not been retired"), two retired models in one tail.

### 4.3 Regression cases (`tests/test_transitions_b1.py`, 65 tests; also `test_p0_adjudication.py` 16, `test_candidate_freeze.py` 3)

Positive: the transition sentence answers the current default and states no retired model; an earlier dated record still answers history next to it; a completed switch and a rollback each produce the current value; a configured value is answered and a *different* decision is added as a decision only; a decision equal to the configured value adds nothing; the decision relation reports the decision without saying it was carried out; a relative time is kept; plural agreement; question order; 12 record phrasings of the three new relations (in addition to the battery above). Negative: decision alone, plan alone, retired-in-another-record, retirement never resolving a conflict (three authors), unauthorised and stale records with no effect, instruction-bearing record excluded, five ambiguous transitions, record timestamps never ordering, past values never shown as current, a relative time present in only some records withholding the claim, and 6 record phrasings that must stay withheld.

## 5. The three relations, defined prospectively

Definitions (full data: `selective/relation_definitions_frozen.json`):

- **release_day** (subject: project; value: weekday): the weekday a project's *recurring* releases go out. Record cues are recurring forms only ("release day", "releases go out/ship/land/happen", "releases on/every", "ships on/every", "cuts a release", "is released on/every"). A one-off "was released on Friday" and an approval day are different propositions and are not read. A plural weekday ("on Thursdays") is the recurring form of the same day.
- **escalation_contact** (subject: project or system; value: person): the person incidents are escalated to. A first-person statement ("I will escalate X") never establishes it (the speaker is the one escalating); a sentence with two people ("A escalated the incident to B") is not read.
- **approver** (subject: project; value: person): the person who approves a **release**. The record cue needs "release" in the sentence, so a budget approval is not an approval of a release; a question that says "budget approver" is not typed as this relation. A first-person statement never establishes it.

Order of work: (1) a labelled question-structure set for the three relations (52 questions, 42 parts, 20 clauses that must be withheld) was written and frozen by hash (`HELDOUT_SET.sha256`); (2) the decomposer was measured on it **before the relations existed** (21/52 exact, 0 invented: they were withheld); (3) the relations were defined; (4) first contact **50/52, 1 invented** (a "when was the last Nimbus release?" typed as a recurring day) and 1 miss ("which person approved ..."); (5) one documented fix each, then 52/52 with 0 invented, **tuned on its own set**, so first contact is the honest figure. The original 164-question set still gives 154/164 and 1 invented structure.

Record side (the author's own battery, not dev16): of 24 phrasings tried, 22 are read; the 2 withheld are verb-after-subject forms that the existing qualified-object rule withholds ("Escalations for Cobalt go to ...", "Releases for Cobalt happen on ..."), a coverage limit and not an error. Four further phrasings (the past-tense one-off "was released on Friday", two hedges, a negated escalation) are withheld on purpose; all six withheld forms are tested as withheld.

Side effects of getting these to work, all general and all measured (dev15 unchanged where it should be): record-cue stems now treat "releases?" as "release"; relative-time words after a subject ("on call for Sable **next** month") no longer make it a qualified object; verbs of change directly after a subject ("Cedar switched its default model") are read as verbs; plural weekdays are weekdays in the entity grammar.

**Freeze.** `CANDIDATE_FREEZE_2026-10-10.sha256` hashes the registry, the question decomposer, the transition reader, admission, states, contract, types, the evaluator, the deterministic criteria, the P0 tooling, the labelled sets with their own freezes, the review samples, the probes, the shared corpus file, `cases_dev15.json`, and `relation_definitions_frozen.json` (all 24 relations as data). `candidate_freeze.py --check` and `tests/test_candidate_freeze.py` fail if anything changes without a new, named freeze. **dev16 and bank D are not listed, opened or hashed.**

**Acceptance population.** Unchanged: nothing is excluded, re-labelled or re-weighted. Coverage consequence, disclosed: the held-out *relations* are no longer held out for this path (the held-out projects and unseen bank D phrasings still are).

## 6. dev15 results and what remains

Arms (each differs from the next in exactly one thing; the recorded first-run numbers are preserved in `results/i2-dev15-report.json`):

| arm | what it uses | exact states | fully correct | false abstention | not typed |
|---|---|---|---|---|---|
| G-old | gold subject list, old decomposition | 267/307 | 137/173 | 40 | 0 |
| G-registry | gold-spec structure, typed registry | 296/307 | 162/173 | 11 | 0 |
| T-old | question text, old decomposition | 145/307 | 48/173 | 89 | 160 |
| **T-new** | question text, typed registry, deterministic decomposer | **294/307** | **160/173** | **13** | 2 |
| T-renamed | T-new with 86 names replaced by unseen ones | 294/307 | replies identical 173/173 | 13 | 2 |

All arms: 0 unsupported claims, 0 wrong values, 0 spurious structures, 0 citation errors, 0 authorisation failures. Revocation test: of 172 claims whose supporting record was revoked, 158 are withheld and 14 are still answered **from a different authorised record** (none cites the revoked one; stale authorisation behaves the same).

**The 13 remaining false abstentions** (`results/i2b-dev15-failures.md`; before this pass: 27):

| cause | n | what it is |
|---|---|---|
| decision, not in effect | 7 | the only record stating the default model is a meeting decision ("the decision is to keep X as the default model"). The gold counts it as the default model; under this pass's rule (a decision is not a deployment) it is withheld and the decision is reported. **A deliberate cost of the rule, 2.3% of the atoms** |
| no admitted record | 4 | two documents say "serves X" and never "default" (Sable, Willow); one vendor, Quarry Data, whose document is excluded as instruction-bearing (two atoms) |
| not typed | 2 | "What was decided about X's default model" has two relation cues (decision and default model); the decomposer withholds it |

The 14 false abstentions that disappeared: the 21 "new value; old retired" cases are now read (the prior largest cause), partly offset by the 7 decision-only cases that are now withheld on purpose.

## 7. Manual review (single reader, NO INDEPENDENT HUMAN REVIEW)

Rubric unchanged (readability 3/2/1, semantics C/P/W, implication N/M/X), written before reading. Data: `results/i2b-manual-review-b.json`.

| set | n | readability 3 / 2 | semantics C / P / W | implication N / M / X |
|---|---|---|---|---|
| **Regression: the 51 previously inspected items, before** | 51 | 31 / 20 | 42 / 9 / 0 | 36 / 15 / 0 |
| **Regression, after this pass** (30 replies changed, 21 identical; the 9 existence-sweep renderings are byte-identical) | 51 | **50 / 1** | **49 / 2 / 0** | **44 / 7 / 0** |
| **Prospective** dev15 sample (28, new, frozen before reading) | 28 | 28 / 0 | 22 / 6 / 0 | 23 / 5 / 0 |
| Fresh probes (14, hash-frozen before rendering) | 14 | 13 / 1 | 14 / 0 / 0 | 11 / 3 / 0 |

The regression set is **previously inspected development material**; its improvement shows the known defects were fixed, not that unseen text reads well. The 6 "incomplete" prospective replies are the cases of section 6: 1 from the decision rule, 5 from coverage (2 "serves, never default", 2 Quarry Data, 1 untyped decision clause). The 5 "minor" prospective implications and most of the 7 regression ones are one cause: **"this month" stays unanchored**. The record says "this month" and carries no date, so the reply can only quote it; a reader may still take it as the current month. The 3 probe "minor" implications are the same (and a past-tense completed switch, "was switched to Lynx-7B", is stated as the current value, as any undated statement is).

**Defect found by the prospective review.** On first render, two historical answers (Cedar, Osprey) added "A record says Swift-20B was decided on ... but the records do not say it is in place", which is false there: another record says *"As of October, the Cedar default model is Swift-20B"*. The note is now dropped when any current record states the value as configured or deployed, and is never attached to a question about the past. Covered by two tests; the packet was rebuilt and re-read. Evidence that the review is not decorative; it is also evidence of what a single reader cannot rule out.

## 8. Criteria on dev15 (unchanged evaluator v3) and where they sit

Exact dry run (`deterministic_criteria.py`): all ten pass on dev15, **which is not an acceptance result**. Two figures sit on a threshold:

- **Criterion 4**: 26/30 mixed questions fully correct, which is **exactly the minimum** for a 70% one-sided lower bound. The four failures: 1 decision-only (design rule), 1 untyped decision clause, 1 "serves, never default" document, and 1 **correct answer whose citation the mechanical check rejects** (below).
- **Criterion 6**: 183/191 cited claims supported (95.8%), 0.8 points above the line. **All 8 misses are one class**: the claim cites a memory whose own sentence states the default model (e.g. `memory:m100`, "As of October, the Cedar default model is Swift-20B ..."), while the case registers only the architecture document. The claim is true and its citation does contain it; the evaluator's claim-level check is by *registered* source, so it counts them as unsupported. A person would almost certainly pass them. This class did not exist before this pass (those atoms were withheld); it can recur in dev16, whose corpus is shared. See the readiness report, decision 4.

Diagnostics: `results/i2b-dev15-criteria-diagnostics.md`. The previous dry run is preserved as `results/i2b-dev16-readiness-dry-run-dev15.before-final-pass.json`.

## 9. Tests and verification

- Companion-core: **1,633 passed, 77 skipped, 2 failed.** The two failures are the known pre-existing ones, both needing a database (`test_knowledge_index::test_reconcile_repairs_a_missing_stale_orphaned_and_expired_index` and `test_knowledge_retrieval::test_historical_mode_reaches_the_prefilter_and_revalidation`); they failed identically on a clean tree before this work. The intermittent `test_knowledge_index` contention-tool tests did not fail in this run. **No new failure.** Previous run: 1,542 passed, so 91 tests were added (transitions 65 including parametrised cases, P0 tooling 16, freeze 3, plus extensions to the registry and question tests, less the replaced held-out tests). In the two committed suites 4 tests were updated, because they pinned the old "unclear" wording and the answers-first order that this pass changed on purpose; in the previous iteration's tests the "relations are held out" tests were replaced by tests of the definitions and of what stays withheld. None was loosened to make it pass.
- B-1 suites together: 490 passed, 1 skipped.
- `ruff check .` from the repository root passes.
- Unchanged and verified: the first-run reports (`i2-dev15-*`, `i2-existence-sweep.json`), the dev8/10/12/14 freezes, the scorer seals, `selective/acceptance/`, `cases_dev16.json`, the earlier decomposition and review freezes.
- Not exercised: any real database, process, image or API. Everything here is in-process and offline.

## 10. Decisions for the owner

See the [readiness report](../phase-44-dev16-deterministic-criteria-draft.md#8-decisions-requested). In short: (1) the decision-versus-default rule and its 2.3% cost; (2) how criterion 6 treats a true citation to an unregistered record; (3) approve the P0 plan, the second rater and the agreement rule; (4) approve the freeze list and whether to freeze dev16; (5) commit/push.

## 11. Files

New source: `transitions.py`. Edited source: `admission.py`, `states.py`, `contract.py`, `registry.py`, `types.py` (all `answerability_b1`). New tests: `tests/test_transitions_b1.py`, `tests/test_p0_adjudication.py`, `tests/test_candidate_freeze.py`; extended: `test_registry_b1.py`, `test_questions_b1.py`, `test_answerability_b1.py`, `test_answerability_scoped.py`. Benchmarks (`benchmarks/answer_quality/selective/`): see section 3, plus freezes `HELDOUT_SET.sha256`, `REVIEW_SAMPLE_B_FREEZE.sha256`, `TRANSITION_PROBES.sha256`, `CANDIDATE_FREEZE_2026-10-10.sha256` and `relation_definitions_frozen.json`. Results (`results/`): `i2b-dev15-report.json` and `-replies-*.jsonl` (after), the same with `.before-final-pass` (before), `i2b-dev15-failures.md`, `i2b-dev15-criteria-diagnostics.md`, `i2b-manual-review-b.json`, `i2b-review-packet-b.txt`, `i2b-review-regression-51.txt`, `i2b-review-b-probe-check.json`, `decomp-heldout-*.json`, `decomp-dev-final.json`, `p0-adjudication-dryrun-dev15/` (blinded packet, empty label template, sealed key; nothing labelled).
