# Phase 44: groundedness milestone, evidence selection and answerability (DESIGN ONLY, 2026-10-12)

Status: **design for owner review. Nothing here is implemented, scheduled or deployed.** Production is unchanged: the 7B is the default model, the 44H unclaimed-action boundary is active, indexing is `false`, retrieval and shadow are off, Phase 44F is unimplemented. Requested by the owner on 2026-10-12 after the dev10 negative result ([record](verification/phase-44e-section-coverage-2026-10-12.md)).

## 1. Why this milestone, and what the evidence says

| Evidence | Reading |
|---|---|
| dev10 (untouched, 41 cases, 7B): B1a baseline **25/41, 14 unsupported claims**; gold/oracle evidence **40/41, 0 unsupported**; every lexical coverage variant identical to baseline | Generation is not the main problem when the evidence is right. What reaches the model is. |
| dev8: baseline 28/39, oracle 36/39; dev7: 15/21 vs 20/21; dev6: 27/32 vs 28/32 | The same gap on every fresh set. |
| No-model diagnosis of dev6 and dev7 (development sets only, `results/evidence-diagnosis-dev6-dev7.txt`) | **Abstention questions the 7B answered correctly received 5.0 non-gold items on average; those where it invented an answer received 9.3** (B1a returns up to its cap of 10 related-but-wrong items and nothing says "none of these is the answer"). Of 4 failed answerable questions, 2 had all gold sources present and 2 lacked one. Descriptive, 53 cases, not a test. |
| 14B comparison | A larger model does not fix it, and fabricates more with no grounding. |
| Coverage experiments | A check on question words cannot see an unsupported **combination** of facts (every word is present), a **related but wrong** record, or an invented **ordering**. |

So the open problems are **(a) selection**: which passages are shown and whether the ones shown assert the proposition asked about; **(b) answerability**: a first-class decision that the evidence does *not* establish the answer; and **(c) generation discipline**: claims that are individually tied to evidence. The five components below map one-to-one onto these and are deliberately separable.

**Primary target:** fewer unsupported material claims **without making Reachy unusably conservative.** Both are measured everywhere (section 7); a mechanism that wins on unsupported claims by abstaining on answerable questions does not count as a win.

## 2. Principles and constraints

- **No full knowledge graph.** Everything below works per query over the passages retrieval already returns (and the existing stores). A persistent graph is revisited only if the evidence in section 8 shows relation matching fails mainly because of multi-record joins or alias resolution that per-query matching cannot do.
- **No generic LLM verification pass as the default.** The measured record is poor (second pass by the 7B: precision 0.09, 55% of correct answers flagged). Components are deterministic or constrained-generation; any model-based check would be a labelled, separate arm.
- **Authorization first, unchanged.** Selection and answerability operate only on passages already revalidated under the trusted `AccessContext`. An abstention or partial reply may mention only authorised material and must be **identical whether a fact is absent or exists but is unauthorised** (no existence leak). Restricted-channel behaviour, text-only destructive confirmation and the 44H boundary are untouched.
- **Separable.** Each component has its own switch, its own offline test, and an ablation arm. No component's evaluation depends on another's being on.
- **Invented corpus only**, no owner data, no cloud model, until a later, separate decision.
- **Production touchpoints: none in this milestone.** Everything runs in the benchmark harness first; an answer-path integration is a later owner decision.

## 3. The five components

### C1. Proposition- and relationship-aware evidence selection (personal-record questions)

*Idea.* Treat a personal-record question as a small proposition to be matched: `(subject, relation, [object/value])`, for example `(Quill, owner, ?)`, `(Harbor, retry limit, ?)`, `(Beacon, support hours, ?)`, `(Lantern, rollback window, ?)`, `(Dana, reviews, Quill retry settings)`. Retrieval still produces candidates (top 30, not 10); C1 then **keeps passages that assert the relation about the subject** and drops the rest, instead of letting word overlap rank everything.

