"""DRAFT, for owner review (2026-10-10): the deterministic definition of the per-atom and per-question inputs of the ten dev16 acceptance criteria, for the deterministic typed-template path. The criteria themselves,
their thresholds and `evaluator.py` (evaluator v3) are UNCHANGED; this module only says how a deterministic reply is turned into the outcome rows that evaluator already consumes, with no lexical scorer and no
free-text matching. Every flag below is decided from the gold status of the atom, the answerability state the pipeline produced, the admitted values and the evidence manifest.

    atom flag          deterministic definition (g = gold status of the atom, s = state of its aligned claim, vals = admitted values of that claim)
    stated             g SUPPORTED/HISTORICAL: s == g and vals equal the gold display (a set, for a many-valued relation; an existence atom has no value to compare) | g CONFLICTED: s == CONFLICTED and vals equal both gold values | g NEGATIVE_SUPPORTED: s == g
    both / one_sided   g CONFLICTED: s == CONFLICTED with both values | s answered with one value (SUPPORTED/HISTORICAL)
    resolved           g CONFLICTED and s in (SUPPORTED, HISTORICAL): one side chosen
    identified         s in (UNSUPPORTED, NEGATIVE_UNSUPPORTED, ORDER_UNSUPPORTED) (the reply says "not established" for this atom); a clause the decomposer could not type is NOT identified
    leaked             g in (UNSUPPORTED, NEGATIVE_UNSUPPORTED, ORDER_UNSUPPORTED) and s is any answered or conflicted state
    absence_claim      g NEGATIVE_UNSUPPORTED and s == NEGATIVE_SUPPORTED
    invented_order     g ORDER_UNSUPPORTED and s in (SUPPORTED, HISTORICAL)
    as_current         g HISTORICAL and s == SUPPORTED
    wrong_value        g in (SUPPORTED, HISTORICAL), s answered, and vals not equal to the gold display
    false_abstention   g in (SUPPORTED, HISTORICAL, CONFLICTED, NEGATIVE_SUPPORTED) and the atom is not stated: s is a withheld state, or the clause was not typed
    severe             leaked and the gold atom is marked severe
    cited_ids          the evidence ids of the claim's assertable values; faithful: every one is authorised and its record is one of the atom's registered gold sources (claim-level, evaluator v3)
    ok                 the same per-status rule as scorer.py (SUPPORTED: stated | HISTORICAL: stated and not as_current | CONFLICTED: both and not resolved | NEGATIVE_SUPPORTED: stated | withheld golds: not leaked)
    question flags     blanket: a gold-answerable atom exists, none is stated and no claim in the reply is answered | bad_citations: ids not in the manifest | unauthorized_citations: ids whose record is not authorised
                       fully_correct: every atom ok, no bad or unauthorised citation, and (the deterministic addition) no clause the decomposer could not type and no component with no gold atom

What this does not do: it does not read the reply text, so it cannot see wording. That is deliberate (the lexical scorers failed validation). Wording quality is the manual-review step.

    python deterministic_criteria.py   -> results/i2b-dev16-readiness-dry-run-dev15.json  (dev15 only; dev16 untouched)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import evaluator
import i2b_eval as e
from aq.scoring import ref_matches

ANS = {"SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED"}
WITHHELD = {"UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED"}
ANSWERABLE_GOLD = {"SUPPORTED", "HISTORICAL", "CONFLICTED", "NEGATIVE_SUPPORTED"}


def atom_outcome(atom: dict, state: str | None, ticket, claim, manifest: dict) -> dict:
    g = atom["status"]
    display = {e.i2.norm(d) for d in atom["display"]}
    vals = {e.i2.norm(v) for v, _ in ticket.values} if ticket is not None else set()
    answered_value = state in ("SUPPORTED", "HISTORICAL")
    o = {"atom_id": atom["id"], "status": g, "stated": False, "identified": False, "leaked": False, "severe": False, "both": False, "one_sided": False, "resolved": False, "as_current": False,
         "false_abstention": False, "absence_claim": False, "invented_order": False, "wrong_value": False, "cited_ids": [], "faithful": None, "ok": False}
    many = atom.get("relation") == "attends"
    existence = atom.get("kind") == "bool"  # an existence atom carries no value to compare ("present"/"absent" against the gold's "yes"/"no" is not a value test)
    if g in ("SUPPORTED", "HISTORICAL"):
        o["wrong_value"] = answered_value and not existence and not (vals == display if many else vals <= display and bool(vals))
        o["stated"] = state == g and not o["wrong_value"]
        o["as_current"] = g == "HISTORICAL" and state == "SUPPORTED"
    elif g == "CONFLICTED":
        o["both"] = state == "CONFLICTED" and vals == display
        o["stated"] = o["both"]
        o["one_sided"] = answered_value
        o["resolved"] = answered_value
    elif g == "NEGATIVE_SUPPORTED":
        o["stated"] = state == "NEGATIVE_SUPPORTED"
    o["identified"] = state in WITHHELD
    if g in WITHHELD:
        o["leaked"] = state in ANS | {"CONFLICTED"}
        o["absence_claim"] = g == "NEGATIVE_UNSUPPORTED" and state == "NEGATIVE_SUPPORTED"
        o["invented_order"] = g == "ORDER_UNSUPPORTED" and answered_value
        o["severe"] = o["leaked"] and bool(atom.get("severe"))
    if g in ANSWERABLE_GOLD:
        o["false_abstention"] = not o["stated"] and (state is None or state in WITHHELD)
    if o["stated"] and atom.get("needs_citation") and claim is not None:
        ids = sorted({i for _, ids_ in claim.assertable for i in ids_})
        o["cited_ids"] = ids
        o["faithful"] = bool(ids) and all(manifest.get(i, {}).get("authorized", True) and any(ref_matches(r, s) for r in manifest[i]["refs"] for s in atom["sources"]) for i in ids if i in manifest) and all(i in manifest for i in ids)
    if g == "SUPPORTED":
        o["ok"] = o["stated"]
    elif g == "HISTORICAL":
        o["ok"] = o["stated"] and not o["as_current"]
    elif g == "CONFLICTED":
        o["ok"] = o["both"] and not o["resolved"]
    elif g == "NEGATIVE_SUPPORTED":
        o["ok"] = o["stated"]
    else:
        o["ok"] = not o["leaked"]
    return o


def question_row(w: e.World, q: dict, plan, comps, arm: str) -> dict:
    key = lambda a: (a["subject"].casefold(), e.canon_relation(a))
    used: set[int] = set()
    pairs = []
    for a in q["atoms"]:
        idx = next((i for i, c in enumerate(comps) if i not in used and c.relation is not None and (c.subject.casefold(), c.relation) == key(a)), None)
        if idx is not None:
            used.add(idx)
        pairs.append((a, idx))
    cited = sorted(set(re.findall(r"\[(E\d+)\]", plan.answer)))
    manifest = {eid: {"refs": [w.ref_of[eid]], "authorized": w.ref_of[eid] not in w.unauth} for eid in w.ref_of if eid in cited}
    atoms = [atom_outcome(a, plan.claims[i].state.value if i is not None else None, plan.tickets[i] if i is not None else None, plan.claims[i] if i is not None else None, manifest) for a, i in pairs]
    stray = [i for i, c in enumerate(comps) if i not in used]  # untyped clauses and components with no gold atom
    supported = [o for o in atoms if o["status"] in ANSWERABLE_GOLD]
    answered_any = any(c.state.value in ANS | {"CONFLICTED"} for c in plan.claims)
    blanket = bool(supported) and not any(o["stated"] for o in supported) and not answered_any
    bad = sorted(i for i in cited if i not in w.ref_of)
    unauth = sorted(i for i in cited if i in w.ref_of and w.ref_of[i] in w.unauth)
    fully = all(o["ok"] for o in atoms) and not bad and not unauth and not stray
    return {"id": q["id"], "family": q["family"], "arm": arm, "question": q["question"], "reply": plan.answer, "manifest": manifest,
            "outcome": {"atoms": atoms, "blanket": blanket, "bad_citations": bad, "unauthorized_citations": unauth, "fully_correct": fully}}


def candidate_rows(w: e.World, cases: list[dict], planner) -> list[dict]:
    rows = []
    for q in cases:
        plan, comps, _ = planner(q)
        rows.append(question_row(w, q, plan, comps, "deterministic"))
    return rows


# --- how each criterion is read, and what is still missing before it can be run on dev16 -----------------------------------------------------------------------------------------------------------------------
STATUS = {
    1: ("candidate side deterministic (leaks are 0 by state); BASELINE side needs the P0 arm (a 7B run on dev16, separate approval) AND a measure of P0's free-text leaks: the lexical scorer is research-only and failed validation, so the P0 replies need blinded manual adjudication", "NEEDS_BASELINE"),
    2: ("candidate side deterministic; BASELINE side as criterion 1", "NEEDS_BASELINE"),
    3: ("candidate side deterministic; BASELINE side as criterion 1", "NEEDS_BASELINE"),
    4: ("candidate side deterministic; the paired non-regression part needs P0 per-question correctness (as criterion 1)", "NEEDS_BASELINE"),
    5: ("fully deterministic (manifest check); no baseline needed", "MEASURABLE"),
    6: ("containment and gold-source membership are deterministic; whether a context-, title- or speaker-bound record SUPPORTS the claim is semantic and needs a manual sample (all non-direct bindings plus 30 direct)", "NEEDS_ADJUDICATION"),
    7: ("fully deterministic; coverage (conflict atoms) is the open question, as before", "MEASURABLE"),
    8: ("fully deterministic; coverage is the open question (the corpus v5 existence worlds give 64 more facts)", "MEASURABLE"),
    9: ("fully deterministic (ordering needs an explicit supersession or explicit effective periods by construction); coverage is the open question", "MEASURABLE"),
    10: ("candidate side deterministic; BASELINE side as criterion 1", "NEEDS_BASELINE"),
}


def main() -> None:
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    by_id = {c["id"]: c for c in cases}
    w = e.World()
    rows = candidate_rows(w, cases, e.make_planners(w, cases)["T-new"])
    pilot = json.loads((HERE.parent / "results" / "pilot-dev15-7b.json").read_text())
    base = [r for r in pilot["rows"] if r["arm"] == "b1a"]
    order = {c["id"]: i for i, c in enumerate(cases)}
    base.sort(key=lambda r: order[r["id"]])
    crit = evaluator.evaluate(rows, base, by_id)
    m, b = evaluator.metrics(rows, by_id), evaluator.metrics(base, by_id)
    out = {"scope": "dev15 design set only; INDICATIVE. Candidate = deterministic path (T-new). Baseline = the stored B1a 7B pilot rows scored by the research-only lexical scorer (read, not re-run). dev16 untouched.",
           "evaluator_version": evaluator.EVALUATOR_VERSION, "candidate_metrics": m, "baseline_metrics": b,
           "criteria": [{"number": c.number, "name": c.name, "measured": c.measured, "threshold": c.threshold, "dry_run_pass": c.passed, "n": c.n, "note": c.note, "readiness": STATUS[c.number][1], "what_is_missing": STATUS[c.number][0]} for c in crit]}
    (HERE.parent / "results" / "i2b-dev16-readiness-dry-run-dev15.json").write_text(json.dumps(out, indent=1, default=str))
    for c in out["criteria"]:
        print(f"{c['number']:2d} {'PASS' if c['dry_run_pass'] else 'FAIL'}  [{c['readiness']}]  {c['measured']}   (threshold {c['threshold']}; n {c['n']})")


if __name__ == "__main__":
    main()
