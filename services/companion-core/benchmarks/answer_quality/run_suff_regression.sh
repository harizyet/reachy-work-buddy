#!/bin/bash
# Over-abstention regression for the evidence-sufficiency note and gate: every older development split, b1a+routed with and without the note/gate (7B).
cd "$(dirname "$0")"
PY=../../../../.venv/bin/python
for s in dev dev2 dev3 dev4 dev5; do
  $PY run.py --split $s --budget 1500 --conditions b1a+routed,b1a+routed+suff,b1a+routed+gate --out results/suffreg-$s.json 2>/dev/null
done
touch results/DONE-suffreg
