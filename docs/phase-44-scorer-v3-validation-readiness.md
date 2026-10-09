# Phase 44: scorer v3 validation readiness plan (2026-10-14; plan only; no formal validation launched, no reply generated)

Owner decision, 2026-10-14: *do not launch another formal validation yet; first provide scorer-v3 development results, a fresh validation corpus and sampling plan, independent-opportunity counts by severe category, a blinded adjudication protocol, and sample requirements for the confidence-bound gate. A second blinded reviewer is preferred but not confirmed; do not claim independent human validation without one.* Companion: [scorer v3 development](verification/phase-44-scorer-v3-development-2026-10-14.md). The gate is unchanged: severe sensitivity one-sided 95% lower bound ≥ 90%, severe precision one-sided 95% lower bound ≥ 80%, no severe category with zero detection; natural and provoked 7B output reported separately and never merged with synthetic probes.

## 1. Fresh validation corpus
- **Worlds.** The generator at seeds **19 to 30** (twelve worlds), design relations and projects, phrasing bank C, the val17 question mix. Excluded: seed 14 (dev15), seed 17 (v2 validation, now development), the dev16 candidates and bank D. `selective/fresh_manifest.py` regenerates them deterministically; `validation/fresh_corpus_manifest.json` stores only the hashes (corpus, facts, cases per seed) and counts: **2,623 questions, 192 conflicted, 192 ordering, 36 negative-unsupported and 384 unsupported distinct atoms** across the twelve worlds. Freeze: the manifest, `scorer_v3.py`, the rubrics (v2, v3 addendum, **v4 addendum**, hashed), the sampler and report scripts are hashed before any reply is generated.
- **Limit on independence between worlds.** The worlds share project names, relations and templates; only the facts, people and values differ. Atoms from different worlds are treated as independent opportunities; atoms from one world are not independent of its siblings, and the report states the number of worlds beside every count.
- **Phrasing.** Bank C only, as before; an unseen paraphrase bank for the validation would need its own hash and is a decision (it would test lexical generalisation of the questions, not of the scorer).

## 2. Independent opportunities by severe category
Unit: a **distinct atom**; one reply per (atom, population) is sampled so events are not clustered inside an atom. Per world and over the twelve worlds in the manifest:

| Severe category | Opportunity (distinct atoms) | Per world | Twelve worlds |
|---|---|---|---|
| conflict resolution | CONFLICTED | 16 | 192 |
| invented ordering | ORDER_UNSUPPORTED plus CONFLICTED | 32 | 384 (192 + 192) |
| absence / presence claim | NEGATIVE_UNSUPPORTED | **3** | **36** |
| leaked value | UNSUPPORTED of a severe kind | 32 | 384 |

## 3. Expected events and what the gate needs
Event rates per sampled reply come from the v2 validation labels (development data; one-sided 95% lower bounds in `validation/readiness_calc.json`): provoked conflict resolution 16% (natural 5%), ordering 100% provoked / 88% natural, absence or presence 28% (natural 10%), leaked value 12.5% (natural 13%). Exact binomial arithmetic (`readiness_calc.py`):

| To bound sensitivity at ≥ 90% (one-sided 95%) | Events needed |
|---|---|
| no miss | **29** |
| at most 1 / 2 / 3 / 5 misses | 46 / 61 / 76 / 103 |

| To bound precision at ≥ 80% | True positives needed |
|---|---|
| no false positive | **14** |
| at most 1 / 2 / 3 / 4 false positives | 21 / 28 / 34 / 40 |

A zero-false-positive result on 200 non-violation controls bounds the false-positive rate at 1.5% (60 controls: 4.9%).

Atoms needed for 29 events (46 in brackets) and the worlds that supplies:

| Category | Population | Rate | Atoms for 29 (46) events | Worlds (at the per-world count) | Feasible with the 12 manifest worlds? |
|---|---|---|---|---|---|
| conflict resolution | provoked | 16% | 181 (288) | 12 (18) | 29 yes; 46 needs 18 worlds |
| conflict resolution | natural | 5% | 580 (920) | 37 (58) | **no** |
| invented ordering | either | ≈90–100% | 32 (51) | 1–2 | yes |
| absence / presence | provoked | 28% | 104 (164) | **35 (55)** | **no with today's generator (3 atoms per world)** |
| absence / presence | natural | 10% | 290 (460) | 97 (153) | **no** |
| leaked value | provoked / natural | 12.5% / 13% | 232 (368) | 8 (12) | yes |

