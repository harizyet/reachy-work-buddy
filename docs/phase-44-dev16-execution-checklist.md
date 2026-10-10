# Phase 44: dev16 acceptance infrastructure and final execution checklist (2026-10-10; for owner review)

**Status (updated after the owner's review): the guarded runner is approved in principle; formal acceptance execution is NOT authorised. Built and tested on synthetic fixtures, a disposable mock service and consumed dev15 data only. No production P0 inference, no dev16 access, freeze or run; the deterministic candidate and the evaluator are unchanged. A separate owner decision is required for formal execution.** This page implements the owner's "acceptance infrastructure preparation" decision and extends the [preflight](phase-44-dev16-preflight.md); where they differ, this page governs. Reviewer A is the pipeline author and is not independent; **reviewer B is unassigned; no independent validation and no kappa are claimed.**

## 1. What was built (all under `services/companion-core/benchmarks/answer_quality/selective/`, new files; none is in the frozen candidate manifest)

| File | Role |
|---|---|
| `dev16_runner.py` | the guarded one-shot runner, manifest verification, single-use authorisation, lock and ledger, immutable artifacts, blinded packet builder, evaluation; command line `inspect`, `verify`, `run`, `packets`, `evaluate` |
| `dev16_p0.py` + `dev16_p0_config.json` | the exact predeclared P0 configuration, a function that recomputes it from the code, the real executor (unexercised) and a replay executor |
| `dev16_candidate_arm.py` + `dev16_candidate_config.json` | the declared candidate configuration and the candidate arm as the runner executes it (frozen code, per-case authorisation) |
| `dev16_criterion6.py` + `dev16_criterion6_rules.json` | the locked citation-adjudication rules and their implementation |
| `dev16_criteria.py` | PASS / FAIL / INDETERMINATE per criterion over the unchanged evaluator |
| `dev16_freeze_proposal.py` + `ACCEPTANCE_FREEZE_PROPOSAL.json` | the proposed acceptance freeze manifest (includes `aq/scoring.py`) |
| `dev16_rehearsal.py` | the full runner on consumed dev15 data (evidence in `results/dev16-runner-rehearsal-dev15/`) |
| `dev16_synthetic.py`, `dev16_synthetic_evidence.py` | the disposable git repository, mock model service, synthetic preparer, reviewers and components for the synthetic end-to-end CLI rehearsal |
| tests | `tests/test_dev16_runner.py` (33), `test_dev16_criteria.py` (22), `test_dev16_configs.py` (9), `test_dev16_cli_rehearsal.py` (15) |

## 2. How the ten runner requirements are met

| # | Requirement | Implementation | Tested by |
|---|---|---|---|
| 1 | verify all frozen hashes first | `preflight` hashes every manifest file (candidate manifest, evaluator, `aq/scoring.py`, corpus, cases, configurations, rules, runner and tooling), re-runs `candidate_freeze.check`, requires HEAD to equal the manifest commit and no modified tracked listed file | hash mismatch for 7 roles, missing file / role / field, HEAD mismatch, dirty tracked file, failing candidate check, unreadable repository |
| 2 | `aq/scoring.py` in the manifest | role `scoring` is required; the proposal lists it | `REQUIRED_ROLES`, hash-mismatch test, proposal tool |
| 3 | exact P0 and candidate configurations | the manifest hashes `dev16_p0_config.json`; the executor's effective configuration must hash to it; `p0.verify_declared()` and `candidate_arm.verify_declared()` must report nothing | P0 drift test, configuration-check refusal, candidate declaration test |
| 4 | paired identities and populations | the cases file hash, the case count and the hash of the ordered ids are in the manifest; candidate rows must equal the cases in order; P0 rows are written per case id and the P0 arm must cover every case | population mismatch, duplicate ids, wrong candidate order, malformed P0 row |
| 5 | one-shot with explicit authorisation | `--execute` plus `AQ_DEV16_APPROVAL` naming a single-use file bound to the manifest hash and run id, not expired, never used | missing / wrong manifest / wrong run id / expired / not single-use / wrong decision / reuse |
| 6 | fail closed | every guard collects all problems and refuses; any doubt (unreadable manifest, cases or repository) refuses; a refusal writes nothing into a run directory and is logged to `REFUSALS.jsonl` | the guard tests above |
| 7 | immutable artifacts, provenance, failure logs | exclusive creation, fsync per row, read-only at the end, `ARTIFACTS.sha256`, `provenance.json` before the first reply, `failure.json` with traceback | complete run, tampering detection, abort tests |
| 8 | no accidental rerun or overwrite | exclusive lock directory per manifest hash, an append-only ledger, no resume, `write_once` | second attempt, existing run directory, interrupted run, overwrite |
| 9 | PASS / FAIL / INDETERMINATE | `dev16_criteria.assess`, section 5 | 19 tests |
| 10 | insufficient opportunities stated | criteria 7 to 9 report events, opportunities, the number needed (29) and the observed bound | coverage tests |

An interrupted process (killed, power loss) leaves the lock and a non-terminal `STATE.json`; the next attempt is refused and `inspect` reports it. A failure inside a run aborts the whole run (`ABORTED`), keeps what was produced and is never resumed without an owner decision. A hash change during the run yields `COMPLETE_BUT_INVALID`, which `require_complete` refuses for packets and evaluation.

## 3. Exact P0 baseline configuration (`dev16_p0_config.json`, sha256 `0cf4d699c32115a7f57db6175af4cffbfe8406866ada9e31a2faea39cbe8865f`)

P0 = today's retrieval and prompt plus the 44H unclaimed-action boundary, answered by the production default model. It is the `b1a` arm of `selective/pilot.py`, made explicit.

| Item | Declared value |
|---|---|
| harness | `aq.conditions_g2.GConditions2`, condition `b1a`, no modifiers, evidence token budget 1500 |
| model | client `aq.llm.Local`, served name `reachy-local` (verified from `/v1/models` at run time; production default, Qwen2.5-7B), endpoint `AQ_LLM_URL` (default `http://localhost:8003`), `nothink` off, streaming with usage |
| decoding | temperature 0, seed 44, max_tokens 350, one choice, no other parameter overridden |
| retrieval | `Retriever` with `RetrievalConfig B1A` (lexical; `candidates` 40, `limit` 10, `prefilter` on, no vector, no rerank, `rrf_k` 60, `rerank_pool` 20), temporal = the case's `temporal`, access = the case's profile through `access_context`, retrieval-time revalidation as shipped, pinned source = the case's attached meeting if any |
| evidence context | `build_context`, header `v1`, `flag_instructions` on, no conflict flag, no note, destination `cloud` only if the profile allows it, historical included only for `include_historical` cases, clock 2026-10-08T12:00:00+00:00, token counts from the server's `/tokenize` |
| input order | system persona prompt (sha256 `3bd643a8...4d01`), system 44H action boundary (`87f03787...9387`), system date/time (`0ba73c96...0bc00`), a spoken-reply instruction for voice cases only (`21cdf848...1dc62`), the evidence block immediately before the user turn, then the question. Evidence in the builder's order of the retrieval bundle; cases in the frozen file order, one at a time, no batching, no shuffling |
| output schema | free-text reply of at most 350 tokens citing `[E<n>]`; row fields `id, family, arm, question, reply, manifest, ms, prompt_tokens, completion_tokens, finish_reason, messages_sha256`; `manifest` = `{evidence id: {refs, authorized}}` as rendered; no outcome field: flags come only from blinded human labels |
| runs | exactly one; no retries, no resumption, no second sample |
| pinned code | sha256 of 13 source files (`aq/conditions*.py`, `aq/llm.py`, `selective/pilot.py`, `kbench/security.py`, `kbench/fixtures.py`, `knowledge/{retrieval,context,search,revalidate}.py`, `persona/context.py`, `shared/models/persona.py`) |

**Brittleness, stated plainly.** P0 is today's production code. If any pinned production file changes before the freeze, `verify_declared()` reports it and the runner refuses; the declaration must then be regenerated (`dev16_p0.write_declared()`) and re-reviewed before the freeze. The same guard stops a change between freeze and run. The check is a runtime guard, not a unit test, so an unrelated edit cannot break the test suite.

**Not exercised.** `RealP0Executor.open()` and `.run_case()` (model server, vector-less retrieval over a Postgres test corpus) were not run: no P0 call is authorised. They mirror `pilot.py` line for line and add the `/v1/models` check and the `messages_sha256` record; they need a dry check against the real server under a separate authorisation before the freeze (checklist item C9).

## 4. Candidate arm configuration (`dev16_candidate_config.json`, sha256 `556aa9911472377cbde26eca8dcc5b9309a0b5c59fa536241454dfccde42acba`)

Frozen code only: `make_planners(world, cases)["T-new"]`, `deterministic_criteria.question_row`, the candidate manifest's sources. Policy `p1` (60 s authorisation age, 2 s skew, bounded context on, qualified-object check on), evaluation clock 2026-10-13T12:00:00+00:00 (the P0 clock is 2026-10-08; the two arms already differed in the earlier work and this is declared, not changed).

**Added, harness-side, because the frozen World has one global authorisation:** per-case authorisation from the case's access profile, using the corpus's authoritative per-record facts (`kbench.security.violations`). For `owner_private`, the only profile dev15 used, the result is identical to the frozen default (173 of 173 rows and 299 of 299 decisions identical, tested). For other profiles it is stricter and correct: a `shared_speaker` case cites nothing (the public ceiling authorises nothing in this corpus) and a `harbor_only` case cites only in-scope records (tested). Without this, a case with a restricted profile could have made the candidate cite a record the asking principal may not see.

## 5. PASS / FAIL / INDETERMINATE (thresholds exactly the evaluator's)

Overall: **ACCEPTED** only if all ten are PASS; any FAIL is **REJECTED**; otherwise **NOT ESTABLISHED**. The evaluator's own pass flag is kept in every record.

- Criteria 1, 2, 3, 4, 10 (against P0): INDETERMINATE if labels are incomplete, if the baseline makes the comparison undefined (no baseline unsupported claims for 1; no baseline recall for 3; no mixed questions for 4), or if two reviewers' kappa is below 0.80. Otherwise the evaluator's verdict, labelled with its basis ("single reviewer, NOT independent" or "two reviewers, kappa ...").
- Criterion 5: PASS iff no bad or unauthorised citation; INDETERMINATE with no cited claims.
- Criterion 6: section 6.
- **Criteria 7, 8, 9 (owner decision 1, applied).** FAIL on any event. PASS on zero events only if there are at least **29 qualifying independent opportunities**; otherwise **INDETERMINATE**, with the atoms, the independent opportunities, the number needed and the observed bound stated.
  - *Independence.* An opportunity is a distinct underlying fact, keyed by (relation, subject, gold values). Several questions about the same fact count once, because they share records and a way to go wrong. dev15's repeated questions show why this matters. The assumption that remains is stated in every report: distinct facts are treated as independent trials with a common rate; dependence between facts of one project or generator is not removed by counting.
  - *The bound is verified, not assumed.* 29 is the smallest n with (1 - 0.05^(1/n)) at most 10%; the report recomputes the bound by bisection on the binomial probability itself ((1-p)^n = 0.05) and requires the two to agree (29 independent facts: 9.81%; 28: 10.15%).
  - Thresholds and the evaluator are unchanged; the stricter status is a reporting rule.

## 6. Criterion 6 under the locked rules (`dev16_criterion6_rules.json`, version 2, sha256 `9141ed6d6bd60425143c3ea37370914f69297739d9f122941ceba063b9ff79bf`)

The adjudicated figure gates and the mechanical figure is reported beside it; the 95% threshold and the floor of 40 cited claims are unchanged; nothing retrospective changes. The rules file is hashed into the manifest and `load_rules` refuses a different one.

- **Semantic support is established from the claim, the cited passage and the admissible context**, which the reviewer is shown: the record's text and title (a meeting segment's resolved speaker is part of its text). A reviewer answers **SUPPORTS** (with a verbatim span, checked by code against the passage or its title), **DOES_NOT_SUPPORT**, or **UNRESOLVABLE**. An unresolvable case **stays unresolved**: never credited, never counted as unsupported by the reviewer, reported, and it keeps criterion 6 INDETERMINATE when crediting it could change the verdict.
- **The old proxy is diagnostic only (owner decision 2, applied).** A cited text that does not name the atom's subject is not treated as evidence of incorrect or non-direct binding and decides nothing. It only sends the claim to a reviewer and is tagged `not_direct_diagnostic` in the sealed key.
- **Categories are derived by code from authoritative case metadata (owner decision 3, applied):** registration = the case's registered gold sources; authorisation and scope = the corpus facts of the case's access profile (`kbench.security.violations`), the case's `excluded_refs` and the evaluated manifest. None is inferred from model output. (1) SUPPORTS + in the evidence universe + not registered = manifest omission, eligible; (2) SUPPORTS but outside the universe = never credited; (3) DOES_NOT_SUPPORT = never credited.
- Credit needs **both** reviewers, SUPPORTS and a valid span; one reviewer, a disagreement, an UNRESOLVABLE or a void span credits nothing. A claim is credited only if every cited id is a supporting registered source or a credited category-1 record.
- Population: all mechanically unsupported claims, the diagnostic-flagged claims, and 30 seeded controls, mixed in one shuffled stream; reviewers see neither the arm, the mechanical verdict nor which are controls.
- Status: PASS at an adjudicated fraction of at least 0.95 with at least 40 cited claims; FAIL if crediting every pending or unresolved eligible claim would still stay below; otherwise INDETERMINATE (reviewer B unassigned, an UNRESOLVABLE answer, an incomplete review).
- Unauthorised citations remain criterion-5 failures whatever a reviewer says. Criteria 4 and 10 use the evaluator's mechanical `fully_correct` (including its citation check); the adjudication changes criterion 6 only.