*How, deterministically.*
1. Subject and object come from the existing entity vocabulary (people, projects, systems, models: the stores' names and aliases, the same source the shadow qualifier already uses) plus capitalised/identifier tokens.
2. The relation comes from a small, written **relation lexicon** (owner/owns/leads, reviews, benchmarks, retry limit/retries, hours/reachable, window/deadline, default model/runs/serves, budget, decision, attends/speaker, due/by) with synonyms and the inflections already handled by the stemmer. A question with no recognised relation falls through unchanged (C1 does nothing).
3. Candidate passages are split into sentence-level units that inherit the record's title, heading and scope (the unit built for the section experiment; it is reused, not as a coverage signal but as the matching unit). A unit **asserts** the proposition when, in one sentence, the subject (or alias) and a relation cue co-occur, optionally with a value (number, name, time).
4. Output: ordered `selected` passages (asserting units first, with the matching sentence marked), `related` passages (subject only or relation only, demoted and, by default, not shown), and a per-passage reason code. The builder shows `selected` first within the same token budget.

*Variants kept separable.* C1a: re-rank only (nothing removed). C1b: filter (show only asserting passages plus at most k related). C1c: filter with a conflict rule (if two asserting passages give different values, keep both and mark the conflict; this subsumes the existing numeric-conflict hint).

*Known risks.* The lexicon is hand-written and incomplete; paraphrases ("who is in charge of" for owner) will be missed and the passage dropped (a recall loss that shows up as false abstention). The design therefore measures **recall of gold passages after C1** explicitly (target: no more than 2 points below B1a's) and keeps the relation lexicon extensible by the owner's vocabulary only through a reviewed file, not learned from data.

### C2. An explicit answerability state

*Idea.* Make "the evidence does not establish this" a computed, first-class state instead of something the model is hoped to say.

States, computed from C1's output (never from question words alone):
- **ESTABLISHED**: at least one selected passage asserts the full proposition (subject + relation + value).
- **PARTIAL**: the question has several parts (the mixed supported/unknown pattern) or a value is missing for an established relation ("Tomas leads infrastructure; no reporting line is recorded").
- **CONFLICTED**: two authorised passages assert different values for the same proposition.
- **UNESTABLISHED** (a.k.a. INSUFFICIENT): no passage asserts the proposition. Related passages may exist (same subject, different relation; same relation, different subject) and are described, not asserted.

*What the state does (each a separate policy arm).* C2-note: add a code-written, factual line to the evidence message (as the coverage note did, but derived from propositions). C2-template: for UNESTABLISHED, a **deterministic reply** with no model call ("I don't have a record of who owns the Lantern release script. I do have a record of ... for ..." listing only authorised related facts). C2-partial: for PARTIAL, a template or constrained generation that states the established parts and names the unknown part. A tunable **conservatism budget** (section 7) caps the abstention rate on answerable questions.

*Risk.* An UNESTABLISHED false positive silences a correct answer. That is why the state is evaluated first as a confusion matrix against gold labels with no model in the loop (section 6), and why the first deployed use, if any, would be note-only.

### C3. Authoritative structured-store routing where a relation maps cleanly

The status and person routes (`knowledge/routing.py`) are the precedent: for these relations the store is the truth and no retrieval is needed. The survey of what maps cleanly onto existing stores:

| Relation | Store / field | Maps cleanly? |
|---|---|---|
| open or done tasks; task text; who a task names | `tasks` (text, done) | yes for status; "who" only if the text names a person |
| reminders and alarms: when, label | `reminders`, `alarms` (due_at, enabled) | yes |
| meeting attendees / speakers; meeting title, date; number of segments | `meetings` (speaker_names, title, created) | yes: **attendees = speaker_names**, authoritative |
| who said / was addressed in a meeting | meeting segments (speaker, text) | yes for "who said"; "was addressed" is text |
| notes: title, body | `notes` | yes by title lookup |
| profile and working memories (type, scope, created) | `memories` (free text, typed) | partly: type and recency are structured; ownership/roles are text |
| owner, role, retry limit, support hours, default model, rollback window | free text in documents/memories | **no**: this is the C1/C2 territory |

C3 adds the missing clean mappings (meeting attendees, reminder/alarm times, note lookup by title) as routed answers with deterministic text and source ids, evaluated on its own. It must say plainly what it covers (as `status_note` does) and fall through when the relation is not one of the mapped ones. No new store, no schema change. **C3 is expected to help narrowly** (attendee, schedule and status questions) and is kept to prove that; most unsupported claims occur in the "no" rows of the table.

### C4. Fact-per-citation / atomic-claim generation

*Idea.* Change what the model is asked to produce: not prose, but a list of **atomic claims**, each with exactly one evidence id and a verbatim quote from that item, plus an explicit `unknown` list, rendered into prose deterministically (text) or into the short spoken form (voice). Structured output is available on the production server: a one-shot probe against the 7B with a JSON schema returned valid claims in the requested shape. The same probe returned an **empty quote**, which is the predicted failure: the schema must enforce a non-empty quote of bounded length (`minLength`), and quote fidelity is the first thing the experiment measures.

```
{"claims":[{"claim":"Tomas Weber owns the Quill message queue.","evidence":"E1","quote":"Tomas Weber owns the Quill message queue."}],
 "unknown":["who the on-call contact is"]}
```

*Risks.* Naturalness and voice length; the 7B's quote discipline; extra tokens (about +40% completion tokens estimated, to be measured); and the claim list can still contain a wrong claim that has a valid quote (a misread). C4 is evaluated **with C5 off** to see the effect of the format alone, and on gold evidence to separate format cost from selection effects.

### C5. Validation of atomic claim → cited evidence relationships

*Idea.* Because C4 gives each claim a quote, validation becomes string and token logic, not a model judgement:
1. The quote must be a verbatim substring (whitespace- and case-normalised) of the cited item, and the cited id must exist in this turn.
2. Every **entity, number, date and name token** in the claim must appear in the quote or in the cited item's title/heading/speaker (the rule that kills "the deep path serves Falcon-7B", where the quote says "deep path" and Falcon-7B is in another passage).
3. The claim's relation cue must appear in the quote's sentence (so "Priya's project runs Falcon-7B" fails when the quote is about a decision).
4. A claim that fails any check is **dropped, not regenerated**; the rendering says what remains and lists the dropped claim's topic under unknown. No second model pass.

*Why this is not the failed free-text checker.* The earlier post-generation checks tried to find support for free prose in evidence after the fact (precision 19%). Here the model commits to the support in advance, and the check verifies the model's own quote, so false drops should be rare; that is a hypothesis and the experiment measures the false-drop rate on valid claims directly.

## 4. Interactions and what stays out of scope

C2 consumes C1's output; C5 consumes C4's; C3 stands alone; C1 and C4/C5 are independent of each other. The generation failures this milestone does **not** target, and which stay open and tracked: repeating a planted instruction (contamination echo), misreading a correct quote in a yes/no question, invented reasons attached to correct facts when no atomic claim contains them (C4/C5 may suppress some), hedged supersession, and the retrospective action-claim problem ("Did you finish X?"), which belongs to the receipt-backed Phase 44H work.

## 5. Where each component would sit in the answer path (for later, not now)

`retrieval (top 30) → revalidation under AccessContext → C3 route if a mapped relation → C1 selection → C2 answerability state → builder (selected passages, budget) → [C4 constrained generation → C5 validation → rendering] or [normal generation] → reply`. Phase 43 attached meetings, restricted channels and the 44H boundary keep their current precedence. Nothing is inserted before authorization.

## 6. Experimental design (separable, factorial where cheap)

**Staged, so each stage answers one question and the expensive stage only runs what earned it.**

0. *Corpus v2 and labels (no model).* The 30-record invented corpus is too small to stress selection. Extend it deterministically (same generator style, still invented) to about 300 records with near-duplicate entities, shared words across projects, archived versions and sibling relations; every question gets gold passages and a gold answerability label (ESTABLISHED, PARTIAL, CONFLICTED, UNESTABLISHED). Questions are generated from templates for the **component-level** stages (hundreds, cheap) and hand-written for the end-to-end stages (dozens).
1. *Component evaluations with no model.* C1: precision and recall of gold passages against B1a at equal budget, and non-gold items shown (the diagnosed 5.1 vs 9.3 quantity). C2: confusion matrix against the gold labels (false-UNESTABLISHED rate on answerable questions is the conservatism measure). C3: coverage (share of mapped questions routed) and exactness of routed answers. C5: false-drop rate on gold-valid claims written by hand, and catch rate on seeded invalid claims (cross-section, wrong entity, invented value).
2. *End-to-end ablation on a new design set (dev11), 7B, identical evidence and prompts across arms.* Arms: B0 baseline; B0+C1b; B0+C2-note; B0+C2-template; B0+C3; B0+C4; B0+C4+C5; C1b+C2-template; C1b+C2-template+C3; the full stack; and oracle evidence with and without C4/C5 to separate generation from selection. Each arm turns on exactly the named components.
3. *Freeze.* Components, thresholds, lexicon, scorer, cases and the pre-registered reading are hashed (the `freeze_check` pattern), with an untouched acceptance set (dev12) authored before stage 2 results are seen.
4. *One-shot acceptance (dev12),* comparing B0, the best single component, and the best combination chosen on dev11 only.

## 7. Metrics and the "not unusably conservative" guardrails

Primary: **unsupported material claims** per answer, and per atomic claim for C4/C5 arms. Reported with it, always: fully correct; **false abstention** (answerable questions answered with an abstention); **answerable-completeness** (share of answerable questions fully answered); correct abstention; and separately wrong-entity, partial-evidence, conflict, invented temporal, negative-claim, cross-section and mixed-answer outcomes; plus latency, tokens and the cost of each component. Pre-registered guardrails (numbers to be fixed by the owner before stage 3, proposed here): false abstention on answerable questions no higher than baseline plus 1 case or 3 percentage points, whichever is larger; answerable fully-correct no lower than baseline minus 1 case; and any arm that reduces unsupported claims only by raising false abstention beyond that is reported as a failure, not a win. Statistics: paired comparisons with the number of discordant cases shown; no superiority claim from fewer than about 12 discordant pairs; acceptance sets of at least 80 cases, of which at least 25 fail under the baseline, so that a halving of unsupported claims is detectable; component-level stages use their hundreds of generated questions, not the small end-to-end set, to carry the statistical weight.

## 8. When a graph would be justified, and not before

Revisit only if stage 1 or 2 shows that the dominant remaining misses need joins the per-query matcher cannot do: an answer that requires linking two records through an alias or a third entity ("the infra lead" = Tomas = owner of Quill) in more than a stated share (proposed: 20%) of the questions the C1 lexicon fails on, **and** a cheaper fix (an alias table in the entity vocabulary) does not recover them. Absent that evidence, no graph is built.

## 9. Risks that could invalidate the milestone

Overfitting to the invented corpus (hence corpus v2, generated questions and a frozen acceptance set); a hand-written relation lexicon that encodes the author's phrasing (hence recall measured against questions written by someone other than the lexicon author, and a review gate); a 7B that will not quote faithfully (C4 then fails cleanly and is dropped, leaving C1 to C3); abstention that sounds unhelpful (the guardrails and a usefulness check on the owner's reading of sample replies); and information leakage through an abstention message (a test that the reply is identical for absent and for unauthorised facts is part of every arm).

## 10. Decisions requested before any work starts

1. Approve this decomposition (C1 to C5) and the staged plan, or remove components.
2. Approve building corpus v2 (invented only) and the dev11/dev12 sets.
3. Fix the conservatism guardrail numbers in section 7.
4. Confirm that structured (JSON-schema) generation on the 7B is acceptable for experiments, with voice rendering deferred.
5. Confirm that nothing in this milestone touches a production answer path until a separate decision.
