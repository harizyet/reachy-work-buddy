# Knowledge retrieval benchmark (Phase 44)

Measures how well a retrieval system finds the right evidence across Reachy's memories, documents, meetings, notes, tasks and
reminders, and whether it respects access rules. Method and gates: [Phase 44, section 7](../../../../docs/phase-44.md).
It measures **retrieval only**: no model writes or judges an answer, so retrieval quality and model quality are never mixed.

```bash
cd services/companion-core/benchmarks/knowledge_retrieval
../../../../.venv/bin/python run.py --validate-only          # check the fixtures
../../../../.venv/bin/python run.py --adapter b0 --split dev # JSON report on stdout (or --out FILE)
../../../../.venv/bin/python run.py --adapter b0-oracle --split holdout --decision-point 44A-baseline
../../../../.venv/bin/python run.py --adapter b0 --split dev --embedder minilm  # the production-embedding track
../../../../.venv/bin/python review.py --out FILE.md  # case-by-case review of recorded results; runs nothing
```

## What is here

| File | Purpose |
|---|---|
| `corpus.json` | The synthetic world: 13 memories (one forgotten, one expired, one superseded, one sensitive), 5 documents (one archived older version, one sensitive, one with a planted instruction), 4 meetings (one 140 segments long so Phase 43 excerpt selection engages, one with a spoken instruction, one sensitive, one with an accepted ASR correction), 4 notes, 4 tasks, 2 reminders, five access profiles and the entity aliases. Everything is invented. |
| `cases_dev.json` | 25 development cases: inspect and iterate freely. |
| `cases_holdout.json` | 44 frozen cases (10 cross-source, 10 relationship, 6 single-source, 6 security, 4 temporal, 4 negative, 2 contradiction, 2 provenance). Never used for tuning. |
| `fixtures.lock.json` | The hashes of the frozen fixtures. A test fails if a fixture changes; changing the holdout starts a new baseline. |
| `holdout_runs.jsonl` | Every holdout scoring: decision point, system, fixture hash, results digest. A decision point gets one look. |
| `results/` | The recorded 44A reports: `44A-baseline-*` (synthetic track, dev and holdout) and `44A-production-embedding-*` (dev only). |
| `review.py`, `review_rationale.json` | The case-level review generator and the reviewer's rationale for each holdout case (not part of the frozen fixtures). The generated review is in [docs/verification](../../../../docs/verification/phase-44a-holdout-case-review-2026-10-08.md). |
| `kbench/` | The harness: `fixtures.py` (loading, validation), `corpus.py` (fresh in-memory stores), `adapters.py` (interface and baselines), `scoring.py` (pure metrics), `security.py` (leakage, canaries, action-boundary probes), `report.py`, `holdout.py`. |

Cases were written from the corpus before any improved retrieval existed, then fixed. A fixture check refuses to run if a case
cannot be answered from the corpus (every expected fact must appear in its expected sources), if an id or question repeats across
splits, or if the holdout loses the minimum size the entity-expansion rule needs (D9). The corpus, cases and baselines were all
written by the same agent that built the harness. **The labels are provisionally reviewed, pending independent inspection by the owner**,
and the results are measurements on a synthetic corpus, not evidence of real-world retrieval quality.

## Case format

`question`; `access` (a profile: ceiling, project scopes, destinations, private channel); `attached_meeting` (the Phase 43 flow);
`temporal` (`current` or `include_historical`); `expected_refs`; `expected_facts` (strings the expected sources contain, for a
later answer-level check); optional `stale_refs` (superseded facts that must not outrank the current one), `forbidden_refs` (with a
reason), `injection_canaries` (planted text to detect) and `contradiction`. A reference is `type:id[#part]` (a document chunk
index or a meeting segment index); without a part it means any part of that source.

## Metrics (as defined in the report)

- **recall@k** (3, 5, 10): expected references found in the top k, divided by the number expected; macro-averaged over cases that
  expect something. Repeats count once.
- **precision@k**: relevant hits in the top k divided by the hits actually returned there (0 if none). A system is neither
  rewarded for returning less nor punished for having fewer than k.
- **MRR**, **source attribution@5** (share of top hits from a needed source), **citation correctness@5** (share of expected
  references that name a part found with exactly that part).
- **full recall@5** and **pooled element recall@5**, each with a Wilson 95% interval. Full recall counts a case only if every
  expected reference is in the top 5; the pooled figure treats each expected reference as one trial and is optimistic because
  trials in a case are correlated. Read intervals, not point values: with 10 cases a category is a coarse measure.
- **temporal accuracy**: the current fact is in the top 5 and no superseded one outranks it. **Negative false-positive rate**:
  share of no-answer questions where the system returned anything at all.
- **Leakage (exposed)**: a hit the system returns to the caller or model that is forgotten, expired, above the profile's sensitivity ceiling, outside its project scope, or
  local-only (any meeting) when the profile may reach the cloud, plus anything the case lists as forbidden. The rules come from
  the fixtures and the 44A access functions, not from the system under test.