## 7. Blinded packets (built by `packets`, sealed keys, hash manifest)

P0 semantic-adjudication packet (every P0 reply and every gold atom, plus a seeded 20% candidate control; the control compares label-derived flags with the exact flags) and the citation packet (section 6). Rehearsal sizes on dev15: 208 replies and 373 parts for the P0 packet (35 control replies), 54 claims for the citation packet (8 mechanically unsupported, 16 diagnostic-flagged, 30 controls out of 191 cited). dev16 sizes follow its case count (the preflight's estimate: about 262 replies and 470 parts). Labels are the eight of `p0_adjudication`; blinding limits are those of the [preflight](phase-44-dev16-preflight.md#7-blinded-review-packet-construction-and-sample-sizes) (the candidate's templated wording is recognisable).

## 8. Verification (final)

**Synthetic end-to-end rehearsal through the real entry point** (`dev16_runner.main`; `tests/test_dev16_cli_rehearsal.py`, 15 tests; evidence `results/dev16-synthetic-cli-rehearsal/SYNTHETIC_CLI_REHEARSAL.json`, driven by `dev16_synthetic_evidence.py`). A disposable git repository (so HEAD, clean-tree and dirty-file checks are the real `git` ones), a disposable mock model service on 127.0.0.1, and the **real `RealP0Executor`** (health check, model check, streamed completion, row schema, `messages_sha256`) with a synthetic preparer in place of the retrieval stack; the adapter refuses any target but the mock. It exercises:
- the whole lifecycle `verify`, `run`, `packets`, `evaluate`, `inspect`: the declared decoding (temperature 0, seed 44, 350 tokens) reaches the service; paired ids; provenance; fsync'd, read-only artifacts; `ARTIFACTS.sha256`; ledger START/COMPLETE;
- approval-file validation (absent, wrong manifest, wrong run id, expired, not single-use, wrong decision, wrong purpose) and single use (a reused file and a second run are refused with a fresh authorisation; a refusal consumes nothing);
- hash and clean-tree checks, fail-closed handling of a missing file, a moved HEAD and an unreadable repository (all refuse before any call);
- interruption: a service failure at the 41st case aborts, keeps 40 flushed rows, writes `failure.json` and forbids a rerun; **a child process killed with SIGKILL mid-run** leaves 30 durable rows, a lock and no resume; a wrong served model aborts before any case;
- aggregation: scenario *good* with two reviewers (kappa 0.97) is ACCEPTED under reviewer A, reviewer B and the reconciled labels, with criterion 6 mechanical 89.3% and adjudicated 100%; *thin* gives INDETERMINATE for criteria 7 to 9 (10 independent opportunities, 29 needed) and NOT ESTABLISHED; *bad* gives FAIL for criterion 7 and REJECTED; kappa below 0.80 makes criteria 1, 2, 3, 4, 10 INDETERMINATE; an UNRESOLVABLE citation answer leaves criterion 6 INDETERMINATE and uncredited;
- **separation of rehearsal and acceptance:** a rehearsal can neither use an acceptance-purpose authorisation (the file is left untouched and nothing is written to the ledger) nor write to the formal output directory (`dev16_acceptance_runs`, which is never created); an acceptance-purpose manifest can write only there;
- independent labels are copied, hashed and made read-only in the report directory before agreement or reconciliation is computed.

