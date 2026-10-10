# Phase 44: final corrected-P0 development smoke test, 2026-10-10

**Result: PASSED. Development-only, one run, consumed dev15 cases only. dev16 and bank D were not inspected, frozen or run; the formal P0 baseline was not run; the frozen candidate, evaluator, baseline prompt, relation registry, thresholds and acceptance rules are unchanged; nothing was tuned on answer quality; nothing was deployed and no production retrieval, indexing or shadow was activated. No independent human validation is claimed; reviewer B is unassigned.** Owner decision: "Final corrected P0 smoke test approved", accepting the R1–R3 corrections at commit `9fa658f3a0159e31cb98b5198d14a94f88e754b9`. Output is in `services/companion-core/benchmarks/answer_quality/results/dev16-p0-smoke-corrected-dev15/`, separate from formal acceptance artifacts (manifest purpose `rehearsal`; `dev16_acceptance_runs` does not exist). The first smoke test ([record](phase-44-dev16-p0-smoke-test-2026-10-10.md)) and the [correction record](phase-44-dev16-p0-reproducibility-correction-2026-10-10.md) are preserved unchanged.

## 1. What ran

The real runner command line (`dev16_runner.py verify`, then `run --execute`), at commit `9fa658f`, clean tree, with the production components: the **corrected stable-id P0 executor**, a **disposable PostgreSQL** (`pgvector/pgvector:pg16`, image `sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b`, removed afterwards), the **cached MiniLM** loaded offline, the **local 7B** (`reachy-local`, `Qwen/Qwen2.5-7B-Instruct-AWQ`, maximum length 8192) at temperature 0, seed 44, 350 tokens, and the frozen candidate arm. The **same ten cases**: `SELECTION.json` sha256 `1ed4ddc2e8ecce3b79fadcf887ffb6880acc0898868c8e25caec028f285e831b` and the cases file `3842bf082e32c6cb63af97d15115f10f885d6314ec33aa5809bb21c74f5a90ff`, both verified identical before the run. Seed `16044` is in the manifest and the run provenance.

## 2. Results

- **Completed first time, exit 0, 25.1 s wall** (the first smoke test took 34 s). State COMPLETE; 10 of 10 rows; no error or abort; artifacts read-only with `ARTIFACTS.sha256`; provenance written before the first reply. The stderr log contains **no Hugging Face Hub notice** (the first smoke test did): the offline flags held.
- **Schema.** Every row has exactly the declared fields; arm P0; question and family match; `messages_sha256` well formed; every cited `[E<n>]` exists in its manifest; every manifest entry is authorised; every `finish_reason` is `stop`.
- **Latency** (model call, ms): min 282, median 1,243, max 2,446, total 12,936.
- **Access enforcement.** No retrieved record violates its case's profile. `shared_speaker` retrieved 0 records; `harbor_only` retrieved 1 (`reminder:rem-4`), as before.
- **Environment record** (`p0_environment.json`, listed in `ARTIFACTS.sha256`): image digest equal to the declared one and **verified by docker**; PostgreSQL 16.15 (Debian 16.15-1.pgdg12+2); pgvector 0.8.6; stable record ids; the hash of `pg_env.py` as run equals the file; embedding model `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, weights sha256 `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`; `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` during the run; the actual `/v1/models` response (served id `reachy-local`, root `Qwen/Qwen2.5-7B-Instruct-AWQ`). The run's effective P0 configuration equals the declared one.
- **Matches the deterministic reproducibility evidence** (`SMOKE2_REPORT.json`): the ten cases were re-prepared (retrieval, access context, prompt assembly; no generation) in two further fresh stable-id databases. With the **same live tokenizer** the run used, the ordered evidence and the sha256 of the assembled messages are identical to the run's in **10 of 10** cases. With the **offline counter** of the reproducibility evidence the ordered evidence is identical in **10 of 10** cases (no token-packing difference arose). The prepared evidence and prompts of the run are therefore exactly what the deterministic path produces.
- **Downstream, no semantic labels.** `packets` built the blinded P0 packet (12 replies, 21 parts) and the citation packet (11 cited claims, 0 mechanically unsupported); `evaluate` ran with no labels: one PASS and nine INDETERMINATE, NOT ESTABLISHED, as designed. A second `run` on the same manifest was refused with no model call (`duplicate_run_refusal.log`).

**Informational, not used to tune anything:** compared with the first smoke test (a random-id draw), the corrected path's evidence is identical in 3 of 10 cases and the replies are identical in exactly those same 3 cases (their prompt hashes are identical too), while every other reply differs in a case whose evidence differs. At temperature 0 and seed 44 the model call itself therefore behaved deterministically given the prompt in this sample; the earlier differences came from retrieval. (Ten cases; stated as an observation, not a guarantee.)

## 3. Exact hashes (sha256)

| Item | Value |
|---|---|
| smoke manifest (`manifest.json`) | `fc31275aa9a32fc5…` (full value in the file) |
| authorisation (`authorization.json`) | `fc40f8a8996efbdf…` |
| run `ARTIFACTS.sha256` | `e6529799d5b7eb09…` |
| `p0_rows.jsonl` | `30bf7623467640d7…` |
| `candidate_rows.jsonl` | `4a640cf1fbaf4068…` |
| `p0_environment.json` | `69bd6274ab35a004…` |
| `provenance.json` | `cf188b7e1e56b905…` |
| `SMOKE2_REPORT.json` | `fb8cd2fbc2be125e…` |
| `dev16_p0_config.json` | `d645e91342bd631b…` |
| `dev16_candidate_config.json` | `556aa9911472377c…` |
| `dev16_criterion6_rules.json` | `9141ed6d6bd60425…` |
| `ACCEPTANCE_FREEZE_PROPOSAL.json` | `a22ce073448a8e20…` |
| `CANDIDATE_FREEZE_2026-10-10.sha256` | `b095e9beb02f5573…` |
| `evaluator.py` | `d364af6bbf7f5328…` |
| `aq/scoring.py` | `6bfb790efdf6a2cb…` |
| `kbench/pg_env.py` | `a37f07e72672fe01…` |
| `dev16_runner.py` / `dev16_p0.py` / `dev16_candidate_arm.py` | `6423ff936e32f58c…` / `8631bd66b530e3fd…` / `dde0404f58d17a08…` |

All except the smoke artifacts are unchanged from commit `9fa658f` (the working tree had no modified tracked file).

## 4. Boundaries

dev16 and bank D were not read, listed or hashed; no frozen component was modified; the smoke output, `dev16_p0_smoke2_check.py` and this record are **uncommitted** (this decision did not authorise a commit); the disposable database container was removed and its throwaway credential deleted; the model server was used read-only through its public completion and tokenizer endpoints.