- **Injection**: whether planted text was returned (allowed: it is data) and, separately, **action-boundary probes** that run the
  existing Phase 43 and Phase 13 flows with a model that obeys any instruction it is shown, then check that no task, memory,
  note, meeting, email draft or receipt changed. A probe only counts if the instruction was really delivered.
- **Read-only**: every store is fingerprinted before and after each case; a retrieval that changes one is flagged. Known read-side
  effect: `MemoryStore.recall` stamps `last_accessed`; it is excluded from the fingerprint and reported separately.
- **Context size** (estimated tokens returned) and **retrieval latency** p50/p95 (host load average is in the report; use it with
  care).

A system with a filtering stage can return `Retrieval(exposed, candidates)`. Only what it exposes is gated; the report also counts
unauthorized *candidates* and how many a filter rejected before exposure, as a diagnostic about retrieval. A plain list is treated as
exposed and reports no candidates.

Gates (`security_gates` in the report) apply to candidate systems from B1 on: zero leakage, zero injection-driven actions, no
store modified, no unknown hits. The B0 baselines are reported, not gated, and are expected to leak because they have no access
control.

## Systems

- `b0`: today's behaviour. Each existing lookup is called with the question as its query: `MemoryStore.recall`,
  `DocumentStore.search` (top 3) and, only when a meeting is attached, Phase 43's `relevant_lines`. Notes, tasks and reminders have
  no free-form lookup today and unattached meetings are not searched.
- `b0-oracle`: a ceiling for today's mechanisms, not shipped behaviour. The same lookups once per content word, every source, every
  meeting treated as attached, ranked by Phase 43's word-overlap measure.

## The PostgreSQL configurations (44D)

`b1a` (full-text), `b1b` (full-text + pgvector, reciprocal rank fusion), `b1c` (b1b + cross-encoder rerank of the authorised survivors)
and the `-nofilter` variants (access pre-filter off, so revalidation alone is what keeps unauthorised rows out). They build the corpus into
a fresh database on the server in `KBENCH_DATABASE_URL` (or `DATABASE_MIGRATION_TEST_URL`; disposable, with pgvector), index it with the
real worker, retrieve, revalidate under the case's access profile and score. The report adds `system` (stage latencies, Python CPU,
peak memory, query-embedding time, revalidation drops by reason, index build time) and reports unauthorised *candidates* separately from
*exposed* hits. **They refuse the frozen holdout** until `KBENCH_HOLDOUT_APPROVAL` names an approved decision point (`44D-first-look` scored `b1a` and `b1b` once each; `compare.py` gives paired case-level differences and `b1_investigate.py` explains differences from development cases only). `b1_sensitivity.py`
checks the hybrid against its two free parameters on the development split only.

```bash
DATABASE_MIGRATION_TEST_URL=postgresql://... python run.py --adapter b1a --split dev
DATABASE_MIGRATION_TEST_URL=postgresql://... python run.py --adapter b1b --split dev --embedder minilm
```

## Tracks

- `synthetic-deterministic` (default, `--embedder hashing`): document scores use a deterministic bag-of-words embedding, so runs are
  reproducible and need no download. Its digest covers ranked keys and scores.
- `production-embedding` (`--embedder minilm`): the same fixtures and systems with the app's real document embedder
  (`all-MiniLM-L6-v2`), scored with exact in-memory cosine (identical ranking to pgvector, checked by an opt-in test). A real
  model's float scores can differ slightly across machines, so its digest covers ranked keys only.

The tracks are reported and logged separately (the holdout log keys on track as well as decision point) and their scores are never
combined. The holdout has been scored once on each track: decision point `44A-baseline` (synthetic) and `44A-production-embedding-baseline`
(production). Both are recorded in `holdout_runs.jsonl` and `results/`.

## Adding a system (44B onward)

Implement `kbench.adapters.RetrievalAdapter`: `load(built)` over the freshly built stores, and `retrieve(case, profile)` returning
ranked `Hit(key, text, score)` with logical keys. Register it in `ADAPTERS`. It must not modify the stores, and a system that
enforces access should use `profile`. Dev runs are free; a holdout run needs a new `--decision-point`.

## Reproducibility

No runtime randomness. The seed (44) only ordered the filler lines of the long meeting when the fixture was written; the file is
the artifact. A report's `results_digest` covers hits, ranks, scores, leaks and probe outcomes (not timings) and must be identical
for two runs over the same fixtures (tested in-process and across processes).

## Growing the holdout

The 44 cases are a first gate. Larger and harder sets are added as new fixture versions that start new baselines, never as edits
to this one: paraphrased questions, ambiguous entities, noisy ASR transcripts, distractor documents that are related but wrong, and
redacted real questions with the owner's approval.

## Limits

The corpus is small, synthetic and keyword-friendly: the oracle baseline already reaches most single-source and cross-source
cases, so headroom is mostly in relationship, provenance and security cases, and an improvement here does not prove one on real
data. Counts are small; use the intervals. No answer-quality evaluation exists yet (the cases carry `expected_facts` for it).