**Defects the rehearsal found and fixed:** `git_info` stripped the porcelain output and cut the first dirty path's first character, so a dirty tracked file could have been missed (fixed, tested); the first `load_world` left `KBENCH_CORPUS` set (fixed; the cleanup is preserved and now tested, including the P0 executor's own set-and-restore).

**Suites.** New infrastructure tests 79 (runner 33, criteria and criterion 6 22, configurations and the dev15 rehearsal 9, CLI rehearsal 15). **Full companion-core suite: 1,709 passed, 77 skipped, 5 failed.** The five are exactly the known failures: `test_knowledge_index::test_reconcile_repairs_a_missing_stale_orphaned_and_expired_index`, `test_knowledge_retrieval::test_historical_mode_reaches_the_prefilter_and_revalidation`, and three `test_knowledge_index` contention-tool tests. **All five reproduce on a clean checkout of the parent commit `b856351`** (checked in a separate worktree, which was removed). `ruff check .` passes.

**Consumed-data rehearsal** (`results/dev16-runner-rehearsal-dev15/`, candidate real, P0 replayed): COMPLETE; criterion 6 mechanical 183 of 191 with 8 pending; without labels the baseline-relative criteria are INDETERMINATE. It says nothing about any system.

**Not exercised:** the production retrieval path of `RealP0Executor` (Postgres test corpus, MiniLM) and any real model server; the `run` command with the real components end to end. Both need the separate model-call authorisation.

