# Model manager

Swaps the local vLLM server between the fast tier (Qwen2.5-7B) and the deep tier (Qwen3-14B) and always restores the
fast tier ([Phase 42](../../docs/phase-42.md), [ADR 0031](../../docs/adr/0031-three-tier-local-model-escalation.md)).
Manual operation only; no routing, escalation or scheduling.

```bash
scripts/start-model-manager.sh --check      # read-only
scripts/start-model-manager.sh              # host process on 127.0.0.1:8090
scripts/start-model-manager.sh --bridge     # on the Docker bridge address instead, so companion-core can reach it (Deep Local)
set -a; . deploy/homelab/.env.model-manager; set +a      # MODEL_MANAGER_TOKEN; with --bridge also export MODEL_MANAGER_URL=http://172.17.0.1:8090
python -m model_manager state
python -m model_manager activate t2 --lease 900
python -m model_manager restore
python -m model_manager run -- COMMAND      # deep tier for one command, fast tier restored afterwards
```

Both tiers are served as `reachy-local`. Run its tests with `pytest services/model-manager`.
