#!/bin/bash
# Second deep-tier session: re-run ONLY the rows whose evidence bundle was empty, which the first replay rebuilt without the evidence frame (a replay defect found by comparing against the 7B).
cd "$(dirname "$0")"
PY=../../../../.venv/bin/python
TAG=${1:-14b-empty}
echo "{\"at\":\"$(date -u +%FT%TZ)\",\"gpu\":\"$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)\"}" > results/larger-model-$TAG.meta.json
$PY replay.py --run results/dev6-7b-suff.json --conditions oracle --only-empty-frame --out results/dev6-empty-replay-14b.json 2>/dev/null
$PY replay.py --run results/dev7-7b.json --conditions oracle --only-empty-frame --out results/dev7-empty-replay-14b.json 2>/dev/null
touch results/DONE-larger-$TAG
