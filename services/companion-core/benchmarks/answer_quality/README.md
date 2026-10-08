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
| `results/` | Raw runs and summaries. |

The corpus is small and invented, so a model with no retrieval cannot answer by world knowledge: the informative contrasts are Phase 43 against retrieval against oracle, and the abstention, authorization and injection behaviour, not the no-retrieval score.
