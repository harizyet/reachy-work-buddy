#!/bin/bash
# Development series on the NEW cases (dev2): baseline retrieval, the v2 header, status routing, both, and the oracle.
cd "$(dirname "$0")"
PY=../../../../.venv/bin/python
TAG=${1:-run}
$PY run.py --split dev2 --budget 1500 --conditions ${CONDS:-none,b1a,b1a+v2,b1a+routed,b1a+routed+v2,oracle,distractor} --out results/dev2-1500-$TAG.json 2>/dev/null
$PY report.py results/dev2-1500-$TAG.json --out results/dev2-1500-$TAG.summary.json
touch results/DONE-dev2-$TAG
