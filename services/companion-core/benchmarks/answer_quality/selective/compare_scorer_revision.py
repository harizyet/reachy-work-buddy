"""Scorer v2 vs sealed v1 on the DEVELOPMENT data (the 142 adjudicated items, the 49 hand-labelled cases). Not validation of v2: these items motivated the revision. Prints agreement with rater A and the changed items."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import adjudicate_fresh as af
import scorer_v2


def run(label_file: str):
    import scorer as v1
    out = {}
    for name, mod in (("v1_sealed", v1), ("v2_revision", scorer_v2)):
        af.scorer = mod
        sc = af.scorer_flags()
        labels = json.loads(Path(label_file).read_text())["labels"]
        items = {i["key"]: i for i in json.loads((HERE / "adjudication_fresh_sample.json").read_text())["items"]}
        tp = fp = fn = tn = 0
        for k in items:
            truth = {f: f in labels[k]["flags"] for f in af.FLAGS}
            t, s = af.severe(truth), af.severe(sc[k])
            tp += t and s
            fn += t and not s
            fp += s and not t
            tn += (not t) and (not s)
        out[name] = {"severe": {"tp": tp, "fn": fn, "fp": fp, "tn": tn}, "flags": sc}
    changed = [k for k in out["v1_sealed"]["flags"] if out["v1_sealed"]["flags"][k] != out["v2_revision"]["flags"][k]]
    print("severe v1", out["v1_sealed"]["severe"], "v2", out["v2_revision"]["severe"])
    print("items whose flags changed v1->v2:", changed)
    for k in changed:
        a, b = out["v1_sealed"]["flags"][k], out["v2_revision"]["flags"][k]
        print(" ", k, {f: (a[f], b[f]) for f in a if a[f] != b[f]})


if __name__ == "__main__":
    run(sys.argv[1])
