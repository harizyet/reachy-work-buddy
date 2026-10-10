# Phase 44: development-only smoke test of the real P0 execution path, 2026-10-10

**Status: development evidence only. Consumed dev15 cases only; dev16 was not accessed, frozen or run; the frozen candidate, evaluator, thresholds and criterion-6 rules are unchanged; nothing was tuned, deployed or activated. Nothing here is a result about any system, and no independent human validation is claimed.** Authorised by the owner's "Final P0 execution-path verification" decision. Output is kept separate from formal acceptance artifacts in `services/companion-core/benchmarks/answer_quality/results/dev16-p0-smoke-dev15/` (manifest purpose `rehearsal`, so the runner structurally refuses to write to `dev16_acceptance_runs`, which does not exist).

## 1. What was exercised, for real

| Component | Used |
|---|---|
| runner | the real command line `dev16_runner.py verify` then `run --execute`, then `packets` and `evaluate`, with the production components (frozen candidate arm with per-case authorisation, the candidate-freeze check, the P0 and candidate declaration checks) at commit `09bba8fcfaf460cb27448d8ba0069076e937ac9f` |
| P0 retrieval | the real `GConditions2` `b1a` path over **real PostgreSQL** (a disposable `pgvector/pgvector:pg16` container, digest `sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b`, PostgreSQL 16.15, bound to 127.0.0.1 with a throwaway password, removed afterwards; the homelab database was never touched), the real indexing worker, the real MiniLM embedder (cached model) |
| access-context enforcement | `kbench.security.access_context` per case profile, plus the retrieval-time revalidation as shipped |
| prompt assembly | the pinned persona, 44H boundary and date messages, the evidence block before the user turn |
| inference | the local 7B served as `reachy-local` (`Qwen/Qwen2.5-7B-Instruct-AWQ`, max length 8192) at `localhost:8003`, temperature 0, seed 44, 350 tokens, streamed. This is the homelab's model server, used read-only through its public completion endpoint; nothing was started, stopped or reconfigured |
| records | the invented corpus `selective/corpus_v4.json`; no private user records |

## 2. The fixed case set (selected and hashed before execution)

`SELECTION.json` (sha256 `1ed4ddc2e8ecce3b79fadcf887ffb6880acc0898868c8e25caec028f285e831b`; the cases file `3842bf08...90ff`), seed **16044**: one dev15 case per question family by a seeded draw over sorted ids (D15-113 conflict, D15-011 control_supported, D15-032 control_unsupported, D15-067 mixed, D15-077 multipart, D15-140 negative, D15-166 temporal, D15-129 unknown_actor), plus two **derived access-profile variants** of consumed cases (`D15-011-AX-shared_speaker`, `D15-067-AX-harbor_only`: same question, `access` changed) to exercise enforcement. The variants are development fixtures, labelled by their ids. 10 cases in all.

## 3. Results

- **Completed first time, exit 0**, wall time 34.4 s for the whole run including corpus build and embedding load. State COMPLETE; 10 of 10 rows; no error, no abort; all artifacts read-only with `ARTIFACTS.sha256`; provenance written before the first reply; ledger START/COMPLETE.
- **Schema.** Every row has exactly the declared fields (`id, family, arm, question, reply, manifest, ms, prompt_tokens, completion_tokens, finish_reason, messages_sha256`); `arm` is P0; the question and family match the case; `messages_sha256` is a 64-hex digest; the evidence manifest is `{E<n>: {refs, authorized}}`; every `[E<n>]` a reply cites exists in its manifest; every manifest entry is authorised; `finish_reason` is `stop` for all 10. The run's effective P0 configuration equals the declared one.
- **Access enforcement.** No retrieved record violates its case's access profile (checked against the corpus's authoritative per-record facts). The `shared_speaker` variant retrieved **0** records (the public ceiling authorises nothing in this corpus) and replied "I do not have that in the owner's records." The `harbor_only` variant retrieved **1** record (`reminder:rem-4`), one record, within that profile's scope.
- **Latency** (model call, ms): min 297, median 1,327, max 3,259, total 14,942; prompt tokens 367 to 1,032, completion tokens 12 to 127. Extrapolation to a full dev16 of about 220 cases: roughly 5 to 8 minutes of inference plus about 30 s of setup, on an otherwise idle server.
- **Source provenance recorded per case:** the retrieved records (`SMOKE_REPORT.json`), the evidence order, the message hash, token counts, finish reason, and the run's git HEAD, manifest hash, authorisation hash, P0 configuration hash, environment, Python version, database image digest and version.
- **Downstream steps.** `packets` built the blinded P0 and citation packets from the real rows (12 P0 replies, 21 parts; 11 cited claims), and `evaluate` ran with no labels: one PASS and nine INDETERMINATE, as designed (no labels, no pass). The duplicate-run guard refused a second `run` on the real path with no model call (`duplicate_run_refusal.log`).

