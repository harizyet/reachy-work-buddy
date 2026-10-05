# Phase 37: Semantic routing and argument validation

Status: **started 2026-10-05; shadow trial enabled, nothing promoted.** Scope and exit criterion are owned by the
[forward roadmap](plan.md#forward-roadmap-phases-30); this page owns the stage sequence and gates. The decision and its rules are
[ADR 0026](adr/0026-semantic-routing-and-argument-validation.md); the shadow contract, flags, trial procedure and measured evidence are in
[shadow-router](shadow-router.md). This phase is independent of 31 and 32 and touches the conversation handler order, so any change to a live
handler needs the owner.

## Stages

| Stage | Work | State | Gate to the next stage |
|---|---|---|---|
| 37.0 Build and verify | Router sidecar (ModernBERT x3, 18 routes, ONNX FP32), extractor, deterministic validator, background shadow pipeline, records, blind-grading and destroy tooling, 33 tests, deployment regression | **Done 2026-10-05** | Sidecar router p95 under 100 ms with 7B and diarization running; queue accounting exact; production replies identical with the shadow on and off |
| 37.1 Shadow trial | Up to 500 accepted turns of real traffic, router online (extraction offline), text logged only for the window and never for sensitive turns; then offline extraction against the shared 7B | **Enabled 2026-10-05, collecting** | Cap reached or owner stops |
| 37.2 Evaluation | Blind sheet (all disagreements plus a random sample of agreements), owner/designated grader labels, report with `unsafe_would_execute`, `safe_but_withheld`, per modality (voice vs text), then destroy every recorded file | Pending 37.1 | Unsafe would-execute at or near zero over the graded sample; safe-but-withheld at a level the owner accepts; voice results reviewed separately |
| 37.3 Read routes live | Router chooses read tools (calendar, email, tasks, clock, status); rule chain is the fallback; per-route flag and kill switch | Not started; needs owner decision | Canary share of turns with no regression against production answers |
| 37.4 Clarifications live | A withheld request produces a short question in the conversation with the reason category | Not started | Owner accepts the over-withholding rate |
| 37.5 Writes behind the consent gate | Router, extractor and validator feed the existing ADR 0011 gate; resolved target echoed for delete and complete; text-only confirmation for destructive actions | Not started | Separate owner decision; gate and undo behaviour unchanged |
| 37.6 Live extraction impact | Decide how extraction runs live: only when the model is idle, a low-priority queue, a smaller dedicated extraction model, or asynchronous extraction if the action tolerates it | Not started | Production decode and TTFT within agreed bounds with extraction active |
| 37.7 Retire rules | Remove phrase matchers only after sustained agreement; otherwise keep as fallback | Not started | Weeks of agreement and a rollback path |

## Constraints that carry across stages

- The shadow never executes or alters anything; robot requests stay on `command_suggestion.classify`.
- Recorded trial data is destroyed once evaluation and testing are complete. There is no deadline other than completion; there is no retention beyond the evaluation.
- Measure only when the host is quiet (load average under 3); an unrelated benchmark on the same host once polluted two runs. The shared 7B serves live traffic, so benchmarks use one stream.
- Re-run the deployment regression (`bench` workspace `contention_deploy.py`) after any change to the queue, sidecar sizing or extract mode.

## Known gaps to close before promotion

- Router weaknesses seen on author-written sets and the 17-turn real run: calendar.read recall 0.58, memory.forget 0.67 (3 cases), coding.status 0.71, tasks.capture 0.71; `unsupported` over-fires (precision 0.61); "note this down" went to tasks.capture and "drop that" to unsupported. Add real examples before retraining; retraining needs the same frozen-holdout discipline.
- Voice transcription noise is untested; the trial's per-modality split is the first evidence.
- The validator over-withholds some phrasings; its rules were tuned on three rounds of author-written cases, so the 2% unsafe-extraction figure (1 of 50, holdout written after the validator was frozen) is a point estimate on small data.
