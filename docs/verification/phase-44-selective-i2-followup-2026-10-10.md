# Phase 44: selective answering, I-2 follow-up (typed entity registry, question decomposition, repeat of the offline evaluation), 2026-10-10

Builds on the [I-1/I-2 record](phase-44-selective-i1-i2-2026-10-10.md), whose next-step list this answers. Contract: [Stage B design 3.1](../phase-44-selective-stage-b-design.md#31-absence-semantics-rubric-v5-2026-10-10-evidence-contract); plan: [integration plan](../phase-44-selective-answering-integration-plan.md). Acceptance readiness: [deterministic criteria draft](../phase-44-dev16-deterministic-criteria-draft.md).

> **Superseded in part (same day):** the figures on this page are the state *before* the [final development pass](phase-44-selective-final-dev-pass-2026-10-10.md), which fixed the rendering defects listed in section 6, read the "new value; old value retired" sentence, defined the three held-out relations and updated every dev15 number (T-new 294/307, 160/173 fully correct). They are unchanged here as the "before"; open decisions (a), (b) and (d) of section 8 were taken up there.

## 0. What was approved, and what was not done

Owner approval, 2026-10-10: a bounded development iteration on (1) a typed entity registry and a relation specification that do not derive from the dev15/dev16 gold, fixing the model-name/known-subject collision with regression tests, no LLM; (2) question-side decomposition with a labelled set, withholding any subclaim it cannot type; (3) a repeat of the offline I-2 as two separate evaluations (gold-spec and question-text-only) with a before/after comparison and the failures; (4) a manual review of a sample frozen before the new replies were read; (5) a draft of deterministic dev16 criteria. Boundaries: I-3 deferred, no new scorer, no model-based decomposition, no production wiring, no retrieval/index/shadow, no Phase 44F, frozen artifacts preserved, no push or deploy.

**Not done, by design:** no model was called; dev16, `cases_dev16.json` and the bank D phrasings were not opened (`banks.py` was not read); nothing is imported by any production path; no database change; **nothing was committed or pushed**. Frozen artifacts are byte-identical to HEAD (`git diff HEAD` shows only the four B-1 source files below; the dev8/10/12/14 freezes, the scorer-v1 seal, the scorer-v3 acceptance and the val17 manifests verify).

## 1. Headline

| | Before (first I-2 run) | After |
|---|---|---|
| **Gold-spec**: exact states / questions fully correct | 267/307 (87.0%) / 137 of 173 | **282/307 (91.9%) / 149 of 173** (gold-independent registry specs: the same 282) |
| Gold-spec false abstentions | 40 of 178 | **25** (all admission limits, section 5.3) |
| **Question-text-only**: exact states / questions fully correct | 145/307 (47.2%) / 48 of 173 | **280/307 (91.2%) / 147 of 173** |
| Question-text-only: questions with an untyped (withheld) clause | 124 of 173 (160 clauses) | **2 of 173** |
| Unsupported claims, wrong values, citation errors, authorization failures, spurious structures | 0 / 0 / 0 / 0 / 0 | **0 / 0 / 0 / 0 / 0** |
| Same questions after every project, system, model, vendor and person name is replaced by an unseen one | not measured | replies **identical on 173 of 173** |
| Question-structure decomposer on the labelled set (164 questions) | n/a | **93.9% exact after one tuning pass (79.3% at first contact); 1 invented structure (a label ambiguity)** |
| Manual review (51 replies, one reader) | n/a | semantics **0 wrong**, 9 incomplete; readability 20 of 51 awkward; 15 minor implications, 0 material |

dev15 is a design set and its question phrasing was seen while the cues were written (section 2): these are development figures, not an acceptance result and not evidence of unseen-phrasing performance. **Not ready for formal acceptance**; see section 8.

## 2. Independence, stated plainly

**Independent of the gold:** the entity types, the relation definitions (subject types, value types, record cues, question cues, labels), the competing-subject policy and the decomposer read no dev15/dev16 atom, `cue_re`, `subject_re`, status or display; a test asserts the two new modules import nothing from the benchmark and name none of its data files. The old harness derived all of those from the gold atoms.

**Not independent, and why it matters:**
- The corpus text is shared with dev16 (same corpus v4), and the author had read the corpus generator. The registry's *record* cues were written from English semantics but with that knowledge. dev16 therefore tests held-out relations, held-out projects and unseen question phrasing, not unseen record phrasing.
- The author read a sample of dev15 questions before writing the question cues. dev15's text-only result is thus not an independent measure of phrasing generalisation. The labelled set was written after that, with fresh names and the author's own paraphrases; it shares the author's blind spots (about a third of it is deliberately hard or out of scope).
- Held-out relations (`release_day`, `escalation_contact`, `approver`) are **not defined**, so they stay held out: 13 near-miss phrasings of them written for a test are all withheld, none typed as a neighbour.
- Everything here was rated or read by one reader, the author of the pipeline: **NO INDEPENDENT HUMAN REVIEW**, no inter-rater agreement, no claim of independently validated detection.

## 3. What was built (source only; imported by nothing in production)

| Piece | Behaviour |
|---|---|
| `registry.py`: typed **entities by form** | model `Name-<n>B`; system = capitalised name + optional modifier + an infrastructure noun (queue, scheduler, gateway, service, cache, API, stream, store, dashboard, builder, index, database, pipeline, worker, broker, proxy, registry); host `<class> host`; meeting `<Name> [planning] meeting`; two or three capitalised words = person **or** vendor until a relation's slot decides; a bare capitalised word = project. Closed-class sentence openers (wh-words, auxiliaries, prepositions, articles) are never names. **Longest span wins** an overlap. Explicit typed entries may be added (`with_entries`); they also let a lower-case spelling be recognised. `harvest` builds the entity inventory of a record pool by grammar alone and ignores headings and sentence-opening words |
| `registry.py`: **relations** | 21 definitions: subject types, value kind, entity types that are its values, types that may share the subject's sentence, record cues, question cues, answer types, labels. Held-out relations are absent |
| Competing subjects, **typed** | `competitors(relation, own aliases, pool)`: an entity competes unless it is a value type or a sharing type of the relation. A model is a value of `default_model` and `decision` (never competing there) and the subject of `runs_on` (other models compete, a sharing project does not). A sentence that really names two projects stays ambiguous |
| `questions.py`: **decomposer** | clause split (`;`, `,`, `and`/`or`, `as well as`, sentence ends); polite openers removed; per clause: pronouns, wh-word answer types, time (any / current / past, a named month `in`/`before`/`as of`), ask (value / existence / ordering), subject by type, relation by cues with longest-phrase dominance and a role-holder rule ("the Harbor lead … away" asks about the lead's days off); a bare second subject or second relation continues its neighbour. **Withheld with a reason** when: pronoun, no relation cue, ambiguous relation, subject of the wrong type, ambiguous subject, a candidate value in the question, answer-type mismatch, existence mismatch, an unsupported period (year, "last week", "after March"), an unsupported qualifier (a weekday), a weak ordering cue ("latest"), conflicting time cues, "why" |
| `contract.py`, `states.py`, `types.py` | an untyped clause renders the fixed sentence "I could not work out one part of the question, so I have not answered it." (several are merged into one line), which says nothing about the records; `Component.period` and a **period filter**: a named month answers only from a past record whose own sentence is dated to it ("in M"/"as of M" names M; "before M" names only earlier months; a year or no month never matches); `build_plan` accepts a per-component competitor function |
| `admission.py` (one line) | **a defect found by this work:** `_qualified_object` extracted relation stems with `[A-Za-z]{3,}` over the cue regex, so `\bdesign reviews?\b` gave the stem `bdesign` and the word "design" made "Quartz design reviews are on Tuesday" look like a sentence about a qualified object. Escapes are now stripped first. All 155 earlier B-1 tests pass and the recorded 267/307 is unchanged |

**Tests added: 116** (`test_registry_b1.py` 26, `test_questions_b1.py` 80, `test_deterministic_criteria.py` 10). The model-name collision has regression tests in both directions: the two previously recovered answers (a meeting decision naming a model; a past default model) are answered with typed competitors and withheld with the flat list; a sentence naming two projects, and two models in a `runs_on` sentence, stay ambiguous.

## 4. Question-side decomposition

**Labelled set** (`selective/decomposition_dev_set.json`, 164 questions, 160 labelled parts, 40 clauses that must be withheld; authored and hash-frozen before the registry or decomposer existed; 14 marked hard on purpose; no whole question shared with dev15, 11 contain a plain clause that coincides with a dev15 clause). Scored: subject, relation, ask, time scope, stated month, answer kind and the number of sub-claims. The safety figure is **invented structures** (a typed component that is not a labelled part); misses are only withheld parts.

| | First contact | After one documented tuning pass |
|---|---|---|
| Exact structure | 130/164 (79.3%) | **154/164 (93.9%)** |
| Labelled parts found exactly / missed | 132 / 28 | **150 / 10** |
| **Invented structures** | **16 in 16 questions (13 temporal)** | **1** |
| Sub-claim count right | 161/164 | 161/164 |
| Of the located parts: ask / scope / stated month / answer kind | | 150 / 150 / 150 / 150 of 150 |
| Subject found / relation found | | 151 / 150 of 160 |

The tuning pass fixed general defects only, found by the first run: the time-qualification code returned an empty string when no period was present (so every past/current cue and every number in the question was silently ignored: this caused the 13 invented temporal structures); sentence-opening prepositions ("On which day…", "By when…") were read as project names; "do I have to roll back" was read as an existence question; "Could you tell me Harbor's default model" was not recognised as a question. No rule mentions an entity or a dev15 question. After it, the labelled set is development data.

By category after tuning (exact / questions): single 55/55, unseen names 12/12, partial 7/7, temporal 17/18, ordering 5/6, coordination 21/23, existence 3/4, uncertain-by-design 26/27, phrasing 8/12. **All 10 non-exact items:** 8 are marked hard (lower-case spellings without a registered entry; "Whose is the Prism dashboard?"; "the biggest message"; two subjects before one relation; a subject that follows the second clause; "Which is newer, A or B"), one is a count difference only (L089: two clauses withheld where one was labelled), and **one is a label ambiguity, not a decomposer fault** (L152 "Who is on call for Harbor and Lantern together?": the decomposer answers the Harbor half and withholds the rest; the label said withhold all). Per the freeze, the label stays; it counts as the one invented structure.

**On dev15's question text** (173 questions, 307 sub-claims): the old decomposer typed 147 sub-claims and withheld 160 clauses (124 questions); the new one types **305 of 307**, withholds 2 clauses ("What was decided about X's default model" matches both `decision` and `default_model`, so it is ambiguous), and produces **0 spurious components and 0 ask/scope mismatches**. This is partly a consequence of the cue vocabulary having been written after reading dev15 questions (section 2).

## 5. The repeat of I-2 on dev15 (`i2b_eval.py`; no model)

Two separate evaluations on the same 173 questions and 307 sub-claims. **Gold-spec** takes the sub-claim structure from the gold (subject, relation, ask, scope) and isolates evidence admission and rendering. **Question-text-only** is the real end-to-end deterministic path: question text, decomposer, registry specs, pipeline; the gold is read only to score. A text arm aligns each gold sub-claim to the component with the same subject and relation: no component means NOT_TYPED, a component with no gold sub-claim is spurious.

### 5.1 Results

| Arm | Exact states | By gold status (exact / n) | Fully correct Q | False abstentions | Not typed | Unsupported | Wrong values | Spurious | Citation errors | Authorization |
|---|---|---|---|---|---|---|---|---|---|---|
| **Gold-spec** G-old (the first run's specs and known list) | 267 (87.0%) | UNS 88/88, CONF 19/19, NEG 7/7 + 6/6, ORD 9/9, SUP 127/154, HIST 11/24 | 137 | 40 | 0 | 0 | 0 | 0 | 0 | 0 |
| G-typed (only the collision fixed) | 282 (91.9%) | same, SUP 142/154 | 149 | 25 | 0 | 0 | 0 | 0 | 0 | 0 |
| **G-registry** (registry specs, labels, competitors) | 282 (91.9%) | same as G-typed | 149 | 25 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Text-only** T-old (first run's decomposer and specs) | 145 (47.2%) | SUP 89/154 (63 not typed), UNS 34/88 (54 not typed), HIST 0/24, CONF 9/19, ORD 0/9 | 48 | 89 (87 not typed) | 160 | 0 | 0 | 0 | 0 | 0 |
| T-grammar (entities by grammar alone) | 280 (91.2%) | SUP 140/154 (2 not typed), UNS 88/88, CONF 19/19, NEG 13/13, ORD 9/9, HIST 11/24 | 147 | 27 (25 evidence, 2 not typed) | 2 | 0 | 0 | 0 | 0 | 0 |
| **T-new** (grammar plus entities learned from the record pool) | 280 (91.2%) | identical to T-grammar | 147 | 27 | 2 | 0 | 0 | 0 | 0 | 0 |
| T-renamed (86 names replaced by unseen ones, same sentences) | 280 | identical | 147 | 27 | 2 | 0 | 0 | 0 | 0 | 0 |

- **Unseen names:** T-renamed gives the same state and the byte-identical reply (after mapping the names) for **173 of 173** questions. The decomposer and the typed competitors therefore carry no knowledge of the invented names. Learning entities from the pool changes nothing on dev15; it matters for lower-case spellings (unit-tested).
- **Template purity:** 147 of 147 withheld, conflict, negative and ordering sentences match their fixed templates; the not-understood sentence is exact and carries no value or citation in 2 of 2.
- **Partial answers** (multi-part questions with an answerable and a withheld part): T-new answers the supported part in **77 of 80** and withholds the other parts correctly in **80 of 80** (G-old: 69 of 73).
- **Authorization:** 0 admitted or cited from an unauthorised record. Revocation test (the records a claim cites are revoked, and separately made stale, and the whole plan is rebuilt): T-new, 158 claims × 2 modes: 152 withheld (all plain templates), 6 re-supported by *another* authorised record, **0 still cite a revoked record**; G-registry 160: 154 / 6 / 0.
- **Citations:** 0 unknown evidence ids, 0 missing, 0 answered claims without one, 0 cited ids absent from the reply text, 0 cited records that do not contain the value. Reply size: median 22 words, 90th percentile 35, maximum 40; median 1 citation.

### 5.2 How the numbers moved (the runs, in order)

| Run | G-registry / T-grammar / T-new exact | What it showed |
|---|---|---|
| First run of the new path | 220 / 220 / 185 | Two defects of this work, not of the labels: `harvest` read document **headings** ("Overview", "Jobs", "Deploy") as entities, flooding the competing-subject list; and an explicit entry ("Sluice") beat the longer system name ("Sluice cache") because explicit entries were tried first |
| Longest-span recognition and a heading-free inventory | 272 / 270 / 270 | The 10 conflicting design-review days were still lost |
| Stem fix in admission (above) | **282 / 280 / 280** | Final |

(In that first run the G-typed arm's 221 was a harness error, a wrong alignment key for history and ordering atoms; it was corrected in the next run and is not a result.) None of the three fixes mentions a dev15 question or entity.

### 5.3 The failures, not only the aggregate (full list: `results/i2b-dev15-failures.md`)

All **27** remaining false abstentions (25 evidence, 2 not typed), in T-new:

| Count | Relation | Gold | Cause |
|---|---|---|---|
| 13 | default model, past | HISTORICAL | **ambiguity by design**: a memory says "As of October, the P default model is NEW; the OLD model has been retired" (two models in one sentence), so the single-valued answer is withheld as "unclear" |
| 10 | default model | SUPPORTED | the same memory (8); the document states the model with "serves" and never "default" (2) |
| 2 | support hours | SUPPORTED | one vendor asked about twice: its document carries an injected instruction and is excluded as instruction-bearing, by design |
| 2 | decision | SUPPORTED | not typed: "What was decided about Cedar's default model" fits both `decision` and `default_model` |

Every remaining failure is therefore a deliberate admission limit (21 of 25 evidence cases are one record shape) or an unresolved relation ambiguity. Zero are wrong answers. The other 280 states match the gold exactly. **HISTORICAL is the weak status: 11 of 24.**

## 6. Manual review (single reader: NO INDEPENDENT HUMAN REVIEW)

**Sample frozen first:** `selective/review_sample_frozen.json` (hashes in `REVIEW_SAMPLE_FREEZE.sha256`, verified before every run and by a test) was drawn, seeded and stratified, before any reply of the new path was rendered. Inputs were only the dev15 gold structure and the *old* committed replies (to find the "unclear" ambiguity replies). 42 dev15 questions: supported 4, partial 8, conflicted 5, historical 5, ordering 3, negative 4, ambiguous 5, abstained 4, unconstrained 4; plus 9 corpus-v5 existence facts (6 scoped-search negatives, 1 explicit absence, 1 source disagreement, 1 unauthorised-only). The gold-spec and text-only replies were **identical for all 42**, so each was rated once. Rubric written before reading (`review_packet.py`); every reply was read beside the text of the records it cites. Ratings: `results/i2b-manual-review.json`.

| Dimension | Result (51 replies) | By stratum |
|---|---|---|
| **Readability** (3 clear, 2 stilted, 1 confusing) | 3: 31, 2: 20, 1: 0 | clear in all negatives and 5 of 6 scoped-search negatives; stilted in all 5 ambiguous and all 3 ordering replies |
| **Semantic correctness** (C correct, P right but incomplete, W wrong) | C: 42, P: 9, **W: 0** | all 9 P are historical "unclear" replies (a supported-in-gold part withheld); supported, partial, conflicted, negative, ordering and abstained replies are all C |
| **Unsupported implication** (N none, M minor, X material) | N: 36, M: 15, **X: 0** | M: 9 "unclear" replies, 5 on-call replies, 1 decision reply |

What the review found, none of it visible in the mechanical counts:
1. **The "unclear" reply blames the records for a limit of the reader.** "The records on the default model of Cedar are unclear" is said when a record states both values in one sentence. It is a minor implication and an unhelpful answer; 9 of 9 incomplete replies.
2. **A relative time is dropped.** The note says "Dmitri Volkov is on call for Willow this month"; the reply says "The person on call for Willow is Dmitri Volkov". Five of 51 replies. This is the one finding that could mislead (a stale on-call answer), and it is not a rendering nicety.
3. **A decision is restated as a fact.** "The decision is to keep X as the default model" becomes "The default model of Tamarind is X" (the same pattern as the seven claims that make criterion 6 unfaithful in the [draft](../phase-44-dev16-deterministic-criteria-draft.md)).
4. **Wording:** "The weekday support hours of Ironside Backup is 9 to 7" (agreement), "The planning decision for Osprey is keep Swift-6B …", "The review assigned to Kavya Menon is Turret settings" (no article), "for the design review day for Osprey" (double "for"), answered parts placed before withheld ones so the order differs from the question, and a standup "10" with no unit.
5. The scoped-search negatives read well: the quoted scope, what was not searched, and "That does not show there is none."; the unauthorised-only reply is indistinguishable from silence, as designed.

Nothing was changed in response, so that the frozen sample and the replies it describes stay one-to-one. These are the natural content of a rendering follow-up, which would re-review the same sample.

## 7. Tests and verification

- **New and affected suites:** `test_registry_b1.py`, `test_questions_b1.py`, `test_deterministic_criteria.py` (116 tests) and the 155 earlier B-1 tests: all pass. Ruff passes on the whole repository.
- **Whole companion-core suite, final run:** 1,542 passed, 77 skipped, **2 failed**, both pre-existing: `test_knowledge_index` reconcile and `test_knowledge_retrieval` historical mode (both fail on a clean tree; they need a database; as already recorded). Across four full runs the count of failures was 4, 3, 3 and 2: the extras were the `test_knowledge_index` **contention-tool tests, which are intermittent** (a different one failed in each run; they also fail intermittently on the clean HEAD, checked in a temporary worktree that was removed; they pass in isolation). They exercise stub servers and are unrelated to this work. No new failure.
- **Frozen artifacts:** unchanged (section 0). The first-run reports (`i2-dev15-report.json`, `i2-dev15-replies.jsonl`, `i2-existence-sweep.json`) are not modified; this work writes `i2b-*` and `decomp-*` files beside them.

## 8. Readiness and what the owner should decide

**Recommendation: keep the deterministic path as the primary release candidate; it is still not ready for formal acceptance.** On dev15 it makes no unsupported claim, no wrong value, no spurious structure and no citation or authorization error, its text-only path reaches the gold-spec path's 280 of 282, and its names carry over to unseen ones unchanged. What stands between it and acceptance is not the model question but four things in this record:
1. **Unseen phrasing is unmeasured.** Only dev16 can measure it, and its fallback rate is unknown (draft, section 4).
2. **HISTORICAL answers 11 of 24 and one record shape causes 21 of the 25 evidence abstentions.** A narrow admission extension (a sentence that states the new value and says another is "retired") would recover most of them; it is B-1 admission work this iteration was not scoped for.
3. **Rendering defects found by the review**, above all the dropped "this month" and the decision-as-fact upgrade.
4. **Baseline-relative criteria cannot be run** without a P0 arm and an adjudication of its free-text replies, and the three held-out relations are withheld by design (draft, section 4).

Decisions requested: (a) approve a bounded rendering follow-up (agreement, decision phrase, articles, question order, keeping a record's own relative time or withholding such a record) with a re-review of the frozen sample; (b) whether to extend admission for the "new value; old value retired" sentence; (c) whether recorded decisions count as the default model; (d) held-out relations: define them now and freeze the definitions before dev16, or keep them held out and report that slice separately; (e) the P0 baseline plan and a second reviewer; (f) I-3 stays deferred: nothing found here needs a model.

## 9. Files

Source: `knowledge/answerability_b1/{registry,questions}.py` (new), `admission.py`, `contract.py`, `states.py`, `types.py` (edited). Benchmark: `selective/{decomposition_set,decomp_eval,i2b_eval,review_sample,review_packet,deterministic_criteria}.py`, `decomposition_dev_set.json`, `review_sample_frozen.json`, `DECOMPOSITION_SET.sha256`, `REVIEW_SAMPLE_FREEZE.sha256`. Results (`results/`): `decomp-dev-first-contact.json`, `decomp-dev-after-tuning.json`, `i2b-dev15-report.json`, `i2b-dev15-replies-{G-old,G-typed,G-registry,T-old,T-grammar,T-new,T-renamed}.jsonl`, `i2b-dev15-failures.md`, `i2b-review-packet.txt`, `i2b-review-packet-sweep.txt`, `i2b-manual-review.json`, `i2b-dev16-readiness-dry-run-dev15.json`. Tests: `test_registry_b1.py`, `test_questions_b1.py`, `test_deterministic_criteria.py`.
