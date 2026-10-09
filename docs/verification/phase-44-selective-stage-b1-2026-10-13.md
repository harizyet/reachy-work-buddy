# Phase 44: selective answering Stage B-1, deterministic components (2026-10-13; source and tests only, nothing wired or deployed)

Owner decision, 2026-10-13: *Stage B-1 approved: deterministic components and unit tests only; the discovery evidence → admissible evidence → per-claim answerability → response-contract pipeline of the [Stage B design](../phase-44-selective-stage-b-design.md); no model calls, response-policy integration, deployment or database migration; dev16 stays unfrozen and unrun and is not used to tune B-1.* Production is unchanged: Qwen2.5-7B, 44H boundary active, indexing off, retrieval and shadow off, 44F not implemented.

> **Correction note (2026-10-10).** Later changes: NEGATIVE_SUPPORTED now requires an authoritative (owner or system) record (a third-party or attendee "there is no X" is reported as attributed and not established), NEGATIVE_UNSUPPORTED has a scoped-search form, display wording changed (articles, plurals, "another says"), and a composer was added: [I-1/I-2 record](phase-44-selective-i1-i2-2026-10-10.md). The 77.9% figure below used a harness whose known-subject list kept escaped backslashes.

## 1. What was built

`services/companion-core/src/companion_core/knowledge/answerability_b1/` (about 700 lines, pure functions, no I/O, no model call). **Nothing in the repository imports it** except its tests and an offline benchmark script (checked with a search); it ships as unreferenced source, like `knowledge/sufficiency.py`. No migration, no endpoint, no setting.

| Module | Role |
|---|---|
| `types.py` | `DiscoveryItem` (untrusted, as retrieved) and `AdmittedFact` (checked, typed) are unrelated classes; an `AdmittedFact` can only be constructed by `admission.admit` (private token, `TypeError` otherwise). States, asks, scopes, author classes, `Provenance`, `AuthDecision`, `RelationSpec`, `Component`. |
| `admission.py` | The only path from a record to an assertable fact. Provenance validation (12 failure reasons), authorisation (missing, denied, stale, from the future, wrong policy version, changed ACL revision), instruction-bearing records excluded, then sentence reading by subject + relation cue + exactly one typed value, with hedged, negated, multi-value and competing-subject sentences reported as **ambiguous** and never admitted. Fact time comes only from the record's own wording, lifecycle or explicit effective period. `find_supersessions`: only an authorised, well-formed, **authoritative** (owner/system) record that explicitly says "supersedes/replaces <ref>"; mutual or self claims cancel. |
| `states.py` | `decide`: one component's admitted facts to one of the seven states (SUPPORTED, UNSUPPORTED, CONFLICTED, HISTORICAL, NEGATIVE_SUPPORTED, NEGATIVE_UNSUPPORTED, ORDER_UNSUPPORTED). Value, existence and ordering asks. Retrieval and creation time are not inputs. |
| `contract.py` | `build_plan`, `render_claim`, `decompose`. Code-written text for every non-value state, claim-level citations (each value lists exactly the evidence ids of the records that state it), fail-closed handling (an uncitable supporting record withholds the claim; one failing component is reported as "I could not check …" and does not affect the others), question-order assembly, `Plan.fallback` when the question cannot be typed (the caller keeps the existing path; never a refusal). |

