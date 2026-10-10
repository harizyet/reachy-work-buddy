# Phase 44: dev16 freeze recommendation and operational-readiness report (2026-10-10; for owner decision)

**Status: recommendation only. Nothing was frozen, dev16 was not accessed, opened, hashed or run, and the P0 baseline was run only on consumed dev15 cases in the development smoke test. This page stops for the owner's explicit approval before any freeze or run.** Inputs: the accepted infrastructure at commit `09bba8fcfaf460cb27448d8ba0069076e937ac9f` ([execution checklist](phase-44-dev16-execution-checklist.md)), the [smoke-test record](verification/phase-44-dev16-p0-smoke-test-2026-10-10.md), the [preflight](phase-44-dev16-preflight.md). No independent human validation is claimed anywhere; reviewer A is the pipeline author and reviewer B is unassigned.

> **Later update:** the corrected P0 smoke test passed and the freeze command, recommended freeze commit and remaining limitations are in [phase-44-dev16-freeze-command.md](phase-44-dev16-freeze-command.md), which supersedes the next-steps list below.

> **Update after the R1–R3 corrections (owner-approved and verified 2026-10-10): this page is now the FINAL FREEZE-READINESS RECOMMENDATION.** The blocking defect (caveat 1: P0 retrieval not reproducible across database builds) is **cleared by evidence**: the hypothesis was confirmed in isolation and the benchmark builder now assigns stable record ids; two independent builds of the identical frozen corpus give identical ordered evidence, evidence manifests and prompt hashes in 865 of 865 question-and-profile comparisons, while the random-id negative control fails as a blocker ([correction record](verification/phase-44-dev16-p0-reproducibility-correction-2026-10-10.md)). Caveats 2 and 3 are resolved (environment pinned and recorded; offline mode with fail-closed missing dependencies). Caveat 4 (a quiet model server) remains an operating condition. Because the fix changes which tied records reach the P0 prompt in 513 of 865 preparations compared with an uncorrected build, **one more small development-only model smoke test is recommended before the freeze (not run; needs your approval).** Seed **16044** is approved. Reviewer B is **not assigned**; no independent-human-validation claim is made. The freeze commit and date are to be chosen after verification; dev16 is not authorised to be opened, frozen or run. The original sections below are kept as written; read them with this update.

## 1. Are the runner and the P0 path operationally ready for a one-shot evaluation?

| Part | Verdict | Basis |
|---|---|---|
| guarded runner (guards, authorisation, lock and ledger, immutability, failure handling, packets, evaluation) | **Ready** | 79 infrastructure tests; the synthetic end-to-end CLI rehearsal (including a SIGKILLed child process and a mock service that fails mid-run); the same guards ran for real in the smoke test (verify, run, duplicate-run refusal, packets, evaluate) |
| deterministic candidate arm | **Ready** | frozen, hash-checked; per-case authorisation reproduces the frozen default on dev15 and fails closed for restricted profiles |
| P0 real path (PostgreSQL retrieval, access context, prompt assembly, 7B inference, citation recording, output parsing) | **Operational, with four recorded caveats** | completed 10 of 10 on the first attempt in 34 s; every row follows the declared schema; no retrieved record outside its access profile; effective configuration equals the declaration |
| criterion computation and statuses | **Ready** | all three outcomes (ACCEPTED, NOT ESTABLISHED, REJECTED) reproduced on synthetic data; bounds verified |
| human adjudication | **Not ready** | reviewer B unassigned (section 4) |

**Caveats on the P0 path (details in the smoke-test record, section 4):**
1. **Retrieval is not reproducible across database builds.** Two fresh builds of the same corpus gave identical ordered evidence in 2 of 10 cases and identical sets in 5 of 10; against the dev15 pilot, 0 of 8 ordered and 3 of 8 sets, with 1 of 8 identical replies. Probable cause: equal-rank ties are broken by `ref_key`, which embeds store ids assigned at build time. So the formal P0 is **one draw** that depends on the build.
2. The run provenance does not yet record the database image digest and version, the build helper `kbench/pg_env.py` is not in the pinned source list, and the served model's full identity is not captured.
3. Loading the cached embedding model contacts the Hugging Face Hub.
4. The 7B is the homelab's live server; the formal run should be on a quiet server.

## 2. Corrections recommended before the freeze (each needs your approval; none is applied)

| # | Change | Why | Cost | Effect on frozen items |
|---|---|---|---|---|
| R1 | record DB image digest, `version()`, the `/v1/models` payload in provenance; pin `kbench/pg_env.py` | caveat 2 | small, no behaviour change | changes `dev16_p0.py`, the P0 declaration and the proposed manifest (regenerated) |
| R2 | `HF_HUB_OFFLINE=1` during `RealP0Executor.open()`, restored in `close()` | caveat 3 | trivial | same |
| R3 | **either** (a) accept caveat 1 and pre-register P0 as one draw with its per-case evidence reported, **or** (b) derive store ids deterministically from logical record keys in the benchmark builder `kbench/pg_env.py` (harness only, not production code) and require the retrieval-only probe to show identical ordered evidence across builds | caveat 1 | (a) none; (b) small, but must pass the probe | (b) changes the pinned build helper; the candidate, evaluator, thresholds and rules are untouched either way |

