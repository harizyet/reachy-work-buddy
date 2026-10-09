# Phase 44: selective answering, Stage B mechanism design (design only; 2026-10-13)

**Status (updated 2026-10-10): the deterministic parts (admission, state table, templates) are built as Stage B-1 and evaluated offline on dev15 ([B-1](verification/phase-44-selective-stage-b1-2026-10-13.md), [I-1/I-2](verification/phase-44-selective-i1-i2-2026-10-10.md)); no model stage, no integration, nothing frozen or deployed. Sections 2 to 10 are the original design; section 3.1 (absence semantics) was added 2026-10-10.** Owner direction, 2026-10-12: *prepare a mechanism design that separates discovery evidence from admissible answer evidence and supports independent answerability decisions per requested sub-claim; handle supported, unsupported, conflicted, historical, negative-supported, negative-unsupported and ordering-unsupported states; prioritise selective partial answers over whole-answer abstention; do not assume a generic second LLM pass or JSON generation; specify trust boundaries, authorization, provenance, policy precedence, failure behaviour, tests and ablation methodology. Do not implement, freeze dev16 or change production answer paths without another decision.* Production is unchanged: Qwen2.5-7B, the 44H unclaimed-action boundary live, indexing off, retrieval and shadow off, 44F not implemented.

Related: [Stage A record](verification/phase-44-selective-stage-a-2026-10-12.md), [adjudication record](verification/phase-44-selective-adjudication-2026-10-13.md), [selective-answering protocol](phase-44-selective-answering-protocol.md), [dev12 acceptance](verification/phase-44-groundedness-dev12-acceptance-2026-10-12.md), [dev14 record](verification/phase-44-scoped-readiness-dev14-2026-10-12.md), [44E sufficiency](verification/phase-44e-evidence-sufficiency-2026-10-12.md).

## 1. What the evidence says the mechanism must do

Measured on the production 7B with the Stage A scorer (dev15, 173 questions; design data, not an acceptance result). B1a is today's retrieval evidence; the oracle arm sees only the gold records.

| Failure | B1a | Oracle | What it implies |
|---|---|---|---|
| Unsupported sub-claim answered | 24 / 88 | 0 / 88 | caused by **what the model is shown** (sibling values) |
| Ordering invented on undated pairs | 8 / 9 | 1 / 9 | caused by showing two values the model then orders |
| Absence claimed from silence | 3 / 6 | 0 / 6 | evidence-driven |
| Conflict, both values given | 4 / 19 | 9 / 19 | **capability**: the 7B gives one side even on perfect evidence |
| False abstention on a supported sub-claim | 24 / 154 | 12 / 154 | partly capability; the cost the design must not raise |
| Whole-answer refusal despite a supported part | 14 | 12 | capability (it refuses, not retrieval) |

Constraints from earlier negative results, treated as design inputs:
1. **Labelling is not a boundary (dev14).** Marking retrieved material uncitable did not stop the model asserting from it. Anything the model may not assert must not be in its prompt as assertable material.
2. **C4 (JSON atomic claims) cost answers (dev12).** Its arm lost net fully correct answers and raised false abstention; the "I don't have a record that establishes…" rendering was read as abstention. No JSON generation here.
3. **C5 worked as a validator, not as a pipeline stage.** At claim level 49 of 51 claims passed, the 2 rejected were genuinely wrong, and nothing rejected was accepted. Deterministic span/identity/authorization checks are reliable; asking the 7B to emit structured claims for them is the expensive part.
4. **Generic checks over free text do not enforce.** The post-generation lexical checks had 19% precision (46 flags, 3 true for unsupported specifics); the 7B as second-pass verifier had 9 to 17% precision and flagged 40 to 64% of correct answers. No second free-text LLM pass, and no regenerate-on-flag rule.
5. **Lexical coverage signals do not replicate (dev10).** Admission must not be decided by word overlap alone.
6. **Date confound (Stage A).** A displayed date was a retrieval date; the model and the author both read it as an ordering.