Requirement coverage: explicit authorisation and provenance checks (sections above); subject/relation/value and temporal-scope matching (admission, `Scope`/`FactScope`); the seven states separate; ambiguous or unparsable evidence handled conservatively (never admitted, caveat on the claim, never an absence or ordering claim); **no automatic supersession from document or retrieval timestamps** (two tests swap creation/retrieval times and assert no change); no unsupported absence claims (NEGATIVE_UNSUPPORTED text is record-level, with a test that it never says "no X"); **no implicit promotion** of discovery evidence (types, token, tests that raw items are rejected and sibling values never reach the text); claim-level citation mappings (a test asserts every id printed in a claim belongs to that claim's mapping).

## 2. Tests

`tests/test_answerability_b1.py`: **68 tests, all passing** (with the 17 Stage A tests: 85 in the two files). They cover each state; stale, missing, denied, future-dated, wrong-policy and ACL-revision-changed authorisation (five parametrised cases); twelve malformed-provenance cases; conflicts and agreeing duplicates collapsing; missing evidence; unsupported ordering (never says "updated/newer/older/latest/superseded/replaced"); explicit supersession by an authoritative record and its refusal for attendee and third-party authors, unauthorised records and mutual claims; explicit effective periods ordering but not resolving a value conflict; partial answerability (four components, four different states, question order); whole-answer abstention only when every component is withheld and each is still named; component isolation on failure; uncitable evidence; ambiguity (five sentence shapes, caveat next to a clean record, no absence from a hedge); instruction-bearing records; many-valued relations; title-as-subject-context; co-subject relations; as-of wording; archived lifecycle; decomposition and fallback; template purity; the excluded-record case where the reply is **byte-identical** to an empty search (no existence leak). Ruff clean for `services shared`; `freeze_check.py` passes (frozen sets untouched); dev16 not read by any B-1 code or test.

## 3. Offline development check against dev15 (no model; development data, not an acceptance result)

`benchmarks/answer_quality/selective/b1_dev15_check.py`, output `results/b1-dev15-check.txt`. It runs the pipeline over the **whole invented corpus** as the discovery pool (harder than retrieval) for each of the 307 dev15 atoms, authorising records by the owner_private profile. **Disclosure:** the subject and cue patterns come from the atoms' own `subject_re`/`cue_re`, written by the same author as the gold, so this measures the state logic and the sentence reading, not generalisation to unseen relations. Result: state equals gold on **239 of 307 (77.9%)**.

| Gold | Pipeline |
|---|---|
| UNSUPPORTED (88) | 88 UNSUPPORTED (no leak; the two incident-auditor atoms rest on a record the owner_private profile does not authorise) |
| CONFLICTED (19) | 19 CONFLICTED |
| ORDER_UNSUPPORTED (9) | 9 ORDER_UNSUPPORTED |
| NEGATIVE_UNSUPPORTED (6) / NEGATIVE_SUPPORTED (7) | 6 / 7 correct |
| SUPPORTED (154) | 97 SUPPORTED, **57 withheld as UNSUPPORTED**, 0 wrong state |
| HISTORICAL (24) | 13 HISTORICAL, **11 withheld** |

So every error the selective policy is meant to prevent is absent here (no unsupported value, no resolved conflict, no invented ordering, no absence claim), and the cost is recall: 97 of 154 supported and 13 of 24 historical atoms are answered, so **68 of 178 supported or historical atoms (38%) are withheld**; criterion 2 (false abstention) is where this will be tested. The misses are concentrated and explained by design choices, not tuned away:
- `attends` (10): attendance comes from a structured speaker list (the C3 route), not from sentences; B-1 reads text only.
- `reviews` (13): value kind "text" (a free phrase like "the Sluice settings") has no typed extractor; B-1 supports typed kinds only.
- `runs_on` 13, `retry_limit` 9, `retry_limit_history` 11, `test_fixer` 8, `default_model` 2, `support_hours` 2: the subject is named in an earlier sentence of the same section or in a different record than the value ("Jobs flow through the Gantry scheduler. A failed job is retried up to 3 times"). Reading across sentences needs coreference; B-1 does not guess it.
Two small, general extensions were made while examining these, both covered by tests: the record title may supply the subject when the sentence names no other subject, and a relation can declare that its sentences naturally name two entities.

## 4. Limits

- **Generalisation is unproven.** Typed extraction by cue and value pattern works on templated invented text; real records are free text. B-1 prefers withholding to guessing, so the failure on real data is expected to be recall, not leaks, but that is a prediction. Held-out relations have no spec and are withheld with `no_relation_spec`.
- **Relation specs are caller-supplied.** The offline check derives them from the gold annotations (circular, disclosed). No production spec table exists.
- **Recall cost is large on the invented corpus** (38% of supported and historical atoms withheld). The design's criterion 2 (false abstention) is where this will show up; the later options are cross-sentence section context, structured attendee input, and typed-text kinds, each a separate decision.
- **Ambiguity policy** is "caveat, never assert"; the stricter "withhold the whole claim" is not implemented.
- The decomposer is a simple clause splitter; mis-typing falls back (never refuses) but its error rate is unmeasured on a labelled set.
- Authorisation here is an input (`AuthDecision`). Wiring it to the real access rules is integration work that is not approved.

## 5. Decisions requested
1. Whether to extend B-1 for the recall gaps in section 3 (section context, structured attendee input, typed-text kinds) before any further evaluation, or to evaluate the current conservative form first.
2. Whether the caveat-on-ambiguity policy is acceptable or the stricter withhold policy is wanted.
3. Whether a labelled decomposition set should be built (deterministic parts only) before any model stage.
