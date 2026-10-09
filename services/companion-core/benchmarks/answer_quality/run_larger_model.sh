#!/bin/bash
# Run under the model manager's deep tier: `python -m model_manager run -- ./run_larger_model.sh TAG`.
# Replays the STORED 7B prompts (identical evidence, persona, question, temperature 0, seed 44) on whatever `reachy-local` serves now, then records GPU memory.
# The 7B baselines are the stored first-pass replies of the same rows, so each comparison is the same prompt and the same scorer.
cd "$(dirname "$0")"
PY=../../../../.venv/bin/python
TAG=${1:-14b}
echo "{\"at\":\"$(date -u +%FT%TZ)\",\"served\":$(curl -s localhost:8003/v1/models | head -c 400),\"gpu\":\"$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)\"}" > results/larger-model-$TAG.meta.json
$PY replay.py --run results/dev6-7b-suff.json --conditions b1a+routed,b1a+routed+suff,oracle,distractor,none --out results/dev6-replay-$TAG.json 2>/dev/null
$PY replay.py --run results/dev7-7b.json --conditions b1a+routed,b1a+routed+suff,b1a+routed+suff+cf,oracle,distractor,none --out results/dev7-replay-$TAG.json 2>/dev/null
$PY replay.py --run results/dev6-7b-suffcf.json --conditions b1a+routed+suff+cf --out results/dev6cf-replay-$TAG.json 2>/dev/null
echo "{\"after\":\"$(date -u +%FT%TZ)\",\"gpu\":\"$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)\"}" >> results/larger-model-$TAG.meta.json
touch results/DONE-larger-$TAG
