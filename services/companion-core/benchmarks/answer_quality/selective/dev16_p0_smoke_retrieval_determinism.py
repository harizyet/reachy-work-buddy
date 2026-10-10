"""Retrieval-only determinism probe for the P0 path (Phase 44 smoke test, 2026-10-10). Builds the disposable test database TWICE from the same corpus and runs only the retrieval/prompt-assembly step of the pinned
P0 configuration (`GConditions2.prepare('b1a', case)`) for the smoke cases: NO model call. Compares the ordered evidence across the two builds and against the smoke run. Consumed dev15 data, disposable database.

    python dev16_p0_smoke_retrieval_determinism.py <smoke-output-dir>      (KBENCH_DATABASE_URL must name the disposable server)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path.insert(0, str(HERE))
import dev16_p0 as p0
import dev16_runner as r


def evidence(out: Path, cases: list[dict]) -> dict:
    ex = p0.RealP0Executor(HERE / "corpus_v4.json")
    ex.open()
    try:
        res = {}
        for c in cases:
            prep = ex.loop.run_until_complete(ex.runner.prepare("b1a", c))
            res[c["id"]] = [(eid, tuple(e.refs)) for eid, e in sorted(prep.evidence.items(), key=lambda kv: int(kv[0][1:]))]
        return res
    finally:
        ex.close()


def main(out: Path) -> dict:
    cases = json.loads((out / "cases_smoke_dev15.json").read_text())["cases"]
    a, b = evidence(out, cases), evidence(out, cases)
    smoke = {x["id"]: [(k, tuple(x["manifest"][k]["refs"])) for k in sorted(x["manifest"], key=lambda k: int(k[1:]))] for x in r.read_jsonl(out / "runs" / "smoke-dev15-1" / "p0_rows.jsonl")}
    pilot = {x["id"]: [(k, tuple(x["manifest"][k]["refs"])) for k in sorted(x["manifest"], key=lambda k: int(k[1:]))] for x in json.loads((HERE.parent / "results" / "pilot-dev15-7b.json").read_text())["rows"] if x["arm"] == "b1a"}
    sets = lambda ev: {i: {ref for _, refs in v for ref in refs} for i, v in ev.items()}
    rep = {"purpose": "retrieval-only probe, no model call", "cases": len(cases), "two_fresh_builds_identical_ordered_evidence": sum(a[c["id"]] == b[c["id"]] for c in cases),
           "two_fresh_builds_identical_set": sum(sets(a)[c["id"]] == sets(b)[c["id"]] for c in cases), "build1_vs_smoke_identical_ordered": sum(a[c["id"]] == smoke[c["id"]] for c in cases),
           "build1_vs_smoke_identical_set": sum(sets(a)[c["id"]] == sets(smoke)[c["id"]] for c in cases), "smoke_vs_pilot_identical_ordered": sum(smoke[i] == pilot[i] for i in pilot if i in smoke),
           "smoke_vs_pilot_identical_set": sum(sets(smoke)[i] == sets(pilot)[i] for i in pilot if i in smoke), "pilot_cases_compared": sum(1 for i in pilot if i in smoke)}
    (out / "RETRIEVAL_DETERMINISM.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    print(json.dumps(main(Path(ORIG[1])), indent=1))
