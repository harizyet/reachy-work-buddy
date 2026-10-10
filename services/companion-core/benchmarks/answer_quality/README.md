# Answer-quality evaluation (Phase 44E)

Measures what the local model *answers* when given different context, not only what retrieval finds. Plan and decisions:
[phase-44e-plan.md](../../../../docs/phase-44e-plan.md). It uses the invented corpus of the [retrieval benchmark](../knowledge_retrieval/README.md)
(read-only) in a scratch Postgres, and the production vLLM (`reachy-local`, Qwen2.5-7B-AWQ) at temperature 0 with a fixed seed. No owner data is read; nothing is sent to a cloud model.

```bash
docker run -d --rm --name aq-scratch-pg -e POSTGRES_PASSWORD=aq -p 127.0.0.1:55444:5432 --cpus 2 --memory 2g pgvector/pgvector:pg16
export KBENCH_DATABASE_URL=postgresql://postgres:aq@127.0.0.1:55444/postgres
../../../../.venv/bin/python run.py --validate-only
./run_dev_series.sh NAME                 # development: 1500-token run, 1000/500 variants, instruction-label ablation
../../../../.venv/bin/python run.py --split dev --budget 1500 --out results/dev-1500-NAME.json
../../../../.venv/bin/python report.py results/dev-1500-NAME.json --out results/dev-1500-NAME.summary.json
../../../../.venv/bin/python review.py --split holdout --out FILE.md   # the owner-review document; runs nothing
docker stop aq-scratch-pg
```

Run only when the model server is otherwise quiet: the runner is serial, checks the server before every request, and stops on `STOP` (a file next to `run.py`), an unhealthy server or `--time-cap`.

## Conditions (only the context differs)

`none` no retrieval; `p43` Phase 43 as shipped (an attached meeting's context as a system message, nothing otherwise); `b1a` lexical and `b1b` lexical + vector retrieval, revalidated, through the 44E builder; `oracle` the gold sources only; `distractor` authorised but irrelevant sources only (abstention cases). B1c is excluded.

## Files

| File | Purpose |
|---|---|
| `cases_dev.json`, `cases_holdout.json` | 35 development and 33 frozen cases. Written by `make_cases.py` before any run and then fixed by hash; the holdout is not scored until the owner has reviewed it. |
| `aq/cases.py` | Loading, hashing and validation (every required fact must be present in the gold sources; canaries must not appear in the question). |
| `aq/scoring.py` | Deterministic scoring: correctness, abstention, groundedness, citations, privacy, injection, voice form. |
| `aq/conditions.py`, `aq/llm.py` | What the model is given under each condition; the streaming vLLM client (time to first token, usage, server-side token counts). |
| `run.py`, `report.py`, `review.py` | Runner (holdout needs `AQ_HOLDOUT_APPROVAL=<decision point>` and is logged once in `holdout_runs.jsonl`), summaries with paired tests, the owner-review generator. |
| `cases_dev6.json`, `cases_dev7.json` | Fresh development sets (2026-10-12) for the evidence-sufficiency work and the larger-model comparison: no evidence, partial evidence, wrong entity, conflicts, supersession, actor attribution, negative claims, contamination. dev7 was written after `knowledge/sufficiency.py` was frozen. `make_cases_dev6.py`, `make_cases_dev7.py`. |
| Conditions `+suff`, `+gate` | `b1a+routed+suff`: coverage note and one focused retrieval retry; `+gate` adds a fixed abstention. `sufficiency_eval.py` (assessor on perfect evidence, no model), `summarize_sufficiency.py`, `aq/postcheck.py` and `postcheck_eval.py` (post-generation checks: measured, not usable to enforce). |
| `replay.py`, `compare_models.py`, `run_larger_model.sh`, `run_larger_model_empty.sh` | Replay stored prompts on another model and compare on identical evidence; the shell scripts run under the model manager (`python -m model_manager run -- ./run_larger_model.sh TAG`) so the 7B is always restored. `AQ_LLM_NOTHINK=1` for a Qwen3 server that is not already launched with thinking off. |
| `selective/` | Phase 44 selective-answering research (2026-10-12 to 10-10): corpus generators v4/v5, scorers v1 to v3 (**research-only; v3 failed its formal validation and the scorer cycle is stopped**), frozen validation and acceptance artifacts (`selective/acceptance/`, `ACCEPTANCE_FREEZE_v3.sha256`: do not modify), rubric v2 to v5, and the deterministic-path evaluation `i2_eval.py` / `i2_existence_sweep.py` (no model; outputs in `results/i2-*`; **do not modify**: the recorded first run) and its 2026-10-10 follow-up `i2b_eval.py` (gold-spec and question-text-only arms, outputs in `results/i2b-*`), the frozen labelled decomposition set (`decomposition_set.py`, `DECOMPOSITION_SET.sha256`, `decomp_eval.py`), the frozen manual-review sample (`review_sample.py`, `REVIEW_SAMPLE_FREEZE.sha256`, `review_packet.py`) and `deterministic_criteria.py` (dev15 dry run only). The 2026-10-10 final development pass adds `transition_probes.py`, `decomposition_heldout_set.py`, `review_sample_b.py`, `review_packet_b.py`, `p0_adjudication.py` (blinded P0 adjudication tooling; dry-run packet in `results/p0-adjudication-dryrun-dev15/`, nothing labelled), `criteria_diagnostics.py`, `i2b_failures.py` and `candidate_freeze.py` with `CANDIDATE_FREEZE_2026-10-10.sha256` (checked by a test; **do not modify the listed files without a new named freeze**; dev16 is not listed). Record: [final development pass](../../../../docs/verification/phase-44-selective-final-dev-pass-2026-10-10.md). Entry points: [Phase 44](../../../../docs/phase-44.md), [I-1/I-2 record](../../../../docs/verification/phase-44-selective-i1-i2-2026-10-10.md), [I-2 follow-up](../../../../docs/verification/phase-44-selective-i2-followup-2026-10-10.md). |
| `results/` | Raw runs and summaries. |

The corpus is small and invented, so a model with no retrieval cannot answer by world knowledge: the informative contrasts are Phase 43 against retrieval against oracle, and the abstention, authorization and injection behaviour, not the no-retrieval score.
