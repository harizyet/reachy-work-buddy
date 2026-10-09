"""Corpus v5 manifest (owner decision 2026-10-15): 18 worlds, seeds 31-48. A NEW manifest (`validation/fresh_v5_manifest.json`); the 2026-10-14 manifest (seeds 19-30) is not overwritten. Stores hashes and the coverage
inventory only; worlds regenerate deterministically (`python fresh_v5_manifest.py --write DIR`). Nothing is evaluated here."""
from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen_v5 as g5
import questions_gen_v5 as q5

SEEDS = list(range(31, 49))


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def world(seed: int):
    corpus, registry = g5.build(seed)
    problems = g5.check_unique(registry)
    assert not problems, problems
    return corpus, registry, q5.build_cases(registry, seed)


if __name__ == "__main__":
    out = Path(sys.argv[sys.argv.index("--write") + 1]) if "--write" in sys.argv else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    worlds = {}
    for s in SEEDS:
        corpus, registry, cases = world(s)
        atoms = {a["id"]: a for c in cases for a in c["atoms"]}
        worlds[s] = {"corpus_sha256": digest(corpus), "facts_sha256": digest(registry), "cases_sha256": digest(cases), "questions": len(cases),
                     "distinct_atoms": dict(collections.Counter(a["status"] for a in atoms.values())),
                     "existence_conditions": dict(collections.Counter(a["condition"] for a in atoms.values() if a.get("family") == "existence"))}
        if out:
            (out / f"corpus_w{s}.json").write_text(json.dumps(corpus))
            (out / f"cases_w{s}.json").write_text(json.dumps({"cases": cases}))
    manifest = {"version": 5, "note": "hashes and counts only; regenerate with fresh_v5_manifest.py", "bank_e_sha256": hashlib.sha256((HERE / "banks_e.py").read_bytes()).hexdigest(), "worlds": worlds}
    (HERE / "validation" / "fresh_v5_manifest.json").write_text(json.dumps(manifest, indent=1))
    tot = collections.Counter()
    cond = collections.Counter()
    for w in worlds.values():
        tot.update(w["distinct_atoms"])
        cond.update(w["existence_conditions"])
    print(json.dumps(dict(tot)), dict(cond), "questions", sum(w["questions"] for w in worlds.values()))