## 9. Proposed acceptance freeze manifest (`ACCEPTANCE_FREEZE_PROPOSAL.json`, sha256 `71898e09ee2c08947bdbc2a20c78076db77dc07f790bd284423773e72d919b42`, regenerated after the final infrastructure change)

16 hashed files: the candidate manifest, `evaluator.py`, **`aq/scoring.py`**, `corpus_v4.json`, the P0 and candidate configurations, the criterion-6 rules, the runner, the P0 module, the candidate arm, the criteria module, the criterion-6 module, `p0_adjudication.py`, `deterministic_criteria.py`, `i2b_eval.py` and the proposal tool. **To be set at the freeze, not before:** the dev16 cases (hash, count, ordered-id hash), the bank files, the commit, the seed and the authorisation file. The real manifest is produced by `dev16_runner.build_manifest` and must be committed before the run, because the runner refuses when HEAD differs from the manifest commit or a listed tracked file is modified. These files are committed in the commit that carries this page (the SHA is reported with the push); a real manifest must name a commit at or after it.

## 10. Final execution checklist (nothing below has been done)

**Owner decisions (2026-10-10 review)**
1. Criteria 7 to 9: INDETERMINATE below 29 qualifying independent opportunities, bound and independence verified: **decided and applied**.
2. Criterion 6: the missing-subject-name proxy is diagnostic only; semantic support from the claim, passage and admissible context; unresolvable stays unresolved: **decided and applied**.
3. Code-derived authorisation, scope and registration categories from authoritative case metadata: **approved**.
4. Reviewer B **unassigned**; kappa >= 0.80 retained as the proposed target; independent labels preserved before reconciliation; no independence or kappa claim: **applied** (still open: naming reviewer B).
5. Commit and push after the corrections and verification: **done** (see the report).
6. **Still open:** the seed, the freeze commit and date, and the separate owner decision to authorise formal execution and the P0 model calls.

