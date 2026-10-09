# Phase 44: selective answering, Stage A record (2026-10-12; nothing deployed, no response policy implemented)

Owner direction, 2026-10-12 (after dev14): *approve selective-answering Stage A only: a synthetic sub-claim corpus generator with unambiguous gold labels, gold annotations, a deterministic sub-claim scorer, scorer validation and adversarial tests, a development-set protocol and a separately frozen one-shot acceptance protocol. No new production response policy. Stop after Stage A and report.* Production is unchanged: Qwen2.5-7B, 44H boundary active, indexing/retrieval/shadow off, 44F not implemented. Protocols are in [the selective-answering protocol](../phase-44-selective-answering-protocol.md#12-stage-a-development-set-protocol-dev15) sections 12 and 13.

All code is under `services/companion-core/benchmarks/answer_quality/selective/` (new files only; no frozen manifest file changed, `freeze_check.py` passes for dev8, dev10, dev12, dev14). The pilot ran the production 7B (`reachy-local`) on the invented corpus only, in the isolated scratch Postgres, with no owner data.

## 1. Corpus design

- `corpus_gen.py` (seed 14) generates corpus v4 and a **fact registry** (`facts_v4.json`) that is the single source of truth: every record text and every gold label derives from it, and `check_unique` rejects two established facts for one subject and relation (the dev12 defect). Held-out relations (`release_day`, `escalation_contact`, `approver`) and held-out projects (juniper, pinnacle, thistle, umbra) are reserved for the acceptance candidates.
- `questions_gen.py` builds **atoms** (sub-claims) with gold status SUPPORTED, UNSUPPORTED, CONFLICTED, HISTORICAL, NEGATIVE_SUPPORTED, NEGATIVE_UNSUPPORTED, ORDER_UNSUPPORTED (an ordering or supersession assertion with no dated basis), a severity (severe for a specific person, number, day, month, model, host or hours value, or an absence/ordering claim) and a family: control_supported, control_unsupported, mixed, multipart, conflict, unknown_actor, negative, temporal.
- Outputs: `atoms_v4.json`; `cases_dev15.json` (design, 173 questions, 154 supported + 88 unsupported + 24 historical + 19 conflicted + 7 + 6 negative + 9 order sub-claims); `cases_dev16.json` (acceptance **candidates**, 218 questions, held-out relations/projects/unseen bank D; **not frozen**).
- **A confound found and removed by the pilot.** The context builder labels a document with its retrieval date (2026-10-09), so "document vs memory" conflicts looked like an ordering to the model and to me. Conflicts and ordering atoms are now built from same-day memory pairs (`standup`, `review_day`); doc-vs-memory pairs are excluded. This changed bank D after it was hashed: the original `bank_d.sha256` (commit bd050ec) stays; `bank_d_unchanged.sha256` proves every other relation is byte-identical to bd050ec; `bank_d_additions.sha256` hashes the replaced `order_figure` and the added `standup`/`review_day` texts, written after the scorer and pilot but before any use of the bank on a model. That is a disclosed amendment; bank D has not been run on a model.
- Registry ambiguity: none. Template overlap (sibling relations sharing a cue word): 9 pairs flagged and listed in `coverage_report.py`; the scorer's subject/cue tie logic is what keeps them apart, and they are a named scorer risk (section 3).

## 2. The deterministic scorer

`scorer.py` scores each atom from the reply text, clause by clause, plus the manifest of evidence ids (existence and authorisation of every cited id, and citation fidelity where a source is required). Per atom flags: stated, identified (said not established/unknown/undated), leaked, severe, both/one_sided/resolved (conflicts), as_current (historical), false_abstention, absence_claim, invented_order, wrong_value (a different value of the right kind), plus blanket refusal per question and `fully_correct` per question. No model is used. The scorer was written before the pilot; it was then amended after reading pilot replies (section 3), which makes the post-fix numbers in-sample.

## 3. Scorer reliability

| Check | Result | Caveat |
|---|---|---|
| 49 hand-labelled and adversarial cases (`scorer_cases.py`, `validate_scorer.py`) | 94/94 flag decisions = 100% after fixes; 98.9% before the pilot-driven fixes, with one documented limit | cases authored by the scorer's author; limit now closed |
| Pilot adjudication: 64 sampled atom outcomes from the 7B's real replies (`adjudication_sample.json`), judged by the author from the status definitions (`adjudication.json`) | **first-pass scorer 439/448 flag decisions = 98.0%** (5 of 64 items with any miss); **post-fix 512/512 = 100%** | single rater, who also wrote the scorer; the post-fix number is **in-sample** (the fixes were made on these items) and is an upper bound |

Defects found by adjudication and fixed: a value's own name counted as "another entity"; "does not have a staging environment" read as unknown; single-atom clause ties; blanket refusals; "no X mentioned/recorded" phrases; anaphoric follow-up clauses; wrong values of the right kind not flagged. **Honest reading: real-output agreement is about 98% before fitting and the fitted figure is not evidence of 100%.** Recommendation before freezing: a fresh adjudication of at least 100 outcomes from pilot replies on a **new** sample (including 25 from the held-out candidates), ideally with a second rater (the owner reading 30 replies, as offered earlier), and no scorer change afterward.

Remaining scorer risks: sibling relations with overlapping cue words (9 flagged pairs), speculative clauses ("probably X") judged by pattern, replies that restate the question, and negation scope.

## 4. Failure taxonomy (production 7B, dev15, scorer after fixes; design data, not an acceptance result)

173 questions per arm. **B1a** = baseline retrieval evidence; **oracle** = gold sources only (separates retrieval from capability).

| Failure | B1a | Oracle | Reading |
|---|---|---|---|
| Fully correct questions | 91/173 | 142/173 | |
| Unsupported sub-claim leaked (UNSUPPORTED) | 24/88 (27%), all severe | 0/88 | retrieval-driven: related-sibling values are asserted; oracle removes it |
| Invented ordering/supersession (ORDER_UNSUPPORTED) | 8/9 | 1/9 | the model orders undated pairs ("was updated from Tuesday to Friday") when shown both |
| Absence claim without basis (NEGATIVE_UNSUPPORTED) | 4 leaked, 3 absence claims of 6 | 0 of 6 | silence read as absence under B1a |
| Conflict: both values stated | 4/19 | 9/19 | **capability limit**: with perfect evidence the 7B still gives one side in 9 of 19 |
| Conflict: false abstention | 7/19 | 0 | |
| False abstention on SUPPORTED | 24/154 (16%) | 12/154 (8%) | the cost a selective policy must not increase |
| Wrong value of the right kind (SUPPORTED/HISTORICAL) | 12 | 5 | |
| Blanket refusal of a question that has a supported part | 14 | 12 | |
| Bad or unauthorised citations | 0 / 0 | 1 / 0 | |

By family (fully correct, B1a → oracle): multipart 4/25 → 19/25, unknown_actor 9/25 → 18/25, conflict 4/19 → 9/19, temporal 9/21 → 19/21, mixed 23/30 → 25/30, negative 9/13 → 13/13, controls 17/20 and 16/20 → 20/20 and 19/20. Reading: **evidence selection** is the main cause of leaks, multipart failure and unknown-actor failure; **model capability** is the main cause of one-sided conflicts and of false abstention on supported parts (12 even on oracle evidence). A response policy can therefore address leaks, invented ordering and absence claims, but conflict presentation and blanket refusal need a mechanism that changes what the model sees or is asked, not only which records are shown.

## 5. Are the ten criteria measurable, and is coverage adequate?

Measured by `coverage_report.py` (counts of **distinct** atoms, since repeated phrasings of one atom are not independent), with Wilson and zero-event bounds (`evaluator.py`):

| Criterion | Operational form | Verdict (dev15 design / dev16 candidates) |
|---|---|---|
| 1 unsupported −30%, no severe increase | paired count of leaked UNSUPPORTED + ORDER + NEGATIVE_UNSUPPORTED atoms; severe counted separately | measurable: baseline 36 leaks on 88+9+6 atoms (design) |
| 2 ≤1 added false abstention and ≤3 pp | paired count on SUPPORTED/HISTORICAL atoms | measurable; baseline 24/154 (16%) so 3 pp is about 5 atoms |
| 3 supported recall ≥90% of baseline | ratio of stated rates | measurable |
| 4 ≥80% of mixed questions keep supported info | mixed-family rate | **weak**: 30 / 38 questions, 95% lower bound at 80% observed is 63–64%; recommend a bound-based form ("point estimate ≥80% and not worse than baseline by a paired test") |
| 5 zero bad/unauthorised citations | count | measurable |
| 6 ≥95% citation fidelity | fidelity over cited factual atoms | needs a floor on cited atoms (fidelity is "None" when nothing is cited); recommend a stated minimum denominator |
| 7 no unsupported conflict resolution | count of resolved conflicts | **underpowered**: 16 / 24 distinct conflict atoms; zero events only bounds the rate below 19% / 14% |
| 8 no absence claim from retrieval failure | count | **inadequate**: 3 / 4 distinct atoms; zero events bounds the rate below 56% / 49% |
| 9 no invented temporal supersession | count | **weak**: 9 / 10 distinct order atoms; bound 30% / 28% |
| 10 ≤1 net loss of fully correct answers | paired net | measurable; "fully correct" defined at question level with all sub-claim flags |

## 6. Changes proposed for owner approval (nothing applied)

1. **Criteria 7, 8, 9**: either enlarge the world (more projects/relations to reach at least 30 distinct atoms each, about a 10% zero-event bound) or restate them as "zero events **and** the stated upper bound is reported", so a pass is not read as proof of safety.
2. **Criterion 4**: bound-based form as above.
3. **Criterion 6**: minimum denominator (suggest 40 cited factual atoms) and report fidelity as not evaluable below it.
4. **Date semantics rule**: a document's displayed date is its retrieval date; only same-day memory pairs and records with explicit "as of" text count as dated evidence. Recorded in the corpus design; owner to confirm.
5. **"Fully correct"** is defined at question level: every atom ok, no blanket refusal, no bad citation.
6. **Scorer freeze**: fresh adjudication (section 3) before dev16 is frozen; no scorer edit after it.
7. **Baseline for comparison**: B1a with the 44H boundary as deployed (the pilot's baseline), plus the revised C1+C2 as an experimental comparator; C1, C2, C3 each switchable.

## 7. Readiness for implementing the selective-answering mechanism

Ready: corpus, gold labels, scorer (98% agreement before fitting), evaluator, coverage tool, development protocol. Not ready: **dev16 is not frozen**; criteria 7–9 lack coverage, the scorer needs a fresh adjudication, and the owner has not fixed the amended criteria. Because 12 supported-part false abstentions and 9 one-sided conflicts remain on **oracle** evidence, a mechanism that only filters or labels evidence cannot reach criteria 2 and 7 on its own; dev14 already showed labelling is not a trust boundary, so the design must separate **discovery evidence** from **admissible answer evidence** (what the model may state), not just mark records uncitable. No mechanism is implemented. Decisions requested are listed in the protocol, section 13.

## 8. Artifacts

`results/pilot-dev15-7b.json` (first-pass scores stored with the replies), `selective/adjudication.json`, `selective/adjudication_sample.json`, `selective/*.sha256`. Tests: `tests/test_selective_stage_a.py` (10 passing), `validate_scorer.py`. Ruff clean for `services shared`.