**Recommendation:** approve R1 and R2; choose **R3(b)** if you want a reproducible baseline (verify with the existing probe on consumed data first), and keep R3(a)'s statement in the report regardless, because the model's own replay noise (about 5%) remains. If you prefer no further change, the freeze can proceed as the infrastructure stands, with caveat 1 stated in every P0-relative result.

## 3. The prospective seed 16044

Proposed as the single seed of the formal evaluation, fixed now, before any dev16 content is seen: the shuffle of the blinded P0 packet, the choice of the 20% candidate control sample, the order of the criterion-6 packet and the choice of its 30 control claims (`manifest.seed`). The smoke test used the same value only to choose its dev15 cases. Changing the seed after the freeze is not permitted; a different seed means a new manifest and a new owner decision.

## 4. Semantic-review limitations (distinct from the engineering readiness above)

- **Reviewer A is not independent.** The pipeline author (an AI coding assistant) wrote the candidate, the relation definitions, the label rubric, the review tooling and every manual judgement so far. Reviewer B is **unassigned**. Without B, no P0-relative status can carry an independence claim, criterion 6 cannot credit any adjudicated claim (it passes only if the mechanical figure already does), and agreement (kappa, target 0.80) cannot be computed. The report will say "single reviewer, NOT independent" in that case.
- **Blinding is partial.** The candidate's code-written replies are recognisable by their wording; protection comes from atom-level labels against a stated gold and from the control sample, not from concealment.
- **Labels are not a validated instrument.** The lexical scorers failed validation and are research-only; the eight-label scheme is defined and lossless on the candidate's own flags (dev15), but its use on free-text P0 replies is untested for inter-rater reliability.
- **Criteria 4 and 10** use the evaluator's mechanical `fully_correct` (which includes its registered-source citation check); adjudication changes criterion 6 only.
- **Criteria 7 to 9** may well be INDETERMINATE: they need 29 independent facts each, and dev15 offered 19, 6 and 9 atoms. Zero events with too few opportunities is not evidence of safety.
- **The two arms differ in clock and authorisation machinery** (declared, not changed) and the candidate's phrasing generalisation on unseen questions is unmeasured; dev16 is the first independent measurement.
- **The P0 comparison inherits caveat 1** (one retrieval draw) and the 7B's replay noise.

## 5. Recommended freeze sequence (every step needs your approval; none has been done)

1. Decide R1, R2, R3 and name reviewer B (or decide to proceed single-reviewer with the limitations above).
2. Apply the approved corrections, regenerate `dev16_p0_config.json` and the proposed manifest, re-run the tests and a retrieval-only probe on consumed data; commit.
3. Quiet the model server; confirm `candidate_freeze.py --check`, `verify_declared()` for P0 and candidate, and a clean working tree at the freeze commit.
4. Build the real manifest with `dev16_runner.build_manifest` (this is the first moment dev16 files are hashed and their ordered ids read), seed **16044**, the freeze commit, purpose `dev16-acceptance`; review its hashes against the proposal.
5. Write the single-use authorisation (purpose `dev16-acceptance`, bound to the manifest hash and run id), set `AQ_DEV16_APPROVAL`, run `verify`, and stop for your explicit go-ahead.
6. `run --execute` once into `dev16_acceptance_runs`; then `packets`, independent labelling by A and B, `evaluate`; report all ten statuses, mechanical and adjudicated criterion 6 side by side, every failure by case id; stop.

## 6. Decisions requested

1. Approve R1 and R2 (yes/no).
2. R3: (a) accept and pre-register, or (b) deterministic benchmark database ids with a verifying probe.
3. Name reviewer B, or decide to run single-reviewer with the limitations in section 4.
4. Approve seed 16044 and the freeze sequence; set the freeze commit and the date.
5. Separately, authorise the formal freeze and the formal run (neither is authorised by this page).
6. Approve committing and pushing the smoke-test record, its evidence and this page (uncommitted now).

## 7. Final freeze-readiness recommendation (after R1–R3)

| Item | State |
|---|---|
| runner, one-shot guards, packets, evaluation | ready (unchanged; 105 infrastructure tests including the end-to-end CLI rehearsal) |
| candidate arm | ready and frozen |
| P0 retrieval reproducibility | **ready**: identical across independent builds (865 of 865), negative control fails, access enforcement and provenance checks pass |
| P0 environment pinning and recording | **ready**: image digest required and docker-verified, PostgreSQL/pgvector versions, embedding revision and weights hash, offline mode, the `/v1/models` response, all in `p0_environment.json` |
| P0 end to end with the real model after the correction | **one small development-only smoke test recommended** (10 consumed cases, about 35 s); everything except the live 7B call has been exercised with a mock service |
| human adjudication | **not ready**: reviewer B unassigned; any status that needs two reviewers will be INDETERMINATE or single-reviewer and labelled "NOT independent" |
| semantic limits | unchanged: partial blinding, unvalidated label instrument, possible INDETERMINATE for criteria 7 to 9, unseen phrasing unmeasured |

**Recommended next steps, each needing your explicit approval:** (1) the small model smoke test of the corrected executor; (2) naming reviewer B, or the decision to proceed single-reviewer; (3) choosing the freeze commit and date; (4) separately, authorising the formal freeze and, later, the formal run. Operating conditions for the formal run: a disposable PostgreSQL container with its image digest exported as `AQ_PG_IMAGE_DIGEST` and the container name as `AQ_PG_CONTAINER`, `KBENCH_DATABASE_URL` pointing at it, the embedding model already cached, and a quiet model server.