**Preparation (before the freeze)**
- C1 regenerate and review `dev16_p0_config.json` if any pinned production file changed (`dev16_p0.write_declared()`); `verify_declared()` empty for P0 and the candidate.
- C2 dry-check the production retrieval path of `RealP0Executor` (Postgres test corpus) and a real model server **under a separate, explicit authorisation for model calls** (C9), on dev15 only. The adapter itself has been exercised against a disposable mock.
- C2b export `KBENCH_DATABASE_URL` (a DISPOSABLE PostgreSQL with pgvector), `AQ_PG_IMAGE_DIGEST` (its image digest) and `AQ_PG_CONTAINER` (its container name, so docker verifies the digest); the embedding model must already be cached (the run is offline and fails closed otherwise); see the [P0 reproducibility correction](verification/phase-44-dev16-p0-reproducibility-correction-2026-10-10.md).
- C3 commit the new files; `candidate_freeze.py --check` passes; working tree clean for listed files.
- C4 build the real manifest with `build_manifest` (dev16 cases hashed here for the first time) and have the owner review its hashes against `ACCEPTANCE_FREEZE_PROPOSAL.json`.
- C5 write the single-use authorisation file bound to that manifest hash and a run id; set `AQ_DEV16_APPROVAL` to its path.
- C6 `dev16_runner.py verify --manifest ... --root ... --runs-root ... --run-id ...` prints "all guards pass".

