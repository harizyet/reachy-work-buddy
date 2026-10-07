# Meeting transcript corrections: model benchmark (2026-10-07)

Evidence for [Phase 41](../phase-41.md) / [ADR 0030](../adr/0030-meeting-speaker-names-and-reviewed-corrections.md).
Harness: [services/companion-core/benchmarks/meeting_corrections](../../services/companion-core/benchmarks/meeting_corrections/README.md).
23 cases: **1 real** (Gemini heard as "germanite") and **22 synthetic** (written for this benchmark; 15 with an expected
correction, 8 negatives where an everyday word resembles a term). Greedy decoding, one run per cell, so one case is
about 5 points: differences of a case or two are noise. Models served by the same vLLM image (0.30.0) on the RTX 2000E Ada
(16 GB), 4096 context, 4-bit weights, one at a time, with the production 7B stopped for the test and restored afterwards.

| Model | Resolver, one question per candidate: recall / precision / F1 | Resolver, batched JSON: F1 | Real germanite found (single / batch) | Model alone, no terms: recall |
|---|---|---|---|---|
| Qwen2.5-7B-Instruct-AWQ (current) | 0.85 / 0.94 / **0.89** | 0.73 | no / no | 0.00 |
| Qwen3-14B-AWQ (thinking off) | 0.95 / 0.95 / **0.95** | 0.93 | yes / yes | 0.10 |
| Gemma-3-12B int4 | 0.85 / 0.94 / **0.89** | 0.89 (recall 1.00, precision 0.80) | no / yes | 0.10 |
| Gemma-4-12B QAT w4a16 | 0.85 / 1.00 / **0.92** | **1.00** (recall 1.00, precision 1.00) | no / yes | 0.45 |

Key terms with no model at all (spelling variants such as "anti-gravity" for Antigravity, "click house" for ClickHouse): recall 0.25, precision 1.00.

Findings:

- **The architecture matters more than the model.** Every model scores 0.00 to 0.45 recall on its own, and 0.85 to 1.00 once it only chooses among key-term candidates. The 7B reaches 0.89 F1 with terms and still cannot resolve the real "germanite" case.
- **Prompt shape depends on the model.** A one-candidate multiple-choice question suits the 7B and Qwen3 (the batched JSON reply drops the 7B to 0.73). Gemma-4 does best on the batched reply (1.00) and Gemma-3 over-accepts in it. The app uses the one-candidate form for local models; Gemma-4 would gain from the batched form.
- **Qwen3-14B and Gemma-4-12B are the credible second tier**; Gemma-3-12B adds little over the 7B here. Neither was tested on chat quality or conversational latency, which decide whether to change the production model: this benchmark does not.
- **Failed to load:** Ministral-3-14B (`PixtralForConditionalGeneration` failed registry inspection in vLLM 0.30.0); Nemotron-Nano-9B-v2-FP8 (out of GPU memory at 0.85 utilisation).
- Window size (400 to 6000 characters) made no difference for the 7B before the key-terms approach.
