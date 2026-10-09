"""Development evaluation of scorer v1/v2/v3 on the v3 development probes (semantic contrasts). Development data: the detector was iterated against these."""
from __future__ import annotations

import collections
import importlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from validate_scorer import PEOPLE


def flagged(o, kind, status):
    if kind == "resolved":
        return bool(o.resolved)
    if kind == "invented_order":
        return bool(o.invented_order)
    if kind == "absence_or_presence":
        return bool(o.absence_claim or (status == "NEGATIVE_UNSUPPORTED" and o.leaked))
    return bool(o.leaked and o.severe)


def run(module, path="validation/dev_probes_v3.json", show=0):
    sc = importlib.import_module(module)
    probes = json.loads((HERE / path).read_text())["probes"]
    cells = collections.defaultdict(lambda: [0, 0])
    wrong = []
    for p in probes:
        o = sc.score_question(p["reply"], p["atoms"], p["manifest"], PEOPLE).atoms[p["atom_index"]]
        hit = flagged(o, p["severe_kind"], p["atoms"][0]["status"])
        want = p["label"] == "violation"
        cells[(p["family"], p["label"])][0] += hit == want
        cells[(p["family"], p["label"])][1] += 1
        if hit != want:
            wrong.append((p["family"], p["label"], p["position"], p["reply"].replace("\n", " / ")))
    return cells, wrong


if __name__ == "__main__":
    for module in ("scorer", "scorer_v2", "scorer_v3"):
        cells, wrong = run(module)
        print("==", module)
        for (fam, label), (ok, n) in sorted(cells.items()):
            print(f"   {fam:28s} {label:9s} correct {ok:3d}/{n}")
        if module == "scorer_v3":
            for w in wrong[: int(sys.argv[1]) if len(sys.argv) > 1 else 30]:
                print("   WRONG", w)