So the mechanism has to act on *what the model sees and what the code renders*, not on a post hoc judgement of free text.

## 2. Architecture

```
question ─► (1) decomposition ─► components c1..cn (deterministic)
             │
retrieval ─► DISCOVERY POOL (untrusted; never shown as assertable)
             │
             ▼
        (2) admission, per component (deterministic code over typed record metadata)
             │            evidence ticket per component: state, admitted records, values, time fields
             ▼
        (3) state policy table ─► per component: ASSERT | PRESENT_CONFLICT | MARK_PAST | STATE_ABSENCE | WITHHOLD
             │
             ├─ ASSERT / MARK_PAST components ─► (4) clause-scoped generation (one plain-text call per component, or one call over
             │                                      admitted records only), or deterministic rendering when the value is typed
             └─ other components ─► (5) deterministic templates (code writes them; the model never sees withheld material)
             ▼
        (6) assembly in question order ─► (7) narrow value-leak telemetry ─► existing 44H boundary ─► reply
```

### 2.1 Decomposition (deterministic)
Reuse the clause splitter and relation/subject routing that C1 already uses (tested, deterministic). A component = relation, subject, kind of ask (value, existence, attendance, ordering/supersession, history). **Failure:** if the question cannot be split or typed, it becomes one component with the whole question and runs the existing path for that turn (never a refusal); the event is counted as `decompose_fallback`. The decomposition error rate is a component result reported before any end-to-end run (the protocol already requires this).

