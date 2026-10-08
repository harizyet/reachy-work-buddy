#!/bin/bash
# The development series: full conditions at 1500, budget variants for the retrieval conditions, and the instruction-label ablation.
set -u
cd "$(dirname "$0")"
PY=../../../../.venv/bin/python
TAG=${1:-run}
$PY run.py --split dev --budget 1500 --out results/dev-1500-$TAG.json 2>/dev/null
for b in 1000 500; do $PY run.py --split dev --budget $b --conditions b1a,b1b,oracle --out results/dev-$b-$TAG.json 2>/dev/null; done
$PY run.py --split dev --budget 1500 --conditions b1a,b1b --no-instruction-flag --out results/dev-1500-$TAG-noflag.json 2>/dev/null
for f in results/dev-*-$TAG*.json; do case $f in *.summary.json) ;; *) $PY report.py $f --out ${f%.json}.summary.json;; esac; done
touch results/DONE-$TAG
