#!/bin/bash
# Development series on dev3 (claim-verification pool and restricted-channel wording).
cd "$(dirname "$0")"
PY=../../../../.venv/bin/python
TAG=${1:-run}
$PY run.py --split dev3 --budget 1500 --conditions ${CONDS:-none,b1a,b1a+routed,oracle,distractor} --out results/dev3-1500-$TAG.json 2>/dev/null
$PY report.py results/dev3-1500-$TAG.json --out results/dev3-1500-$TAG.summary.json
touch results/DONE-dev3-$TAG