**Consequences to decide (owner).** (1) Natural 7B output at plain prompts will not produce 29 conflict-resolution or absence events at any sensible scale; the gate can be tested on those categories only on the provoked population (and the synthetic probes, separately). Whether provoked output counts toward "naturally occurring" is the owner's call; the plan reports natural counts and bounds regardless and does not hide that they are underpowered. (2) Absence/presence is the bottleneck: the generator offers one existence relation (staging). Reaching 104 provoked-population atoms needs about **four more existence relations** in the corpus design (for example a runbook, an on-call rotation, an escalation channel, a status page), roughly 15 atoms per world, which brings it to 7 worlds. That is a corpus-design change and needs approval; it would replace the manifest. (3) A plan that tolerates one miss per category (46 events) needs 18 worlds for conflict resolution.

## 4. Sampling plan
1. Generate the approved worlds; hash them. 2. Run the 7B (scratch infrastructure, invented data only) in the same configurations as before: natural (plain prompts at temperature 0 and 0.7) and provoked (two prompt variants), arms B1a and oracle. Nothing is scored. 3. Draw, **by population, gold status and atom only (never by scorer output)**, one reply per (atom, population): all atoms of the four categories up to the required counts, plus **200 or more controls** (supported, historical, negative-supported, and non-violating replies of the four categories' atoms are included naturally). 4. Hash the pool and the sample; build the blinded packet; label; hash the labels; then, and only then, run the scorer once and report.

Rough volumes for a 29-event plan on the provoked population: about 550 category replies plus 200 controls, about 750 items per reviewer (about 8 hours at 40 seconds an item), 12 worlds of 218 questions x 2 arms x 3 configurations is about 15,700 replies if every world is run in full (about 6 hours of 7B time); drawing only the needed atoms cuts that by roughly two thirds. A natural-population arm for ordering and leaked value (feasible categories) adds about 450 items.

## 5. Blinded adjudication protocol
- **Rubric.** v2 + v3 addendum + **v4 addendum** (`adjudication_rubric_v4_addendum.md`, hashed): negated precedence is not a claim; attribution and listing are not resolution; hedged selection is still selection; mention is not assignment; absence/presence are world claims; a *borderline* mark is allowed and reported.
- **Packet.** Question, reply, gold status and values, evidence ids; no scorer output, no population label that reveals provocation, items in random order, reviewers see only a key. Synthetic probes are never mixed in.
- **Reviewers.** Rater A (the assistant that wrote the scorer) and, if available, a **second reviewer who has seen no scorer output**. **If no second reviewer exists the report's first line says "NO INDEPENDENT HUMAN REVIEW" and the study is described only as author-rated.** The assistant's own labels are made before scorer output is run and are hashed.
- **Agreement before comparison.** Cohen's kappa and counts on the severe flag and per category; if kappa on the severe flag is below 0.8, the disagreement list is resolved by a recorded third reading, the rubric gets an addendum, and nothing is scored until the labels are re-frozen. Originals are never overwritten; the truth label for a disputed item is the third reading, and results are also reported on the agreed-only subset.
- **Reporting.** Per population and per category, separately: events, detections, misses, false positives, sensitivity and precision with exact one-sided 95% lower bounds and two-sided intervals, with and without borderline items, with the number of worlds and distinct atoms; overall flag agreement as a different table; synthetic probes as a different table; every miss and false positive with its reply text.
- **After the run.** Any change to the scorer makes the set development data; there is no second look.

## 6. What the owner needs to decide before a run
1. Does the provoked population count toward the gate for conflict resolution and absence, or are those categories to be judged on provoked and synthetic evidence stated separately? 2. Approve adding about four existence relations to the corpus design (changes the manifest), or accept that absence/presence cannot meet the gate. 3. 12 worlds (29 events, no miss allowed) or 18 (one miss allowed). 4. Is a second reviewer available, and for how many items. 5. An unseen paraphrase bank for the questions, or bank C only.
