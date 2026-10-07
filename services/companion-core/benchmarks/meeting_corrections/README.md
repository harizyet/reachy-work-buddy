# Meeting transcript correction benchmark

Scores approaches for suggesting transcript corrections against `cases.json`
([Phase 41](../../../../docs/phase-41.md), [ADR 0030](../../../../docs/adr/0030-meeting-speaker-names-and-reviewed-corrections.md)).
Approaches: `deterministic` (key terms only, no model), `resolver` (key terms plus a model choosing among
candidates), `scan` (model alone, no terms) and `both` (what the app runs).

```bash
cd services/companion-core
../../.venv/bin/python benchmarks/meeting_corrections/run.py \
  --base-url http://localhost:8003/v1 --model Qwen/Qwen2.5-7B-Instruct-AWQ
```

Production vLLM now serves its model as `reachy-local`, so pass `--model reachy-local` there.

Only `real` cases come from recordings (one so far: Gemini heard as "germanite"). The rest are `synthetic`,
written for this benchmark, so scores measure the approach, not real-world accuracy. Add genuine ASR mistakes
as they turn up. Qwen3 needs `--extra-body '{"chat_template_kwargs": {"enable_thinking": false}}'`.