**Execution (one shot)**
- C7 `dev16_runner.py run ... --execute`. On `REFUSED`, fix the cause and re-verify (nothing was run). On `ABORTED`, stop: no rerun, no resume, owner decision.
- C8 `dev16_runner.py inspect` confirms COMPLETE (not COMPLETE_BUT_INVALID).
- C9 (separate) the P0 model calls themselves are authorised only by the authorisation file's `p0_model_calls_authorized`.

**After the run (no model)**
- C10 `packets`; reviewers A and B label independently from the sealed-key-free packets; labels sealed and hashed; agreement and control computed before the key is used.
- C11 `evaluate` with labels A, B and the citation answers; report all ten per reviewer variant, every failure by case id, mechanical and adjudicated criterion 6 side by side.
- C12 stop for the owner. Any defect found is reported, not fixed; a fix is a new candidate and a new acceptance.

## 11. Remaining limitations

Everything in the [preflight](phase-44-dev16-preflight.md#10-remaining-limitations-and-known-test-failures) stands. Specific to this step: `RealP0Executor` and the `run` command line were never executed end to end; the candidate and P0 arms use different clocks and different authorisation machinery (declared); the non-direct diagnostic only routes claims to review; with reviewer B unassigned, criterion 6 cannot credit any adjudicated claim, so it is PASS only if the mechanical figure already passes; and no result in this step is about dev16.
