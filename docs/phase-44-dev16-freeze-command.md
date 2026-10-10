# Phase 44: final freeze recommendation, freeze command and manifest procedure for dev16 (prepared 2026-10-10; NOT EXECUTED)

**Status: prepared for owner approval. Nothing below has been run against dev16. dev16 and bank D have not been read, listed, hashed or opened; the formal P0 baseline has not been run; no freeze exists.** Based on the passed [corrected P0 smoke test](verification/phase-44-dev16-p0-smoke-test-corrected-2026-10-10.md), the [R1–R3 correction record](verification/phase-44-dev16-p0-reproducibility-correction-2026-10-10.md) and the [execution checklist](phase-44-dev16-execution-checklist.md). Seed **16044** is approved prospectively and recorded. Reviewer B is **unassigned**; no independent human validation is claimed.

## 1. Recommended immutable commit

The runner refuses to start unless `HEAD` equals the manifest's commit and no tracked file in the manifest has changed, so **no commit may be made between the freeze and the run**, and the freeze commit must already contain everything.

- **Content baseline (verified):** commit `9fa658f3a0159e31cb98b5198d14a94f88e754b9`. Every file the manifest lists is byte-identical at that commit and in the working tree now (hashes in the smoke-test record, section 3), and a fresh clone of it reproduces the candidate-freeze check, the P0 and candidate declaration checks and 175 infrastructure tests.
- **Recommendation:** freeze at **the commit that adds the corrected-smoke-test evidence and records on top of `9fa658f`**, i.e. once you approve committing and pushing them (they are uncommitted: this decision did not authorise a commit). That commit changes only documentation, evidence and unlisted helpers, so the manifest's listed files stay identical to `9fa658f`; prove it at the freeze with `git diff --name-only 9fa658f HEAD` (it must list no file the manifest names) and `candidate_freeze.py --check`. Freezing at that commit keeps the smoke-test evidence inside the immutable history the formal run points to. If you prefer not to add a commit, `9fa658f` itself is a valid freeze commit, but the smoke evidence then stays untracked.
- **The SHA of that commit does not exist yet.** It will be reported when you approve the commit; the manifest records whatever `HEAD` is when the helper runs.

## 2. Preconditions at the freeze (all must hold; check them in this order)

```bash
git rev-parse HEAD                              # the chosen freeze commit, pushed to origin
git status --short --untracked-files=no         # must print nothing
git diff --name-only 9fa658f HEAD               # must name no file listed in the manifest (docs/evidence only)
python3 services/companion-core/benchmarks/answer_quality/selective/candidate_freeze.py --check     # "candidate freeze intact"
python3 - <<'E'
import sys; sys.path.insert(0, "services/companion-core/benchmarks/answer_quality/selective")
import dev16_p0 as p0, dev16_candidate_arm as ca
assert p0.verify_declared() == [] and ca.verify_declared() == [], "a pinned input drifted: regenerate and re-review before freezing"
print("declarations match the code")
E
```

Also: no author has read dev16; the model server is quiet; the disposable PostgreSQL container exists, its image digest is exported as `AQ_PG_IMAGE_DIGEST`, its name as `AQ_PG_CONTAINER`, and `KBENCH_DATABASE_URL` points at it; the MiniLM model is cached (the run is offline and fails closed otherwise).

## 3. The freeze command (builds the manifest; the first moment dev16 files are hashed and parsed)

```bash
python3 services/companion-core/benchmarks/answer_quality/selective/dev16_make_freeze_manifest.py \
  services/companion-core/benchmarks/answer_quality/cases_dev16.json \
  dev16-acceptance \
  services/companion-core/benchmarks/answer_quality/selective/dev16_acceptance_runs/FREEZE \
  <BANK_D_FILE_1> <BANK_D_FILE_2> ...
```

The helper (`dev16_make_freeze_manifest.py`, validated on consumed dev15 data only) refuses if any tracked file is modified, records `HEAD` as the commit, **seed 16044**, purpose `dev16-acceptance`, the case count and the hash of the ordered case ids, and hashes **22 files plus the bank files**: the candidate manifest, `evaluator.py`, **`aq/scoring.py`**, the corpus, the dev16 cases, the P0 and candidate configurations, the criterion-6 rules, the runner, the P0 module, the candidate arm, the criteria and criterion-6 modules, the P0 adjudication tool, `deterministic_criteria.py`, `i2b_eval.py`, the benchmark database builder `kbench/pg_env.py`, the embedding module, the two probes, the synthetic fixtures and the proposal tool. It writes `dev16_acceptance_runs/FREEZE/manifest.json` (an untracked file, so it does not move `HEAD`) and prints the manifest sha256, which you record. The bank D file names are for you to supply; they are not named here because bank D has not been opened.

Review the manifest against `ACCEPTANCE_FREEZE_PROPOSAL.json` (every proposed hash must appear unchanged), then stop for your decision.

## 4. The single-use authorisation (created by the owner, not by the assistant)

