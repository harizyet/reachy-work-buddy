# Phase 44: B-1 qualified-object tightening (2026-10-14; deterministic source and tests only, nothing wired or deployed)

Owner decision, 2026-10-14: *approve a narrowly scoped tightening of third-person subject–relation–object admission. A statement about ownership of a schedule, process, component or other qualified object must not establish ownership of the broader system or project unless an explicit authoritative equivalence exists. Add regression tests for the Ferry queue schedule example and analogous modifier/object-coverage cases; preserve the safety invariants; report recall lost and distinguish safety-driven withholding from extraction failures; no unrelated recall optimisation.* Closes the finding in the [extension record](phase-44-selective-stage-b1-extension-2026-10-13.md#4-findings-the-owner-should-decide-on).

## 1. The rule (`knowledge/answerability_b1/admission.py`, `_qualified_object`)
A sentence that mentions the subject only as the **start of a longer qualified object** asserts nothing for the subject; it becomes discovery-only (not ambiguous, so it cannot block a clean record). Two structural cases, no parsing and no coreference:
- **Object position** (a relation cue precedes the subject): a head noun that is neither a boundary word nor one of the relation's own words follows the subject's name ("owns the Ferry queue **schedule**", "responsible for the Ferry queue **rollout plan**", "the Ferry queue**'s** schedule").
- **Subject position**: a run of up to four plain words follows the subject and ends at a boundary word, punctuation, the end of the sentence or a relation word ("the Ferry queue **schedule is** owned by", "the Ferry queue **rollout plan belongs** to", "the Ferry queue **schedule owner** is"). A capitalised or numeric token inside the run marks a verb followed by its value ("Cedar serves Swift-20B") and is not a qualifier.
- The relation's own nouns are declared in its reviewed spec (`object_words`; `attends` needs "planning meeting"). A spec that omits them withholds more, never less.
- **Explicit authoritative equivalence:** `AdmissionPolicy.equivalences`, a caller-supplied set of exact lowercase phrases ("ferry queue schedule"); empty by default; lifts the rule only for that phrase.
- Applies to every value kind except existence statements; does not apply to context-, title- or structured-bound facts (they name no subject in the sentence); the first-person speaker path keeps its own object-coverage rule. `qualified_object_check` (default on) exists only so the effect can be measured.

## 2. Tests
`tests/test_answerability_b1.py`: **128 tests passing** (23 new). Nine qualified-object variants withheld (owner position, subject position, possessive, rollout plan, runbook, deployment process, dashboard, a two-word qualifier, a relation word after the qualifier); eight plain statements still admitted ("owns the Ferry queue", "is owned by", "…in production", "…, and it is stable", "'s owner is", "queue owner is", "this quarter", "Ferry queue: Olga Petrova owns it"); a schedule sentence beside a plain one contributes nothing and causes no conflict; the rule on numeric relations; the equivalence lifts exactly one phrase; the switch defaults on; verb-like words are not qualifiers; context-bound sentences unaffected. Ruff clean; frozen sets unchanged.

## 3. Recall and safety, measured (no model; development data; same circularity disclosure as before)
| World | State = gold, before the rule | After | Atoms whose claim text changed |
|---|---|---|---|
| dev15 (307 atoms) | 282 (91.9%) | 282 | **0** |
| val17, a different world (385 atoms) | 358 (93.0%) | 358 | **0** |

**No supported or historical atom lost recall in either world**, and no unsupported atom is answered (dev15 88 of 88, val17 105 of 105). Every sentence the rule rejects, in either world (`results/b1-qualified-object-inventory.txt`):

| Rejected sentence (counts are atom evaluations, not distinct sentences) | Evaluations dev15 / val17 | Classification |
|---|---|---|
| "I will own the <system> schedule." (six systems in each world) | 17 / 21 | **Correct, safety-driven.** These are the planted distractors: a commitment about a schedule. They are text-path sentences; the speaker path already refused them. |
| "Failed <project> jobs are retried N times before they are parked." (Cedar, Marlin, Osprey) | 13 / 13 | **Judgement call, not a gold source of any atom.** The registry treats this memory as a partner of the *system's* retry limit; the rule reads "<project> jobs" as a qualified object of the project. Withholding it is the conservative reading. If the owner wants it admitted, the right mechanism is an authoritative equivalence ("cedar jobs" for Cedar), not a looser rule. |

**Extraction failures versus safety withholding.** None of the rejections is an extraction failure in the sense of a gold sentence the rule mis-read. The one place the rule can cause extraction-style loss is a relation spec that omits its own object nouns (the first run of the new rule failed two attendance tests until `attends` declared "planning" and "meeting"); that is a spec obligation, now documented, not a rule defect.

## 4. Limits
- The rule is structural. A qualifier hidden behind a prefix ("the production Ferry queue") or a long compound is not caught; a first-person or third-person statement about an object the sentence never names is not a subject mention at all.
- Specs from real data must declare each relation's own nouns; the offline checks derive them from cue words, which is circular.
- The two worlds contain only the schedule-style distractor and the project-jobs memory; other qualified-object shapes are covered by unit tests, not by corpus evidence.

Not done: no integration, deployment, migration or model call; dev16 untouched.
