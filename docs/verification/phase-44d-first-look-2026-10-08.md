# Phase 44D first look at the frozen holdout, 2026-10-08

Decision point `44D-first-look` (owner decision D12). B1a and B1b were **frozen before scoring** ([freeze record](../../services/companion-core/benchmarks/knowledge_retrieval/results/44D-first-look-freeze.json), committed and pushed as `0117c6e` first), then scored **once each** on the locked 44-case holdout (fixture hash `deca72b3ed08...`, unchanged). B1c was excluded. Nothing was tuned against the results; a repeat for this decision point is refused by the harness and a test checks the log. The comparison is **retrieval only**: no model wrote or judged an answer. The corpus is synthetic and small and its labels are provisionally reviewed; these figures are not evidence of real-world quality, and 36 cases with expected sources is a coarse instrument.

Both systems ran on the production-embedding track (one index build, real all-MiniLM-L6-v2; B1a does not use the vectors), against the recorded baselines on the same track. Every result was revalidated against the stores under the case's trusted `AccessContext` before scoring.

## Results (holdout, 44 cases, 36 with expected sources)

| System | R@3 | R@5 | R@10 | P@5 | MRR | attribution@5 | citation@5 | full recall@5 (Wilson 95%) | exposed (cases) | proposed | latency p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `b0` today's lookups | 0.22 | 0.25 | 0.31 | 0.14 | 0.30 | 0.26 | 0.40 | 5 of 36 (0.06 to 0.29) | 30 (21) | n/a | 8.2 / 9.4 ms |
| `b0-oracle` (keyword overlap over everything) | 0.70 | 0.84 | 0.90 | 0.36 | 0.72 | 0.46 | 0.76 | 27 of 36 (0.59 to 0.86) | 104 (17) | n/a | 8.2 / 9.1 ms |
| **B1a** lexical | 0.75 | 0.83 | **0.96** | 0.29 | 0.67 | 0.48 | 0.79 | 25 of 36 (0.53 to 0.82) | **0 (0)** | 0 | 6.3 / 15.0 ms |
| **B1b** lexical + vectors, RRF | 0.76 | **0.86** | 0.94 | 0.30 | **0.75** | 0.47 | 0.81 | 27 of 36 (0.59 to 0.86) | **0 (0)** | 0 | 29.1 / 92.6 ms |

("exposed" is unauthorised hits that reached the caller; "proposed" is unauthorised candidates the search produced before revalidation. Neither retrieval configuration produced any; the baselines have no access control.)

**Authorization.** 0 unauthorised hits exposed by either system, 0 stores modified by retrieval, 0 hits outside the corpus, both action-boundary probes delivered their instruction and changed nothing. B1a and B1b both pass every security gate. (The pre-filter was on, as it will be in use; the development comparison showed revalidation alone holds when it is off.)

**Other measures.** Temporal accuracy 1 of 3 (B1a) and 2 of 3 (B1b): the stores carry no supersession data, so this is the text alone. Both return something for all 4 no-answer questions. Pooled element recall@5: 52 of 67 (B1a), 54 of 67 (B1b). Mean context returned: 133 and 154 tokens (the oracle returns about 257). Python CPU per query: 4.5 ms (B1a), 85.6 ms (B1b, of which 14.2 ms is embedding the query); peak resident memory of the benchmark process 568 and 570 MB (both load the embedding model to build the index).

### By category (R@5, cases fully recovered)

| Category | B1a | B1b | `b0-oracle` |
|---|---|---|---|
| single-source (6) | 1.00, 6 of 6 | 1.00, 6 of 6 | 1.00, 6 of 6 |
| cross-source (10) | 0.88, 7 of 10 | 0.85, 6 of 10 | 0.88, 7 of 10 |
| relationship (10) | 0.50, 2 of 10 | 0.63, 5 of 10 | 0.75, 6 of 10 |
| temporal (4) | 1.00, 4 of 4 | 1.00, 4 of 4 | 1.00, 4 of 4 |
| contradiction, provenance, security (2 each) | 1.00 | 1.00 | 1.00, 0.50, 0.50 |

## Paired case-level differences (b minus a, 36 cases with sources)