Save as `dev16_acceptance_runs/FREEZE/authorization.json`, with the manifest hash printed above and a run id:

```json
{"decision": "AUTHORIZE_ACCEPTANCE_EXECUTION", "manifest_sha256": "<manifest sha256>", "run_id": "dev16-acceptance-1",
 "authorized_by": "<owner>", "authorized_at": "<UTC time>", "expires_at": "<UTC time, a few hours later>",
 "single_use": true, "p0_model_calls_authorized": true, "purpose": "dev16-acceptance"}
```

An authorisation with another `purpose`, another manifest hash or another run id is refused, is consumed only by a run that starts, and cannot be reused.

## 5. Verify, then the one-shot run (each a separate owner go-ahead)

```bash
export KBENCH_DATABASE_URL=<disposable server URL> AQ_PG_CONTAINER=<container> AQ_PG_IMAGE_DIGEST=<image digest>
export AQ_DEV16_APPROVAL=$PWD/services/companion-core/benchmarks/answer_quality/selective/dev16_acceptance_runs/FREEZE/authorization.json
F=services/companion-core/benchmarks/answer_quality/selective/dev16_acceptance_runs
python3 services/companion-core/benchmarks/answer_quality/selective/dev16_runner.py verify --manifest $F/FREEZE/manifest.json --root . --runs-root $F --run-id dev16-acceptance-1   # "all guards pass", no calls
python3 services/companion-core/benchmarks/answer_quality/selective/dev16_runner.py run    --manifest $F/FREEZE/manifest.json --root . --runs-root $F --run-id dev16-acceptance-1 --execute   # ONE SHOT
```

On `REFUSED`: nothing was run; fix the cause, re-verify. On `ABORTED`: stop; no rerun, no resume; owner decision. Afterwards: `dev16_runner.py packets` and `evaluate` (commands in the checklist), independent labelling by A and B, report all ten statuses with the mechanical and adjudicated criterion 6 side by side and every failure by case id, then stop.

## 6. Where seed 16044 is recorded

In the manifest (`seed`), copied into the run's `provenance.json`; it drives the shuffle of the blinded P0 packet, the choice of the 20% candidate control sample, the order of the citation packet and its 30 control claims. It is also recorded in `ACCEPTANCE_FREEZE_PROPOSAL.json` and was the seed of the smoke test's case selection. Changing it after the freeze needs a new manifest and a new owner decision.

## 7. Remaining acceptance limitations (read before approving)

1. **Reviewer independence.** Reviewer A is the pipeline author (an AI coding assistant); reviewer B is unassigned. Without B: no independent-validation claim, no kappa, criterion 6 can credit no adjudicated claim (it passes only if the mechanical figure already does), and P0-relative statuses are labelled "single reviewer, NOT independent". Even with B, partial blinding remains (the candidate's templated wording is recognisable) and the label instrument is not independently validated.
2. **Insufficient qualifying independent opportunities for criteria 7 to 9 is a real risk.** Each needs at least **29 distinct facts** for a zero-event result to bound the rate at 10%. On the consumed dev15 data the candidate offers only **16 independent conflict facts (19 atoms), 3 negative-unsupported facts (6 atoms) and 9 ordering facts**. If dev16 resembles dev15, criteria 7, 8 and 9 will be INDETERMINATE and the overall verdict **NOT ESTABLISHED regardless of every other result**. I cannot know dev16's composition (it has not been opened); you could ask its generator's plan for the number of distinct conflict, negative and ordering facts **before** deciding to freeze, so the owner is not surprised, without exposing any question or content.
3. **Criteria 4 and 10** use the evaluator's mechanical `fully_correct` (including the registered-source citation check); adjudication changes criterion 6 only.
4. **P0 is one draw.** Retrieval is now reproducible, but a single P0 run still carries the 7B's replay noise (about 5%, from earlier replays; at temperature 0 and seed 44 the model behaved deterministically given the prompt in the 10-case smoke sample), and it runs on the live homelab model server (use a quiet one).
5. **Unseen phrasing is unmeasured** (the decomposer's own sets are author-written); the two arms differ in clock and authorisation machinery (declared); the candidate's withholding rules (decision is not a deployment, relative time quoted, unsupported "serves" documents) cost false abstentions that count against criterion 2.
6. **Not exercised:** the formal run itself, and a run with the real `run` command on dev16-shaped data beyond the 10-case smoke tests.

## 8. Decisions requested

1. Approve committing and pushing the corrected-smoke-test evidence and records, and choose that resulting commit as the freeze commit (or keep `9fa658f`).
2. Name reviewer B, or decide to proceed single-reviewer with the limitations above.
3. Decide whether to learn dev16's count of distinct conflict, negative and ordering facts from its generator's plan before freezing (limitation 2).
4. Supply the bank D file names for the manifest, and choose the freeze date.
5. Separately authorise, in order: the freeze (section 3), then the authorisation file (section 4), then the run (section 5). None is authorised by this page.
