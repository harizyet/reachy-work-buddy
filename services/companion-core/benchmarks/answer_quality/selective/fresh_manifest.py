"""Fresh validation-corpus manifest for the scorer-v3 validation (plan only; no reply is generated). Worlds are the same generator at seeds 19-30, design relations and projects, bank C, v17's question mix. Only hashes are
stored; the worlds regenerate deterministically (`python fresh_manifest.py --write DIR` writes them out). Seed 17 is excluded (v2 validation, now development data); so are 14 (dev15) and the dev16 candidates."""
from __future__ import annotations

import collections
import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen as gen
import questions_gen as qg
import validation_gen as vg

SEEDS = list(range(19, 31))


def build(seed: int):
    gen.SEED = seed
    corpus, registry = gen.build()
    assert not gen.check_unique(registry)
    corpus["header"]["note"] = f"Scorer-v3 validation world, seed {seed}. Every name, number and instruction is invented."
    qg.REG, qg.FACTS, qg.PROJECTS = registry, registry["facts"], registry["projects"]
    pool = qg.Pool()
    pool.atoms = [a for a in pool.atoms if not a["held_out"]]
    cases = qg.build_cases(pool, random.Random(seed * 100 + 17), False, vg.COUNTS, f"W{seed}")
    return corpus, registry, cases


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":
    out = None
    if "--write" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--write") + 1])
        out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for s in SEEDS:
        corpus, registry, cases = build(s)
        atoms = {a["id"]: a for c in cases for a in c["atoms"]}
        manifest[s] = {"corpus_sha256": digest(corpus), "facts_sha256": digest(registry), "cases_sha256": digest(cases), "questions": len(cases),
                       "distinct_atoms": dict(collections.Counter(a["status"] for a in atoms.values()))}
        if out:
            (out / f"corpus_w{s}.json").write_text(json.dumps(corpus))
            (out / f"cases_w{s}.json").write_text(json.dumps({"cases": cases}))
    (HERE / "validation" / "fresh_corpus_manifest.json").write_text(json.dumps({"note": "plan only; regenerate with fresh_manifest.py", "seeds": manifest}, indent=1))
    tot = collections.Counter()
    for m in manifest.values():
        tot.update(m["distinct_atoms"])
    print(json.dumps(dict(tot)), "questions", sum(m["questions"] for m in manifest.values()))