### 2.2 Discovery evidence versus admissible answer evidence
- **Discovery pool**: everything retrieval returns, including routed memories, sibling-project records, other-entity records and quarantined context. Used to find candidates, to decide *whether anything was found at all*, and to build the "not established" statement. **Never put in the generator prompt as something it may assert from.**
- **Admissible answer evidence**, per component, is a record that passes all of: (a) **authorised** for this turn (section 4.2); (b) **provenance recorded** (store, record id, author class, created-at, effective-at if stated, retrieved-at); (c) **asserts** the component's relation for the component's subject, decided by a typed extractor over the record (subject, relation, value) and not by word overlap; (d) is **not instruction-bearing content** acting as a source (untrusted text is data); (e) for HISTORICAL, carries an explicit past/as-of/archived marker in the record itself.
- A record that is related but does not assert (a sibling's value, an adjacent relation, a document about the same project) is discovery-only. It may support the *reason* line ("records name Falcon-7B, not Falcon-3B") only when code writes that line, and never supplies a value.
- The extractor is deterministic in v1. C2's calibrated annotation is an input signal about extractor confidence, never a gate (owner decision, dev14). An LLM-assisted admission arm exists only as an ablation with its own precision test (section 8, arm A+LLM) because of constraint 4.

### 2.3 Independent answerability per component
Each component gets its own ticket; one component's state never changes another's. A question with three components can yield one assertion, one conflict presentation and one withholding in the same reply. Whole-answer abstention is **only** the case where every component is WITHHOLD, and even then the reply names each part.

## 3. States, evidence rules and rendering

The state is a pure function of the admitted records for the component and the question's ask. Time fields are separate: **retrieval time** (when the system fetched it) and **record creation time** (when the store row was made) never establish recency, ordering or supersession; **fact effective time** counts only when the record states it explicitly, and supersession needs an explicit authoritative statement (a record saying it replaces another, or two as-of statements with dates).

| State | Admission condition | Policy action | Rendering (who writes it) |
|---|---|---|---|
| SUPPORTED | one or more admitted records assert one value (agreeing duplicates collapse) | ASSERT | value with its source ids; generated from admitted records only, or templated when the value is typed |
| UNSUPPORTED | nothing admitted for this component, though discovery found other material or nothing | WITHHOLD | code: "The records do not say <part>." Never a value, never a sibling's value, never "no one" |
| CONFLICTED | two or more admitted records, different values, no explicit authoritative ordering | PRESENT_CONFLICT | **code**: "<source A> says X [E1]; <source B> says Y [E2]; the records do not say which applies." Templated because the 7B gives one side in 9 of 19 even on oracle evidence |
| HISTORICAL | an admitted record explicitly marked past/as-of/archived with its own effective period | MARK_PAST | value marked past with the record's stated period; if a current value is also admitted, both are shown with their markers; never "now/currently" attached to the past value |
| NEGATIVE_SUPPORTED | an admitted record explicitly asserts absence for the subject (a typed "has no X" statement) | STATE_ABSENCE | absence stated with its basis: "<record> says <subject> has no <X> [E]" |
| NEGATIVE_UNSUPPORTED | the question asks about existence/absence/mention and no admitted record asserts presence or absence | WITHHOLD (world-level absence is never asserted) | two forms, see section 3.1: **scoped-search negative** (an admitted record states a bounded search and its scope): code: "A search of <scope> found no <X> for <subject> [E]; <unsearched scope> was not checked."; **unknown** (no such record): code: "The records I searched do not mention <X> for <subject>." |
| ORDER_UNSUPPORTED | the question or two admitted values invite "newer/updated/replaced/which first", and there is no explicit authoritative ordering | WITHHOLD the ordering, keep the values | code: values shown as in CONFLICTED, plus "nothing in the records dates one before the other." No "updated", "newer", "outdated", "superseded" |

Precedence among states for one component: explicit authoritative supersession (HISTORICAL with a stated successor) over CONFLICTED; CONFLICTED over SUPPORTED when any admitted record disagrees; NEGATIVE_SUPPORTED versus an admitted presence record is CONFLICTED, not a winner. A presence record on a sibling project is discovery-only. When two authorised records disagree and one is a third-party document and the other the owner's own memory, **the policy does not rank them** (source rank is not an ordering); both are shown with their provenance and the owner decides.

### 3.1 Absence semantics (rubric v5, 2026-10-10; evidence contract)

Owner decision, 2026-10-10, after the consumed scorer-v3 validation. A negative statement about a subject and relation belongs to exactly one of three evidence classes, and the class decides what may be said:

| Class | Evidence required | State | What the reply may say |
|---|---|---|---|
| 1. Scoped-search negative (verifiable) | an admitted, authorised record that states a **bounded search and its scope** and that it found nothing ("Looked in the Osprey chat space only for an escalation channel and found none there. Other spaces were not searched.") | NEGATIVE_UNSUPPORTED, scoped form | only the search result with its scope and, when the record says so, what was not checked: "A search of the Osprey chat space found no escalation channel [E]; other spaces were not checked." Never "there is no escalation channel" |
| 2. Authoritatively established absence | an admitted, authorised record from an authoritative author class (owner or system) that states the absence itself ("Marlin has no staging environment") | NEGATIVE_SUPPORTED | "<subject> has no <X>", with the record cited |
| 3. Unknown or insufficient evidence | no admitted record asserts presence, absence or a scoped search (including: only unauthorised or sibling records exist) | NEGATIVE_UNSUPPORTED, unknown form (or UNSUPPORTED for a value ask) | "The records I searched do not mention <X> for <subject>." Nothing about the world |

Rules, enforced by the state function and by template purity tests (they restate [rubric v5](../services/companion-core/benchmarks/answer_quality/selective/adjudication_rubric_v5_addendum.md)):
1. **A scoped search result never implies world-level nonexistence without explicit authoritative evidence.** There is no inference path from class 1 to class 2: not by count, by recency, by the search covering "most" places, or by the generator's phrasing.
2. **Scoped negatives do not compose.** Several scoped negatives remain scoped; only a class 2 record establishes absence.
3. **Scope must be verifiable.** The record has to name what was searched. A note that only says "no runbook found" has no verifiable scope and is class 3. The scope text shown to the owner is quoted or copied by code from the record, not paraphrased by the model.
4. **Conflict with authority.** A class 1 record next to a presence record is not a conflict (a search of one place not finding it is consistent with it existing elsewhere); the presence record decides SUPPORTED. A class 1 record next to a class 2 record agrees with it and adds nothing. A class 2 record next to a presence record is CONFLICTED, as before.
5. **Registry mapping, unchanged.** The frozen corpus v5 condition `incomplete_scope` has gold NEGATIVE_UNSUPPORTED, `silent` and `unauthorized_only` the same, `explicit_absence` NEGATIVE_SUPPORTED. Class 1 is a *rendering and evidence distinction inside* NEGATIVE_UNSUPPORTED, not a new registry status, so no frozen manifest changes.
6. **In code (I-1, 2026-10-10; source and tests only, not wired).** The Stage B-1 admission reads a bounded search into a `ScopedFinding`, the state function separates authoritative from attributed absence, and the renderer has the scoped, attributed and unknown wordings; 27 tests ([record](verification/phase-44-selective-i1-i2-2026-10-10.md)).

Rubric versions: v2 (sealed) → v3 addendum → v4 addendum (used by the consumed scorer-v3 validation) → **v5 addendum** (this section; adjudication from 2026-10-10 on). The consumed scorer-v3 acceptance labels, report and verdicts are not altered or re-labelled; see [the result record](verification/phase-44-scorer-v3-formal-validation-2026-10-10.md), where the scoped-search convention disagreement drove ten of the natural absence false positives.

**Selective partial answers.** The reply is assembled in question order from per-component renderings, so a supported part is never removed because another part is withheld. The templates are short and component-named (they replace "I cannot answer that"), which targets the 14 blanket refusals and the false abstentions that survive on the oracle arm.

**Generation.** Supported and historical components are the only ones that call the model. Two arms (ablation, section 8): one call over all admitted records for the SUPPORTED/HISTORICAL components in plain text with a one-line directive per component written by code; or one call per component. Where the relation has a typed value (person, number, day, month, model, host, hours) a no-model arm renders the value by template, which gives a floor for what the model adds. Output is plain text. No structured output is requested from the 7B.

## 4. Trust boundaries, authorization and provenance

### 4.1 Boundaries
| Zone | Content | Authority |
|---|---|---|
| Discovery (index, retrieval, embeddings, memories, meeting segments, documents) | untrusted text | none: may contain instructions ("ignore previous instructions", "system instruction") and forged "supersedes" lines |
| Admission and state policy | deterministic code | decides what may be asserted; reads records only as data through typed extractors |
| Generator (7B) | sees admitted records and code-written directives only | can phrase; has no tool, action or consent authority; cannot add components |
| Renderer / assembler | code | writes withheld, conflict, negative and ordering text; fixes order |
| Action and consent gates (ADR 0011, 0006, 0018) and the 44H unclaimed-action boundary | existing deterministic code | unchanged and above everything here |

The generator never receives discovery-only material, so the dev14 failure (a label the model could ignore) is removed rather than mitigated: ignoring it is not possible because it is absent.

### 4.2 Authorization
Authorisation is evaluated at admission, per record and per turn (access class, attached-meeting scope, attendee routing as in C3, owner versus third-party viewer). An unauthorised record is dropped **before** discovery results are summarised, so the reply cannot reveal that it exists: a component whose only evidence is unauthorised renders as UNSUPPORTED with the same wording as an empty search. Citations are validated by code against the turn's manifest (existence and authorisation), as now (criterion 5).

### 4.3 Provenance
Every admitted fact carries: `store`, `record_id`, `author_class` (owner, attendee, third-party document, system), `created_at`, `effective_at` (nullable, only if stated in the record), `retrieved_at`, `authorized`. The assembler may cite only ids in the admitted tickets. Provenance is logged per turn as the evidence ticket (no new store in this phase: design only).

## 5. Policy precedence (highest first)
1. Action, consent and destructive-confirmation gates; the 44H unclaimed-action boundary; text-only destructive confirmation; private-response routing. The selective layer cannot approve, narrow or bypass them, and it runs only on knowledge-answer turns.
2. Authorisation and privacy routing (section 4.2).
3. Admission and state policy (sections 2 and 3). A template-rendered component cannot be altered by the generator or by persona styling.
4. Persona and rendering style, applied to model-written text only, never to templated statements of absence, conflict or ordering.
5. Free model text (supported and historical components only).
If two rules disagree the higher wins; a lower layer that wants more disclosure than a higher layer allows is ignored and counted.

## 6. Failure behaviour
| Failure | Behaviour | Why |
|---|---|---|
| Decomposition cannot type the question | one component, existing path, counted as fallback | never turn a parser miss into a refusal |
| Extractor error or timeout for one component | that component is WITHHOLD with "I could not check <part>" (distinct wording, counted); other components continue | fail closed on assertion, open on the rest |
| Authorisation cannot be determined | treat as unauthorised | privacy first |
| Model call fails or times out | typed components still rendered by template; others "could not check"; no partial free text | no silent loss, no invented text |
| Model output mentions a discovery-only value in a withheld component's clause | telemetry increment; reply unchanged | constraint 4: no regenerate, no replace on a low-precision signal; promotion to enforcement needs the precision gate in section 8 |
| Whole pipeline raises | existing production path for the turn (which has retrieval off today) plus the 44H boundary | the layer is additive and removable |
| Both values equal after normalisation | collapse to SUPPORTED | avoid a false conflict |

The feature is a flag, default off, disabled by the same switches that gate retrieval; with retrieval off nothing changes.

## 7. Tests (to be written when implementation is approved; nothing exists yet except the Stage A corpus and scorer)
1. **Unit, per state**: a table test with one fixture per state, per ask kind, with fixtures for agreeing duplicates, equal-after-normalisation values and a record that asserts a sibling relation.
2. **Authorization**: unauthorised-only evidence gives the empty-search wording byte for byte; an unauthorised record never appears in a ticket, a citation or the discovery summary; attendee routing cases from C3.
3. **Date semantics (owner rule)**: retrieval date and creation date differ from effective date in fixtures; neither ever produces HISTORICAL, an ordering or a supersession; a record that explicitly says it replaces another does.
4. **Injection and forgery**: document text containing instructions, a forged "supersedes", and a forged "as of" line from a third party; none changes a state or reaches the prompt as an instruction.
5. **Metamorphic**: reordering records, adding an irrelevant record, renaming a project in both question and records, paraphrasing the question (unseen bank), splitting versus joining components: ticket states are invariant or change only as specified.
6. **Template purity**: withheld, conflict, negative and ordering text contains only fixed strings plus component names and source ids; a leak test over every held-out relation value.
7. **End to end on dev15 only**, scored by the validated scorer: all criteria with the owner's definitions (fully correct, criteria 4, 6, 7, 8, 9 forms). No dev16 run.
8. **Regression**: dev8/dev10/dev12/dev14 manifests and files unchanged (`freeze_check.py`), existing companion-core tests, ruff.
9. **Scorer-dependency check**: because the scorer missed 3 of 9 severe events in adjudication, criteria 7 and 9 results from any run are accompanied by a full human read of conflict and ordering replies until a revised scorer has a validated sensitivity.

## 8. Ablation methodology

**Principle:** every element is switchable, measured alone and in combination, always against the same baseline and always with the oracle-evidence counterpart so retrieval limits and capability limits are not confused. C1, C2 and C3 stay separately switchable as they are now.

Factors: **D** decomposition, **A** admission (deterministic), **S** state templates (unsupported, conflict, negative, ordering), **R** generation scope (single call over admitted records, or one call per component), **T** typed no-model rendering, **V** value-leak telemetry, plus **C1, C2, C3**.

| Arm | Contents | Question it answers |
|---|---|---|
| P0 | B1a, today's prompt and the 44H boundary | reference |
| P0+ | P0 with the reply contract in the prompt only | does instruction alone work (protocol P1) |
| D+S | decompose, no admission: templates for components with no matching record in the pool | value of rendering alone |
| D+A | decompose and admit, generator sees only admitted records, no templates | value of withholding evidence (the dev14 repair) |
| D+A+S | full policy, single generator call | the central candidate |
| D+A+S+R | as above, one call per component | does clause scope add anything (protocol P2/P3) |
| D+A+S+T | typed values rendered by code, no model for them | floor and upper bound on safety, cost in naturalness |
| D+A+S+V | adds the value-leak check as telemetry only | precision of the check against the scorer (must exceed a pre-registered precision before any enforcement use) |
| A+LLM | admission uses a 7B judgement of "asserts" | included only because the owner asked not to assume LLM-free; it is expected to inherit the 9 to 17% precision seen in verification |
| each of the above on oracle evidence | gold records only | capability limit |

Plus leave-one-out from D+A+S (drop D, A, S, R in turn) and, for C1/C2/C3, the current switches layered on D+A+S to see whether they still add anything once admission exists.

**Measurement rules.** Dev15 only until the owner decides on dev16. Paired by case; report discordant pairs and sign tests, not only counts. The 7B's replay noise is about 5%, so every arm is run three times and the baseline's replicate disagreement sets the noise floor for "no difference". Primary metrics follow the owner's ten criteria with the new definitions (fully correct, criteria 4, 6, 7, 8, 9 with upper or lower bounds and counts of independent opportunities); secondary: blanket refusal, false abstention on supported and historical, wrong value, `decompose_fallback` rate, latency (model calls per turn and median/p95). Every arm, its prompt and its switches are listed and hashed before any run; no run is repeated after seeing it. Scorer and rubric are the frozen, adjudicated versions; if the scorer is revised from the adjudication, the revision is validated on a new sample first and dev15 results are reported with both versions. Report regressions by case id.

**Predictions to be checked, not claimed.** From the taxonomy: S plus A should bring unsupported answers, invented ordering and absence claims toward zero on dev15 (oracle already shows 0, 1 and 0), and templated conflicts should show both values in nearly every conflict by construction; the open risk is **supported-part false abstention**, which is 16% on B1a and 8% on the oracle arm and which admission can raise if the extractor misses an asserting record. The design succeeds only if that rate does not rise (criterion 2) while the other failures fall.

## 9. Known limits of this design
- **Generalisation.** The corpus is invented and templated; real records are free text. Typed extractors that work on 24 people, 12 projects and 20 relations may not generalise, and success on dev15 or dev16 would not show it. The held-out relations and projects in dev16 test only transfer inside the same style. A real-data stage (shadow with the owner's approval, on the owner's own records) is needed and is outside this design.
- **Template fluency.** Code-written statements will sound less natural than model text; persona handling for them is deliberately limited. Voice rendering is out of scope.
- **Admission recall.** Anything the extractor cannot type is withheld. The design chooses missing a supported fact (measured, criterion 2) over asserting an unsupported one (measured, criteria 1, 7, 8, 9).
- **Authority conflicts** between a document and a memory are not resolved by rank; the owner receives both. A future ranking rule would be a separate decision.
- **Scorer reliability**: severe-event sensitivity is 67% with a wide interval until the scorer is revised and revalidated.
- **No claim of production readiness.** Retrieval and shadow remain off, and 44F is not part of this.

## 10. Decisions requested
1. Approve implementing nothing yet, or approve a **Stage B-1** limited to the deterministic parts (decomposition, admission, state table, templates) with unit tests and no model, so the state machine can be tested on dev15 without any generation question.
2. The scorer revision path from the adjudication (section 7 of the adjudication record) before any dev15 run that is reported against the criteria.
3. Whether the no-model typed-rendering arm (T) is acceptable as an arm at all (it is a different product: a lookup that answers in templates).
4. Whether the value-leak telemetry (V) may ever be promoted to enforcement, and the precision it must show first.
5. dev16: remains unfrozen and unrun until you decide.