| Comparison | Mean R@5 difference (bootstrap 95%) | Better / worse / tied | Sign test p | Mean MRR difference (95%) | Full recall@5 only b / only a, McNemar p |
|---|---|---|---|---|---|
| B1b minus B1a | +0.028 (-0.037 to +0.107) | 3 / 2 / 31 | 1.0 | +0.076 (+0.005 to +0.152) | 3 / 1, p = 0.63 |
| oracle minus B1a | +0.014 (-0.097 to +0.111) | 7 / 3 / 26 | 0.34 | +0.051 (-0.073 to +0.177) | 4 / 2, p = 0.69 |
| oracle minus B1b | -0.014 (-0.125 to +0.093) | 5 / 4 / 27 | 1.0 | -0.025 (-0.133 to +0.083) | 3 / 3, p = 1.0 |
| `b0` minus B1a | -0.579 (-0.708 to -0.444) | 0 / 28 / 8 | below 0.001 | -0.374 | 0 / 20 |
| `b0` minus B1b | -0.607 (-0.736 to -0.472) | 0 / 28 / 8 | below 0.001 | -0.450 | 0 / 22 |

B1b is better than B1a in three cases (H-R4, H-R6, H-R8, all relationship) and worse in two (H-C5, H-R1); the other 31 are identical. Only the MRR difference between B1b and B1a has an interval that excludes zero, and only just; nothing else separates the two. Both are far above today's lookups, whose recall they exceed in 28 of 36 cases and never fall below.

## Development to holdout

R@5 on the development split was 0.86 (B1a), 0.79 (B1b) and 0.74 (oracle); on the holdout 0.83, 0.86 and 0.84. The ordering of B1a and B1b reversed, which is what a gap this small looks like under a change of cases, and the oracle moved most. The development split informed how the configurations were built, so it was always an optimistic and noisy guide; the holdout is the less biased figure, and neither is large.

## Lexical versus hybrid, from development cases only

`b1_investigate.py` (it loads only the development split; a test checks that) traces the two cases where B1b's top five lost a source B1a kept ([results](../../services/companion-core/benchmarks/knowledge_retrieval/results/44D-dev-lexical-vs-hybrid.json)):

- **D-S1** ("What does Priya Nair prefer for updates?"): the memory that answers it is lexical rank 1 but vector rank 40. Three segments of the 140-segment weekly sync, whose filler lines are generic, are lexical ranks 2 to 4 and vector ranks 1 to 3. Reciprocal rank fusion rewards agreement between lists, so each of those outscores the memory (found strongly by one list only) and it falls to rank 8.
- **D-C1**: the meeting segment is lexical rank 4 and vector rank 37, and falls to fused rank 8 behind items both lists like.

So the hybrid's cost is an artifact of rank fusion plus filler text that matches many short queries semantically; its gain (MRR) comes from the same mechanism in the other direction, promoting items both lists agree on. Neither is evidence about real data, whose repetition and phrasing differ, and the investigation changed nothing: both configurations remain exactly as frozen.

## What this does and does not support

- A unified index with PostgreSQL full-text ranking recovers as much as keyword overlap over every source (and more than 3 times today's lookups) with **no exposure of unauthorised content**, at 6 ms median. That is the robust result, and it holds on development and holdout alike.
- Whether adding vectors is worth it is **not settled**: a small, borderline MRR gain and a possible small recall gain against 5 times the median latency, 19 times the CPU and the need to keep the embedding model resident. The data neither supports nor rules out hybrid.
- The weakest category for both is relationship (alias and indirect references): B1a recovers 2 of 10 fully, B1b 5, the keyword oracle 6. This is where an entity or alias mechanism could matter, but per the plan it is investigated only if error analysis shows alias resolution is the cause and simpler remedies (lexical aliases, query expansion) fail; that analysis has not been done and no entity work was started.
- Not evaluated: generated answers, real data, abstention on weak matches (all systems return something for every no-answer question), recency or supersession.

## Remaining acceptance gates for 44D

Production activation of retrieval (not started, needs its own decision and the context builder, 44E); answer-quality evaluation (no harness); a decision on whether hybrid justifies its cost; an owner review of the benchmark labels (provisional).
