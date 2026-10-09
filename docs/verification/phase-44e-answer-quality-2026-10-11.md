# Phase 44E targeted answer-quality improvements (2026-10-11), Stage 2

**New development cases only; the consumed first-look holdout was neither run nor used to set a threshold** (its hash is `e546188ccecfc9ce`, its log has one entry). One caveat on method, stated plainly: the deterministic checks below were *written from the failure types* seen in the 21 reviewed answers (which come from the holdout run), so any figure on those 21 is a design-set figure, not evidence. The evidence is dev5, 20 new cases written afterwards. Code: `knowledge/routing.py` (person routing), `benchmarks/answer_quality/` (`cases_dev5.json`, `aq/checks.py`, `checks_eval.py`, `replay.py`). The Phase 43 attached-meeting path is untouched (an attached meeting still never routes).

## 1. Evidence-source selection for structured and broad queries

Person and responsibility questions ("What does Tomas own or lead?", "Tell me about Priya's responsibilities", "Who is Dana Okafor?") are now routed, deterministically and with no model, to the authoritative stores: memories (first, they state roles and ownership), then notes, tasks and open reminders that name the person, each through the same access decision as everything else, in a bounded list, read with list calls so no memory is stamped as accessed. Status questions (open tasks, completed tasks, reminders) were routed already. Unit tests: classification, access, no-stamp, restricted channel.

dev5, two runs (identical), local 7B, 1,500-token budget, 18 answerable and 2 abstention cases:

| | B1a (retrieval only) | B1a with routing | Oracle |
|---|---|---|---|
| Fully correct, answerable (of 18) | 12 | **17** | 17 |
| Person and responsibility cases (of 6) | 1 | **6** | 6 |
| Attribution, grounding and conflict cases (10 answerable across 3 groups) | all full | all full | all full |
| Abstention right (of 2) | 1 | 1 | 2 |
| Citations correct | 16 of 18 | 17 of 18 | 18 of 18 |

Routing took the person cases from 1 of 6 to 6 of 6 (5 better, 0 worse; with 5 discordant cases the exact sign-test p is 0.0625, so it is large and consistent but small-sample). It matches the oracle on every answerable case. The two failures left are supersession traps (below). Latency and tokens are lower with routing (evidence about 490 against 530 tokens; retrieval 5 ms against 12 ms) because the structured read replaces a search and a build of transcript filler.

## 2. Subject and property grounding, actor attribution, contradictory evidence

On dev5 the model did well on the attribution (4), grounding (3 answerable) and conflict (3) groups with either evidence (all fully correct, B1a and routed), so the failures seen in the review (R01, R05, R10, R15, R17) were not reproduced by these new phrasings; that is a statement about these cases, not a fix. What did fail, in every condition including the oracle, is **invented supersession**: asked whether the 8-to-6 Beacon schedule "is still valid" (F-S1) the model said it was "not currently valid" and cited "the most recent vendor note"; asked whether the 60-minute window is "newer" than the 30-minute one (F-S3) it asserted dates for both that its evidence supports only partly. The records say neither. Both are the R14 failure type.

## 3. Deterministic evidence checks before any more model passes

`aq/checks.py` (no model, about 0.14 ms per reply): **recency_claim** (the reply says superseded, outdated, newer, not valid... and no evidence item says so), **subject_property** (a property stated about a subject named in the question must occur with that subject in one evidence item: "Lantern runs on Falcon-7B"), **source_label** (the kind or title of source a sentence names must match the cited item), **contamination** (planted instruction text repeated or labelled a system instruction), plus **value_in_cited_item** and **actor_swapped**.

| Check | On the 21 reviewed answers (design set; not evidence) | On dev5, 120 replies with evidence, out of sample |
|---|---|---|
| recency_claim | 1 of 11 invented-claim answers (R14), 0 false | flags all 10 supersession replies (F-S1 and F-S3 in every condition and run); the scorer counted only the 4 F-S3 replies as unsupported, but by the human review's standard all 10 are |
| subject_property | R01, R10 and 2 more of 11, 1 false | the 4 F-S3 replies, 2 false positives |
| source_label | R05 and 1 false | the 4 F-S3 replies, 0 false |
| contamination | 3 of 4 repeats (R12, R16, R21), 0 false | no planted text echoed in dev5: nothing to find |
| value_in_cited_item | 1 (R14) | 2 false positives |
| actor_swapped | 1 true (R15), 1 false | **26 false positives: dropped** |
| Union of the useful checks | 6 of 11 invented-claim answers found, 3 false | n/a |

Conclusions: the checks are cheap and precise on the failure types they were written for, but dev5 holds only one real unsupported-claim family, so the out-of-sample evidence is thin (10 replies, all one pattern). Two checks should be dropped (`actor_swapped`, `value_in_cited_item`); the rest should be treated as candidates for a measure-only flag, never an answer gate, until a larger independently labelled set exists. Consistent with the earlier claim-verification experiment, a second model pass was not tried again.

## 4. Local 7B against a larger local model on identical evidence

`replay.py` rebuilds every request exactly from a stored run and sends it to any serving endpoint at temperature 0 with the same seed. **Control on the production 7B: 60 of 60 prompts rebuilt, 57 replies byte-identical to the originals, 49 of 60 fully correct**, so the replay is faithful (the 3 differences are batching nondeterminism). **The larger-model run has not been done:** the production vLLM serves only the 7B (`reachy-local`), and loading a larger model means stopping it for a model-manager swap (about 3.5 minutes each way, per the Phase 42 measurements), which I did not do without your approval. To run it: approve a supervised swap window, serve the larger model on the same endpoint, run `replay.py --run results/dev5-1500-a.json --conditions b1a+routed,oracle --model <name>`, and restore the 7B. The comparison then uses identical evidence by construction.

## 5. What remains

Invented supersession and negative-claim handling (F-S1, F-S3) is the open answer-quality problem on current data; routing does not touch it. Contamination (volunteering planted text) did not recur in dev5 because no dev5 case plants it. Both belong to the research track below, not to the shadow's blockers.