## 4. Findings the smoke test produced (none is a defect that prevented the test)

**F1. P0 retrieval is not reproducible across fresh database builds.** The 8 base cases compared with the dev15 pilot's stored B1a replies: the ordered evidence is identical in **0 of 8**, the retrieved set in **3 of 8**, and the reply in **1 of 8**. A retrieval-only probe (no model call; `RETRIEVAL_DETERMINISM.json`) built the disposable database twice from the same corpus and found identical ordered evidence in **2 of 10** cases and identical sets in **5 of 10**. The cause, supported by the experiment but not isolated by controlling the variable, is tie-breaking: the search query orders equal ranks by `ref_key` (`ORDER BY rank DESC, ref_key`), and `ref_key` embeds the store ids that the stores assign (random) each time the database is built, so records with equal rank swap places and the ten-record cut can include different ties. The model call itself (temperature 0, seed 44) is not isolated as a second source. Consequence: **the P0 baseline of a formal run is one draw from a distribution that depends on the database build**, over and above the roughly 5% model replay noise already noted. This does not touch the candidate (deterministic) and does not invalidate the infrastructure, but it must be stated in any P0-relative result and is the reason the paired criteria carry a sensitivity margin.

**F2. Unpinned inputs of the P0 path.** The runner's provenance records the P0 configuration and pinned code hashes but not the database image digest or version, the build helper `kbench/pg_env.py` (not in the pinned source list), or the served model's full identity (`/v1/models` shows the root model and maximum length). This test recorded them by hand.

**F3. Network contact at embedding load.** Loading the cached MiniLM model produced a Hugging Face Hub "unauthenticated request" notice, i.e. the loader checks the network even with the model cached. Harmless here, but a one-shot evaluation should not depend on it.

**F4. Shared model server.** The 7B is the homelab's live server; other traffic can change latency (not content at temperature 0, apart from F1). A formal run should be scheduled on a quiet server.

## 5. Proposed smallest corrections (NOT applied; each changes a listed acceptance component and so needs owner approval, a regenerated P0 declaration and a regenerated proposed manifest)

1. **Provenance (F2):** record, in the run's `provenance.json`, the database image digest and `select version()`, the `/v1/models` payload, and add `kbench/pg_env.py` to the pinned source list. No behaviour change.
2. **Offline embedding load (F3):** set `HF_HUB_OFFLINE=1` inside `RealP0Executor.open()` for the duration of the run (restored in `close()`), and record it. No behaviour change when the model is cached.
3. **Retrieval reproducibility (F1), two options:** (a) *accept and pre-register*: no code change; the report states that P0 is one draw, lists the retrieved evidence per case, and the owner decides whether to also bound the jitter with retrieval-only repeats (no model calls); (b) *make the benchmark database deterministic*: derive the store ids from the logical record key in the benchmark builder `kbench/pg_env.py` (a harness change, not production code), then re-run the retrieval-only probe and require identical ordered evidence across builds. Recommendation: (b) if the owner wants an exactly reproducible P0, with (a)'s statement kept regardless; it is a small change but must be verified by the probe before it is trusted.

## 6. Boundaries kept

No dev16 file or content was read, listed or hashed; the formal acceptance directory does not exist; the frozen candidate manifest check passes (`candidate freeze intact`); no tracked file was modified; no production service was started, stopped or reconfigured; the disposable database container was removed (`docker ps -a` shows none left); the throwaway credential was kept only in a mode-600 temporary file and the process environment, and deleted. The smoke output, the selection and the three new scripts (`dev16_p0_smoke.py`, `dev16_p0_smoke_check.py`, `dev16_p0_smoke_retrieval_determinism.py`) are **uncommitted**.
