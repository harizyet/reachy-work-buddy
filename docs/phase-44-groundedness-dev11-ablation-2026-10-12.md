# Phase 44 groundedness: dev11 ablation of components C1 to C5 (2026-10-12; design data, local, nothing deployed)

Design: [phase-44-groundedness-milestone-design.md](phase-44-groundedness-milestone-design.md). This is **development evidence on invented corpus v2 with the production 7B** (temperature 0, seed 44, 1,500-token budget, scorer v2), 50 cases (33 answerable), every arm on identical retrieval and an identical prompt shell. dev11 was used to design and tune the components, so none of the numbers below is an acceptance result; the acceptance set is dev12, which was authored but is **not frozen, not run**. Production is unchanged.

## What was built (all experimental, not wired into any answer path)

`companion_core/knowledge/grounding/`: **C1** `propositions.py` (+ the written lexicon `relations.py`), **C2** `answerability.py`, **C3** `routes.py` (attendees from the meeting record), **C4** `claims.py` (JSON-schema atomic claims, deterministic rendering), **C5** `validate.py` (source identity, authorization recomputed from the access rules, exact evidence span with offsets computed by code, supported relation; an empty or trivial quote never supports a claim). 12 unit tests (`tests/test_grounding_components.py`) include seven seeded invalid citations that C5 must reject (an id not in the turn, an unauthorised item, an empty quote, a trivial quote, a fabricated quote, a claim that joins two sentences, a relation the quote does not state). The harness is `run_g.py` with `aq/conditions_g.py` and `aq/llm_json.py`; `analyze_g.py` prints the tables and the owner's guardrails.

## Component-level results with no model (design pool: 252 generated design questions; `g_design_eval.py`)

- **C1:** records shown 9.1 -> 3.3 and **non-gold records shown 8.1 -> 2.5**; gold sources present in what is shown 155/192 against 161/192 for B1a's top 10 (six cases lost to the filter; that is the recall cost).
- **C2 (null generator):** unestablished questions detected **70/76**; answerable questions wrongly called unestablished **11/176 (6%)**; conflicts detected 23/28 (5 false conflicts). Known failure families: the possessive/modifier reading of "the Cedar lead's vacation" (6 mis-established), the `decision` relation (8 mis-unestablished), and host questions across archived records (5 false conflicts). The alias between a system and its project is recovered per query from record scopes (a per-query alias, not a graph); it recovered most of the 12 conflict misses it produced when absent, so the "graph needed" trigger of the design (alias joins as the dominant miss) has **not** fired.
- A stricter variant (any discriminating question word absent from every candidate blocks an assertion) detects 76/76 but wrongly flags 47/176 (27%) answerable questions, so it is not used.

## End-to-end ablation on dev11 (7B)

| Arm | fully correct /50 | unsupported claims | false abstention (answerable) | answerable fully correct /33 | better / worse vs baseline | all five guardrails |
|---|---|---|---|---|---|---|
| **B0 baseline (B1a)** | 31 | 8 | 2 | 21 | | |
| C1 re-rank only | 31 | 8 | 2 | 21 | 1 / 1 | no |
| C1 filter | 33 | 8 | 2 | 23 | 2 / 0 | no (no fewer unsupported claims) |
| C2 note | 34 | 7 | 2 | 22 | 4 / 1 | no (no specific correction) |
| C2 deterministic reply | 33 | **0** | **8 (+6, +18%)** | 16 | 7 / 5 | no (guardrails 2, 3, 4) |
| C3 attendee route | 32 | 8 | 2 | 22 | 1 / 0 | no |
| C4 atomic claims, no validation | 30 | 7 | 3 | 20 | 1 / 2 | no (6 accepted citations fail C5) |
| C4 + C5 | 24 | 7 | 9 | 14 | 1 / 8 | no |
| **C1 filter + C2 note** | **35** | **7** | 2 | **25** | 4 / **0** | **yes (all five)** |
| C1 filter + C2 deterministic reply | 35 | 0 | 9 | 18 | 9 / 5 | no |
| C1 filter + C2 reply + C3 | 36 | 0 | 8 | 19 | 10 / 5 | no |
| full stack (C1 + C2 reply + C3 + C4 + C5) | 34 | 0 | 9 | 17 | 10 / 7 | no |
| oracle evidence | 43 | 2 | 2 | 26 | 15 / 3 | |
| oracle + C4 (+ C5) | 36 | 3 | 1 | 22 | 10 / 5 | |

## What it says (dev11 only; no component is claimed better on this evidence)

1. **C1 filter + C2 note is the only arm that meets all five owner guardrails on dev11:** two more fully correct answers than C1 alone and four more than baseline, no regression, no added false abstention, one unsupported answer corrected without a blanket refusal. The effect on unsupported claims is small (8 -> 7), because a note does not make the 7B abstain.
2. **A deterministic reply for UNESTABLISHED removes every unsupported claim (8 -> 0) but costs 6 to 7 false abstentions (18 to 21 percentage points of answerable questions), mostly two-part questions and historical questions where C2 calls part of the question unestablished.** It fails guardrails 2 and 3 as built. This is the central trade-off the milestone was designed to expose: the safety gain exists, and the price is exactly the conservatism the owner asked to bound. A refinement that answers the established part and abstains only on the missing part (the PARTIAL policy) is the obvious next experiment and has **not** been built or tuned.
3. **C3** helps narrowly as predicted (one attendee question).
4. **C4/C5 do not help this 7B.** Constrained JSON generation costs correctness even on perfect evidence (oracle 43 -> 36), because the structure displaces the specifics some answers need and the rendered "I don't have a record that establishes..." line reads as an abstention to the scorer. C5 itself behaves as designed at claim level: on the model's 37 raw claims, 31 were valid and the 6 it rejected were all "the maximum message size is unknown, citing E1"-type claims that should have been `unknown` entries; with C5 off, those 6 would have been accepted with citations that do not support them (guardrail 5 fails without C5, passes with it). No claim with a nonexistent or unauthorised source was accepted in any arm with C5.
5. **Oracle evidence is not perfect on corpus v2 either** (43/50, 2 unsupported): about 7 of the 19 non-correct baseline answers are generation failures that evidence selection cannot fix.

## Frozen for the acceptance set (no further tuning of any component)

C1 to C5 as committed with this record; the arms pre-registered for dev12: B0; C1 filter; C2 note; **C1 filter + C2 note**; C1 filter + C2 note + C3; C1 filter + C2 deterministic reply + C3 (reported as the high-conservatism variant); C4 + C5; oracle and oracle + C4 + C5 for context. The acceptance reading is the owner's five guardrails, applied per arm, plus the transparency requirements. See [the dev12 protocol](phase-44-groundedness-dev12-protocol.md).
