# Phase 44: P0 reproducibility correction (R1 provenance, R2 offline assets, R3 deterministic retrieval), 2026-10-10

**Status: bounded infrastructure correction, verified without any model call. Consumed dev15 data and the frozen invented corpus only; disposable databases; dev16 was not accessed, frozen or run; the formal P0 baseline was not executed; the deterministic candidate, the evaluator, the thresholds, the criterion-6 rules and every earlier frozen artifact are unchanged; nothing was deployed and no production retrieval, indexing or shadow was activated. No independent human validation is claimed; reviewer B is unassigned.** Triggered by the owner's decision after the [development smoke test](phase-44-dev16-p0-smoke-test-2026-10-10.md) (which is preserved unchanged), which recorded retrieval nondeterminism as a blocking pre-freeze defect. Evidence: `services/companion-core/benchmarks/answer_quality/results/dev16-p0-reproducibility/` and `dev16-p0-mocked-run/`.

## 1. R3 first: the random-ID tie-breaker hypothesis, tested in isolation

Hypothesis: the lexical search orders results by `(rank DESC, ref_key)`; `ref_key` embeds the store id; the benchmark builder lets each store assign a **random** UUID (`uuid.uuid4()`) every time the disposable database is built; so records with **equal rank** change places between builds, and the tie that survives the result limit changes.

Probe (`dev16_p0_tiebreak_probe.py`): the frozen corpus is built twice into independent disposable databases and the search layer is queried directly (no model, no server) with all 173 consumed dev15 questions (limit 40). Predictions and results with the **unchanged** builder (`1_tiebreak_probe_BEFORE_random_ids.json`):

| prediction | result |
|---|---|
| P1 the multiset of scores is identical across builds | 173 of 173 |
| P2 the sequences differ only where scores are equal | 0 positions differ with unequal scores (3 apparent exceptions in the first run were an artifact of my own metric: an equal-score group truncated by the limit; the metric was corrected, not the data) |
| P3 inside every equal-score group each build's order is its own `ref_key` order | 173 of 173 |
| P4 fully contained tie groups have the same members in both builds | 173 of 173 |
| P5 a tie group straddling the limit can differ in membership | differs in 94 of 173 queries in the stored run (94 to 103 across the runs made) |
| observed | **165 of 173** queries return a different ordered list in the two builds in the stored run (165 to 168 across the runs made; random ids give a different answer every time); every one of the 173 queries has an equal-score group; store ids identical across builds: no |

**Hypothesis confirmed**: the difference is entirely inside equal-score groups, ordered by the build's random `ref_key`. Relevance scoring is identical across builds.

## 2. R3 correction (benchmark builder only)

`kbench/pg_env.py` gains an opt-in `stable` option for `build_pg_corpus` (default off, so every other benchmark behaves as before) and a context manager `stable_ids(logical_key)`: while a benchmark record is created, `uuid.uuid4()` returns `uuid5(namespace, "<logical key>#<n>")`, with n counting the calls for that record (documents and meetings make several). Record ids, and therefore `ref_key` and the tie-break, become a function of the corpus, not of the build. The database name still uses the random generator imported at module load. **Not touched:** the search query, relevance scoring, access-context enforcement, revalidation, evidence admission, the context builder, the deterministic candidate, the evaluator and all thresholds. The P0 executor's default (production) path builds with `stable=True`.

Verification:
- **Search layer, same probe, stable ids** (`2_tiebreak_probe_AFTER_stable_ids.json`): store ids identical across the two builds; **0 of 173** sequences differ; **0** differ at the limit; scores identical.
- **Full P0 preparation, two independent builds of the identical frozen corpus** (`3_reproducibility_two_stable_builds.json`, `dev16_p0_reproducibility.py`): every one of the 173 dev15 questions under every one of the 5 access profiles (865 comparisons) through the pinned `GConditions2.prepare('b1a', ...)`: **0 differences** in the ordered evidence (real ids and logical keys), in the evidence manifests and dropped counts, and in the sha256 of the assembled messages (the prompt contents); 0 access-profile violations in either build; every evidence reference resolves to its store; all store ids are `uuid5` and identical across builds. All 173 questions contain an equal-score tie in their top ten, so the comparison exercises ties. A **duplicate-content fixture** (the frozen corpus plus six identical-text records with different ids, scopes and sensitivities) is retrieved in the same order, with the same ids, in both builds, and the duplicates really tie.
- **Negative control** (`4_negative_control_random_ids.json`, the same probe with random ids): it reports **BLOCKER** and exits non-zero, with 519 of 865 comparisons differing in the ordered evidence and in the prompt hash, store ids and duplicate order not reproducible. So the probe can fail, and the pass above is not vacuous.
- No model call and no model-server contact: the token budget used an offline deterministic counter, the same function of the text in both builds, so build-to-build identity is unaffected.

## 3. R1: provenance and pinning

