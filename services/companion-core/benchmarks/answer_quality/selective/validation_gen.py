"""Scorer-v2 validation corpus and question set (owner-approved 2026-10-13). A NEW invented world from the same generator at seed 17 (different people, values and records than corpus v4), design relations and
projects only, phrasing bank C only: no dev15 atoms, no bank D, no held-out relations or projects, no dev16 candidates. Over-represents the categories where severe errors are possible (conflicts, ordering,
negatives, unsupported actors). Used ONLY for scorer validation; never to tune B-1 or any mechanism; not an acceptance set.

    python validation_gen.py     ->  validation/corpus_val17.json, validation/facts_val17.json, ../cases_val17.json"""
from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen as gen
import questions_gen as qg

SEED = 17
COUNTS = {"control_supported": 15, "control_unsupported": 30, "mixed": 30, "multipart": 25, "conflict": 45, "unknown_actor": 35, "negative": 40, "temporal": 60}

if __name__ == "__main__":
    gen.SEED = SEED
    corpus, registry = gen.build()
    problems = gen.check_unique(registry)
    if problems:
        raise SystemExit("ambiguous facts: " + "; ".join(problems))
    corpus["header"]["note"] = "Scorer-validation corpus (seed 17). Every name, number and instruction is invented."
    out = HERE / "validation"
    (out / "corpus_val17.json").write_text(json.dumps(corpus, indent=1) + "\n")
    (out / "facts_val17.json").write_text(json.dumps(registry, indent=1) + "\n")
    qg.REG, qg.FACTS, qg.PROJECTS = registry, registry["facts"], registry["projects"]
    pool = qg.Pool()
    # design relations and projects only: the held-out ones stay out of this set by construction
    pool.atoms = [a for a in pool.atoms if not a["held_out"]]
    cases = qg.build_cases(pool, random.Random(1717), False, COUNTS, "V17")
    (HERE.parent / "cases_val17.json").write_text(json.dumps({"version": 1, "split": "val17", "corpus": "corpus_val17", "purpose": "scorer-v2 validation questions (seed 17, bank C, design relations/projects); not an acceptance set", "cases": cases}, indent=1) + "\n")
    print(len(cases), dict(collections.Counter(c["family"] for c in cases)), dict(collections.Counter(a["status"] for c in cases for a in c["atoms"])))
    print("distinct atoms by status:", dict(collections.Counter(a["status"] for a in {a["id"]: a for c in cases for a in c["atoms"]}.values())))
