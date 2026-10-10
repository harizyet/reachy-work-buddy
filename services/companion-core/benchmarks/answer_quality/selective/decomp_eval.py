"""Measure the question-side decomposer on the labelled structure set (`decomposition_dev_set.json`, frozen by `DECOMPOSITION_SET.sha256` before the decomposer was first run). No model, no gold.

Per question: the typed components must equal the labelled parts exactly (subject, relation, ask, scope, stated month) and the number of withheld clauses must equal the labelled `unc`. Field-level
accuracy is reported over the labelled parts. The safety number is INVENTED STRUCTURES: a typed component that is not one of the labelled parts (including any component produced for a clause that should
have been withheld). The coverage number is MISSED PARTS: a labelled part that was withheld or lost. A decomposer may miss parts (it then withholds); it may not invent them.

    python decomp_eval.py [--set dev|heldout] [--json out.json] [--quiet]
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from companion_core.knowledge.answerability_b1.questions import decompose_question
from companion_core.knowledge.answerability_b1.registry import Registry
from companion_core.knowledge.answerability_b1.types import Ask, Scope

SETS = {"dev": ("decomposition_dev_set.json", "DECOMPOSITION_SET.sha256"), "heldout": ("decomposition_heldout_set.json", "HELDOUT_SET.sha256")}
SET = "dev"


def verify_freeze() -> None:
    for line in (HERE / SETS[SET][1]).read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        digest, name = line.split()
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"FROZEN FILE CHANGED: {name}")


def key(part: dict) -> tuple:
    return (part["subject"].casefold(), part["relation"], part["ask"], part["scope"], tuple(part["period"]) if part["period"] else None)


def obj_of(registry: Registry, relation: str, ask: str) -> str:
    """The kind of answer a typed component asks for: existence and ordering are their own objects; otherwise the value kind of its relation (derived from the relation's definition, not from the question)."""
    if ask == "existence":
        return "existence"
    if ask == "ordering":
        return "order"
    r = registry.relation(relation)
    return r.kind if r else "?"


def produced(clauses) -> list[dict]:
    out = []
    for c in clauses:
        if c.component is None:
            continue
        k = c.component
        out.append({"subject": k.subject, "relation": k.relation, "ask": k.ask.value if isinstance(k.ask, Ask) else k.ask, "scope": k.scope.value if isinstance(k.scope, Scope) else k.scope,
                    "period": list(k.period) if k.period else None})
    return out


def evaluate(registry: Registry | None = None) -> dict:
    registry = registry or Registry()
    items = json.loads((HERE / SETS[SET][0]).read_text())["items"]
    n = collections.Counter()
    by_cat = collections.defaultdict(collections.Counter)
    failures, reasons = [], collections.Counter()
    fields = collections.Counter()
    for it in items:
        dec = decompose_question(it["q"], registry)
        got = produced(dec.clauses)
        unc = len(dec.uncertain)
        want = it["parts"]
        wk, gk = collections.Counter(map(key, want)), collections.Counter(map(key, got))
        invented = list((gk - wk).elements())
        missed = list((wk - gk).elements())
        exact = not invented and not missed and unc == it["unc"]
        for c in dec.uncertain:
            reasons[c.reason] += 1
        n["questions"] += 1
        n["exact"] += exact
        n["count_ok"] += (len(got) + unc) == (len(want) + it["unc"])
        n["parts_expected"] += len(want)
        n["parts_found_exact"] += sum((wk & gk).values())
        n["missed_parts"] += len(missed)
        n["invented_structures"] += len(invented)
        n["withheld_clauses_expected"] += it["unc"]
        n["withheld_clauses_produced"] += unc
        n["questions_with_invented"] += bool(invented)
        for e in want:  # field level over the labelled parts
            same_sr = [g for g in got if g["subject"].casefold() == e["subject"].casefold() and g["relation"] == e["relation"]]
            fields["parts"] += 1
            fields["subject_ok"] += any(g["subject"].casefold() == e["subject"].casefold() for g in got)
            if same_sr:
                g = same_sr[0]
                fields["relation_ok"] += 1
                fields["ask_ok"] += g["ask"] == e["ask"]
                fields["scope_ok"] += g["scope"] == e["scope"]
                fields["period_ok"] += g["period"] == e["period"]
                fields["located"] += 1
                fields["object_ok"] += obj_of(registry, g["relation"], g["ask"]) == e["obj"]
        by_cat[it["cat"]]["questions"] += 1
        by_cat[it["cat"]]["exact"] += exact
        by_cat[it["cat"]]["invented"] += len(invented)
        by_cat[it["cat"]]["missed"] += len(missed)
        if not exact:
            failures.append({"id": it["id"], "cat": it["cat"], "hard": it["hard"], "q": it["q"], "want": [(w["subject"], w["relation"], w["ask"], w["scope"], w["period"]) for w in want], "want_unc": it["unc"],
                             "got": [(g["subject"], g["relation"], g["ask"], g["scope"], g["period"]) for g in got], "got_unc": unc, "reasons": [c.reason for c in dec.uncertain],
                             "invented": [k[:2] for k in invented], "missed": [k[:2] for k in missed]})
    hard = [f for f in failures if f["hard"]]
    return {"counts": dict(n), "fields": dict(fields), "by_category": {k: dict(v) for k, v in by_cat.items()}, "withhold_reasons": dict(reasons), "failures": failures,
            "failures_not_marked_hard": [f for f in failures if not f["hard"]], "marked_hard_total": sum(i["hard"] for i in items), "marked_hard_failed": len(hard)}


def main() -> None:
    global SET
    if "--set" in sys.argv:
        SET = sys.argv[sys.argv.index("--set") + 1]
    verify_freeze()
    r = evaluate()
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(r, indent=1, default=str))
    c, f = r["counts"], r["fields"]
    print(f"questions {c['questions']}: exact structure {c['exact']} ({c['exact'] / c['questions']:.1%}); sub-claim count right {c['count_ok']}")
    print(f"parts expected {c['parts_expected']}: found exactly {c['parts_found_exact']}, missed (withheld or lost) {c['missed_parts']}; INVENTED structures {c['invented_structures']} in {c['questions_with_invented']} questions")
    print(f"withheld clauses: expected {c['withheld_clauses_expected']}, produced {c['withheld_clauses_produced']}")
    print(f"fields over {f['parts']} labelled parts: subject {f['subject_ok']}, relation {f['relation_ok']} (subject+relation located {f['located']}); of the located: ask {f['ask_ok']}, scope {f['scope_ok']}, period {f['period_ok']}, object kind {f['object_ok']}")
    for cat, v in sorted(r["by_category"].items()):
        print(f"  {cat:13s} exact {v['exact']:3d}/{v['questions']:3d}  invented {v['invented']:2d}  missed {v['missed']:2d}")
    print("withhold reasons:", r["withhold_reasons"])
    print(f"marked hard: {r['marked_hard_total']}, of which failed {r['marked_hard_failed']}")
    if "--quiet" not in sys.argv:
        print("failures:")
        for x in r["failures"]:
            print(f"  {x['id']} [{x['cat']}{' HARD' if x['hard'] else ''}] {x['q']}\n      want {x['want']} unc {x['want_unc']}\n      got  {x['got']} unc {x['got_unc']} {x['reasons']}")


if __name__ == "__main__":
    main()
