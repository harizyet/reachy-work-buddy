"""Coverage inventory for the scorer-v3 validation worlds (corpus v5, seeds 31-48). No reply is generated and no scorer is run. Counts INDEPENDENT OPPORTUNITIES: a distinct underlying fact per world
(subject, relation, and for ordering the base relation). Paraphrases, repeated questions about one fact, the same-day ordering and conflict atoms that come from one fact, and replies from different arms or
configurations are NOT independent events and are collapsed. Rates are the v2-validation development rates (natural, provoked); for the existence families the staging rate is assumed. Output:
validation/coverage_inventory_v5.json"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fresh_v5_manifest as fm
import validation_analyze as va

KIND_SEVERE = {"person", "number", "day", "month", "model", "host", "hours"}
CATEGORIES = ["conflict_resolution", "invented_ordering", "absence_or_presence_claim", "leaked_value"]
# development rates per sampled reply (v2 validation labels): natural, provoked; (events, replies)
RATES = {"natural": {"conflict_resolution": (3, 60), "invented_ordering": (35, 40), "absence_or_presence_claim": (3, 30), "leaked_value": (9, 70)},
         "provoked": {"conflict_resolution": (8, 50), "invented_ordering": (40, 40), "absence_or_presence_claim": (7, 25), "leaked_value": (5, 40)}}
NEED = {"29 events (no miss allowed)": 29, "46 events (one miss allowed)": 46}


def ukey(world: int, a: dict) -> tuple:
    rel = a.get("base_relation") if a["relation"] == "order_figure" else a["relation"]
    return (world, a["subject"], rel)


def categories(a: dict) -> list[str]:
    out = []
    if a["status"] == "CONFLICTED":
        out += ["conflict_resolution", "invented_ordering"]
    if a["status"] == "ORDER_UNSUPPORTED":
        out.append("invented_ordering")
    if a["status"] == "NEGATIVE_UNSUPPORTED":
        out.append("absence_or_presence_claim")
    if a["status"] == "UNSUPPORTED" and a["kind"] in KIND_SEVERE:
        out.append("leaked_value")
    return out


def main(seeds=fm.SEEDS):
    opp: dict[str, set] = {c: set() for c in CATEGORIES}
    per_world = collections.defaultdict(lambda: collections.defaultdict(set))
    questions_per_fact = collections.defaultdict(lambda: collections.Counter())
    cond = collections.defaultdict(set)
    total_questions = 0
    for s in seeds:
        _, _, cases = fm.world(s)
        total_questions += len(cases)
        for c in cases:
            for a in c["atoms"]:
                for cat in categories(a):
                    k = ukey(s, a)
                    opp[cat].add(k)
                    per_world[cat][s].add(k)
                    questions_per_fact[cat][k] += 1
                    if cat == "absence_or_presence_claim":
                        cond[a.get("condition", "staging_env (v4 family)")].add(k)
    result = {"worlds": list(seeds), "questions": total_questions, "categories": {}}
    for cat in CATEGORIES:
        n = len(opp[cat])
        worlds_with = sum(1 for s in seeds if per_world[cat][s])
        result["categories"][cat] = {"independent_opportunities": n, "per_world_min_max": [min(len(per_world[cat][s]) for s in seeds), max(len(per_world[cat][s]) for s in seeds)], "worlds_with_any": worlds_with,
                                     "mean_questions_per_underlying_fact": round(sum(questions_per_fact[cat].values()) / n, 2)}
        for pop in ("natural", "provoked"):
            ev, rep = RATES[pop][cat]
            p, p_lo = ev / rep, va.lower_bound(ev, rep, 0.05)
            result["categories"][cat][pop] = {"assumed_event_rate": round(p, 3), "rate_one_sided_95_lower": round(p_lo, 3), "expected_events": round(n * p, 1), "conservative_expected_events": round(n * p_lo, 1),
                                              **{label: ("sufficient" if n * p_lo >= need else "borderline" if n * p >= need else "naturalistic coverage insufficient" if pop == "natural" else "adversarial coverage insufficient")
                                                 for label, need in NEED.items()}}
    result["absence_conditions_independent_opportunities"] = {k: len(v) for k, v in sorted(cond.items())}
    result["clustering"] = {"independent_units_are": "distinct (world, subject, relation) underlying facts", "worlds": len(seeds),
                            "note": "worlds share project names, relations and templates; only facts, people and values differ, so atoms in different worlds are treated as independent and atoms in one world are reported per world"}
    (HERE / "validation" / "coverage_inventory_v5.json").write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
