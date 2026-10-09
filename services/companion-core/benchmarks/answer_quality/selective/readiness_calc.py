"""Validation-readiness arithmetic for the scorer-v3 gate (no model; no reply generated). Opportunities per world come from the generator itself; event rates come from the v2 validation labels (val17, rater A), which are now development data;
sample sizes come from exact binomial bounds."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen as gen
import questions_gen as qg
import validation_analyze as va

SEEDS = [19, 20, 21, 22]
KIND_SEVERE = {"person", "number", "day", "month", "model", "host", "hours"}


def world(seed: int):
    gen.SEED = seed
    corpus, registry = gen.build()
    problems = gen.check_unique(registry)
    assert not problems, problems
    qg.REG, qg.FACTS, qg.PROJECTS = registry, registry["facts"], registry["projects"]
    pool = qg.Pool()
    atoms = [a for a in pool.atoms if not a["held_out"]]
    return corpus, registry, atoms


def opportunities(atoms):
    c = collections.Counter(a["status"] for a in atoms)
    return {"conflict_resolution (CONFLICTED atoms)": c["CONFLICTED"], "invented_ordering (ORDER_UNSUPPORTED + CONFLICTED atoms)": c["ORDER_UNSUPPORTED"] + c["CONFLICTED"],
            "absence_or_presence (NEGATIVE_UNSUPPORTED atoms)": c["NEGATIVE_UNSUPPORTED"], "leaked_value (UNSUPPORTED atoms of a severe kind)": sum(1 for a in atoms if a["status"] == "UNSUPPORTED" and a["kind"] in KIND_SEVERE)}


def rates():
    labels = json.loads((HERE / "validation" / "validation_labels_raterA.json").read_text())["labels"]
    sample = json.loads((HERE / "validation" / "validation_sample.json").read_text())["items"]
    [json.loads(x) for x in (HERE / "validation" / "replies_val17.jsonl").read_text().splitlines()]
    cases = {c["id"]: c for c in json.loads((HERE.parent / "cases_val17.json").read_text())["cases"]}
    out = {}
    for pop in ("natural", "provoked"):
        cnt = collections.defaultdict(lambda: [0, 0])
        for it in sample:
            if it["population"] != pop:
                continue
            status = cases[it["case"]]["atoms"][it["atom"]]["status"]
            fl = set(labels[it["key"]]["flags"])
            cat = {"CONFLICTED": "conflict_resolution", "ORDER_UNSUPPORTED": "invented_ordering", "NEGATIVE_UNSUPPORTED": "absence_or_presence_claim", "UNSUPPORTED": "leaked_value"}.get(status)
            if not cat:
                continue
            ev = ("resolved" in fl) if cat == "conflict_resolution" else ("invented_order" in fl) if cat == "invented_ordering" else ("leaked" in fl and "severe" in fl) if cat == "leaked_value" else ("absence_claim" in fl or "leaked" in fl)
            cnt[cat][0] += ev
            cnt[cat][1] += 1
        out[pop] = {k: {"events": v[0], "replies": v[1], "rate": round(v[0] / v[1], 3), "rate_one_sided_95_lower": round(va.lower_bound(v[0], v[1], 0.05), 3)} for k, v in cnt.items()}
    return out


def min_n(max_misses: int, target=0.90):
    for n in range(max_misses + 1, 400):
        if va.lower_bound(n - max_misses, n, 0.05) >= target:
            return n
    return None


if __name__ == "__main__":
    result = {"worlds": {}}
    for s in SEEDS:
        _, reg, atoms = world(s)
        result["worlds"][s] = opportunities(atoms)
    result["rates_from_val17_development_labels"] = rates()
    result["min_events_for_90pct_one_sided_lower_bound"] = {f"{m} misses": min_n(m) for m in range(6)}
    result["min_true_positives_for_80pct_precision_lower_bound"] = {f"{fp} false positives": next(n for n in range(1, 200) if va.lower_bound(n, n + fp, 0.05) >= 0.80) for fp in range(5)}
    result["zero_fp_upper_bound_on_controls"] = {str(n): round(va.upper_bound(0, n, 0.05), 4) for n in (60, 100, 200, 300)}
    (HERE / "validation" / "readiness_calc.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
