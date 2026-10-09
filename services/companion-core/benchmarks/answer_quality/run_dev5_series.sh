#!/bin/bash
# Development series on dev5 (new cases): plain B1a, B1a with routing (tasks, reminders, persons), and the oracle.
cd "$(dirname "$0")"
PY=../../../../.venv/bin/python
TAG=${1:-run}
$PY run.py --split dev5 --budget 1500 --conditions ${CONDS:-b1a,b1a+routed,oracle} --out results/dev5-1500-$TAG.json 2>/dev/null
$PY report.py results/dev5-1500-$TAG.json --out results/dev5-1500-$TAG.summary.json
touch results/DONE-dev5-$TAG