- **Pinned sources:** `kbench/pg_env.py` and `rag/embeddings.py` join the 13 files already hashed in the P0 declaration (`dev16_p0_config.json`, regenerated after the final code change); the proposed freeze manifest also lists the builder, the embedding module and the probes.
- **Declared and verified database image:** `AQ_PG_IMAGE_DIGEST` is **required** (a missing or malformed value fails the run) and, when `AQ_PG_CONTAINER` names the container, is verified with `docker inspect` of the container and of its image (a mismatch fails the run).
- **Recorded per run** as an immutable artifact `p0_environment.json` (written by the runner after the executor opens, listed in `ARTIFACTS.sha256`): the database image digest and verification status, `SHOW server_version`, `version()`, the pgvector extension version read from the server, the hash of `pg_env.py` as run, the embedding model name, **cache revision** and **weights sha256**, the offline flags in force, and the **actual `/v1/models` response**.

Example from the production-path rehearsal: PostgreSQL 16.15, pgvector 0.8.6, image `sha256:ccc6e83d...b4d6b` verified by docker, `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, weights sha256 `53aa5117...128d9db`.

## 4. R2: offline assets

`RealP0Executor.open()` (production path) sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, and switches the already-imported `huggingface_hub` constant, **before** anything loads the embedding stack; `close()` restores all three. A failed `open()` undoes everything before re-raising (tested: environment byte-identical afterwards). Dependencies must already be cached: `embedding_identity()` uses a local-only snapshot lookup, so a missing cache **fails the run** and nothing is downloaded. Tests: the real cached MiniLM loads in an isolated process with `socket.connect` made to raise: **0 connection attempts**; with an empty cache the same call fails closed with **0 attempts**. In the production-path rehearsal a socket guard recorded 100 connection attempts, all loopback (the mock service), **0 non-loopback**; libpq connections to the loopback database are below the Python socket layer and are not counted.

## 5. Production-path rehearsal with a mock model service (`dev16-p0-mocked-run/`)

The real runner, the real `RealP0Executor` default path (offline mode, image requirement and docker verification, real embedding load, a real PostgreSQL build with stable ids, real access-context retrieval and prompt assembly) and the real frozen candidate arm ran on the 10 smoke-test cases, with the model replaced by a disposable mock on 127.0.0.1 (the executor refuses any other target). Result: COMPLETE, 10 of 10 rows, 10 completions and 88 tokenizer calls to the mock, **no production inference**, environment restored afterwards (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `KBENCH_CORPUS` all as found). Two defects of mine surfaced here and were fixed before the evidence was produced: the first docker check asked a container for image digests (it has none; they are on the image), and a declaration changed without regeneration was refused by the guard, as designed.

## 6. Does the fix change actual P0 retrieval or prompt contents? Yes, exactly in the tie order, and a further small model smoke test is recommended (not run)

Compared with an uncorrected (random-id) build, the corrected path differs in **513 of 865** question-and-profile preparations (`5_versus_random_informational.json`): in the order of equal-rank records and in which tied record survives the ten-record cut, and therefore in the evidence block and the prompt hash of those cases. It does so because an uncorrected build's tie order was an arbitrary draw; the corrected build fixes one arbitrary order that is the same every time. Relevance, authorisation, admission, instructions and wording are identical. So the earlier smoke-test replies were one draw of a distribution; the corrected path is a different, now reproducible, draw, and no earlier P0 reply is expected to match it case for case. **Recommendation:** one more small development-only model smoke test (the same 10 fixed consumed cases, about 35 seconds of the live 7B, a new manifest and a new authorisation) to confirm the corrected executor end to end against the real model; the retrieval and environment parts are already verified without a model. **No model call was made for this correction and none will be without your approval.**

## 7. Tests and baseline

- New: `tests/test_dev16_p0_environment.py` (12 tests: stable ids, pinned sources, image digest and docker verification, the environment artifact, offline set and restore, failed-open cleanup, offline load with zero connections, missing-cache fail-closed, and a database-backed test that two independent builds are identical while the random-id control is not; the last runs only when `KBENCH_DATABASE_URL` names a disposable server).
- Existing infrastructure tests (runner 33, criteria 22, configurations and dev15 rehearsal 9, CLI rehearsal 15, candidate freeze 3) pass unchanged.
- Full-suite result and the comparison with the clean-checkout baseline are in the final report below the commit.

## 8. What is uncommitted/changed and what is untouched

Changed: `kbench/pg_env.py`, `dev16_p0.py` and its regenerated declaration `dev16_p0_config.json`, `dev16_runner.py` (writes `p0_environment.json`), `dev16_synthetic.py` (mock `/tokenize`), `dev16_freeze_proposal.py` and the regenerated proposed manifest, regenerated rehearsal evidence. New: the probes, the production-path rehearsal, the tests, this record. **Untouched:** the frozen candidate (`candidate_freeze.py --check` passes), `evaluator.py`, `deterministic_criteria.py`, `i2b_eval.py`, the criterion-6 rules, the thresholds, the smoke-test record and evidence, all earlier frozen artifacts, `cases_dev16.json`, bank D.
