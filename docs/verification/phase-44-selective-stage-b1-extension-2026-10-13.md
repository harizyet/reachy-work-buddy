# Phase 44: Stage B-1 recall extension (2026-10-13; deterministic source and tests only, nothing wired or deployed)

Owner decision, 2026-10-13: *extend B-1 before candidate evaluation, limited strictly to the three identified recall gaps: authoritative structured attendee/speaker input; bounded cross-sentence subject context; conservative deterministic extraction of supported free-text values. Preserve the safety invariants; extraction failure or ambiguous subject binding stays unestablished. No general coreference. No further dev15-driven optimisation. Ambiguity applies at the smallest affected proposition.* Predecessor: [Stage B-1 record](phase-44-selective-stage-b1-2026-10-13.md). Production unchanged; no model call, no integration, no migration; dev16 unfrozen, unrun and unused.

## 1. What changed in `knowledge/answerability_b1/`

| Gap | Mechanism | Bounds |
|---|---|---|
| 1 structured input | `AttendeeRecord` (a meeting's attendee list) and `SpeakerSegment` (a segment with its resolved speaker) are separate input types that pass the **same provenance and authorisation checks** and must come from an **authoritative author** (owner/system). Attendees become a set of facts; a first-person statement ("I will fix the Cedar rollback test") is attributed to the resolved speaker. A relation opts in with `RelationSpec.structured`. | An empty attendee list is not evidence that nobody attended; an unparsable name or an unresolved speaker ("SPEAKER_00") is ambiguous and never guessed; a hedged statement is ambiguous; the statement's object must be only the subject, the relation's own words and function words (`object_words`), so "I will own the Conduit stream **schedule**" asserts nothing about the Conduit stream. A non-authoritative or unauthorised record is excluded. |
| 2 cross-sentence context | A sentence that names no subject takes the subject of **the one previous sentence of the same paragraph** only when that sentence names this subject and no other and is not hedged, and the current sentence names no other subject. | One sentence back, never across a blank line, a heading or a list item; no pronoun resolution; the fact's evidence is both sentences; switchable (`AdmissionPolicy.allow_context`). |
| 3 free text | `RelationSpec(kind="text", text_pattern=...)`: a reviewed regex with a named group `value`. | At most 10 words, no sentence punctuation, hedge or negation inside; two different values in one sentence are ambiguous; **no pattern, no reading**. Another entity named inside the captured phrase ("reviewing the Sluice settings") is not a competing subject; the rest of the sentence still is checked. |
| Ambiguity policy | Applied **at the smallest affected proposition.** An ambiguous sentence that bears on the requested subject, relation and time scope makes a single-valued answer **unchoosable** (the claim is withheld with "the records on the X are unclear, so I will not pick an answer"; no value is chosen even next to a clean record). A conflict stays a conflict (nothing is chosen). For many-valued relations each value is its own proposition, so independent supported values stay answered with a caveat. Ambiguity about a different time scope does not block the question asked. Other components are never touched. | Previously an ambiguous record only added a caveat beside a clean value. |

Tests: `tests/test_answerability_b1.py`, **105 tests passing** (37 new): authorisation, malformed provenance and non-authoritative author for structured input; speaker resolution and wording; the context boundaries (blank line, heading, list, two sentences back, two subjects, hedged previous sentence, pronoun); free-text hedge, negation, length, multiple values, missing pattern; ambiguity at proposition level (clean record beside an ambiguous one, independent components, many-valued relation, other time scope); injection and unauthorised text still unable to reach a value. Ruff clean for `services shared`; `freeze_check.py` passes; nothing imports the package except tests and the offline script.

## 2. Offline development check against dev15 (no model; development data; same circularity disclosure as before)

`benchmarks/answer_quality/selective/b1_dev15_check.py`, output `results/b1-dev15-check-extension.txt`; the previous configuration is kept as `results/b1-dev15-check-before-extension.txt`. The discovery pool is the whole invented corpus; subject and cue patterns come from the gold annotations (so this measures logic, not generalisation). Structured input is built from the corpus's own speaker map; the two text patterns are written from the relation wording (not from dev15 replies). Result: state equals gold on **282 of 307 (91.9%)**, up from 239 (77.9%).

| Gold status (n) | Before extension | After |
|---|---|---|
| SUPPORTED (154) | 97 answered | **142 answered**, 12 withheld |
| HISTORICAL (24) | 13 | 11 (the new ambiguity policy withholds two it used to answer) |
| UNSUPPORTED (88) | 88 unsupported | **88 unsupported** |
| CONFLICTED (19), ORDER_UNSUPPORTED (9), NEGATIVE_UNSUPPORTED (6), NEGATIVE_SUPPORTED (7) | all correct | all correct |
| Values of answered supported/historical atoms | no value check existed | 151 correct, **0 wrong** (the 2 flagged "wrong" are the harness comparing an existence answer with the label "yes") |

Step by step (cumulative, state equals gold): the new code with none of the extensions in use 218 (**−21 against the earlier 239, all from the stricter ambiguity policy**: "As of October, the Cedar default model is Swift-20B; the Merlin-2B model has been retired." is a two-value sentence, so the default-model answer is now withheld rather than chosen); two harness fixes (an escaped hyphen in aliases and keeping headings) 231; **+ structured input 249; + bounded context 269; + free text 282.** Per extension, supported atoms recovered: attendance and first-person task statements 18, cross-sentence retry limits and history 20, review and decision phrases 13.

**Safety invariants.** Throughout the final configuration: no gold-unsupported atom is answered, no conflict resolved, no ordering or absence invented. **One regression was caught and fixed during the work:** the first speaker path answered 7 unsupported "who owns the Conduit stream" atoms from "I will own the Conduit stream schedule" (the commitment is about the schedule). The object-coverage rule (`object_words`) closes it and has a test; this is a safety fix, not recall tuning.

## 3. Remaining misses (not optimised, by instruction)

25 atoms: `default_model` 10 and `default_model_history` 13 (the contradictory "retired" sentence now correctly makes them unchoosable; the gold keeps one value, so this is the price of the owner's ambiguity policy) and `support_hours` 2. Nothing outside the three gaps was tuned.

## 4. Findings the owner should decide on

1. **The third-person text path has the same noun-phrase-head weakness that the speaker path just had.** "Olga Petrova owns the Ferry queue **schedule**." is admitted as the owner of the Ferry queue (demonstrated, SUPPORTED). The corpus has no such third-person sentence, so dev15 does not show it. It is pre-existing and outside the three gaps, so **I did not change it**; a tightening (object coverage for verb-object relations) is small and would only reduce recall. Decision requested.
2. The offline check is circular by construction (cue patterns from gold). A held-out relation check needs relation specs written independently of the gold, which is not approved here.
3. Free-text values rely on a reviewed pattern per relation; a new relation has no reading until someone writes one.

## 5. Not done
No integration, no deployment, no migration, no model call, no production record, indexing/retrieval/shadow unchanged, 44F not started; dev16 not frozen, run or used.
