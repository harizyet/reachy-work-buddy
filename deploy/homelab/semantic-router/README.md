# semantic-router sidecar (shadow use only)

ModernBERT-base x3, 18 routes, ONNX FP32 on CPU. `POST /route {"text"}` -> route, confidence. It stores and logs nothing and holds no tool, consent or credential logic.
Started only with `scripts/start-homelab.sh --shadow-router` (compose profile `shadow-router`); companion-core calls it only when `SHADOW_ROUTER_ENABLED=true`.

## Model artifacts (not in git)

`models/` here must contain `onnx_fp32_s0.onnx`, `onnx_fp32_s1.onnx`, `onnx_fp32_s2.onnx` and `tokenizer/`. Export them with the bench workspace
(`bench/router/export_onnx_fine.py`) and symlink or copy them in; `SEMANTIC_ROUTER_MODELS_DIR` overrides the location. The pilot export's parity check
(max probability difference 2e-5, 100% argmax agreement on 4,755 rows per model) is in its `parity.json`; re-run the parity check after any re-export.

CPU is capped (`SEMANTIC_ROUTER_CPUS`, default 6, with `SEMANTIC_ROUTER_ORT_THREADS`=2 per model; 3 threads per model under a 3-CPU cap was throttled and missed the p95 gate) so the sidecar cannot starve the production services that share the host.
