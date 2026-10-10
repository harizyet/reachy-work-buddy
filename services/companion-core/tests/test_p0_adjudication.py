"""Phase 44 final development pass: the blinded P0 adjudication tooling (benchmarks/answer_quality/selective/p0_adjudication.py). No model, dev15 only, dev16 untouched. The tooling turns a person's atom-level
labels of a free-text reply into the per-atom flags the unchanged evaluator consumes; these tests pin that conversion, the blinding and the agreement statistics."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load(name):
    saved = list(sys.argv)  # i2_eval replaces sys.argv with the B-1 configuration flags at import
    sys.path[:0] = [str(SEL), str(SEL.parent)]
    try:
        spec = importlib.util.spec_from_file_location(name, SEL / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv[:] = saved
        del sys.path[:2]


P0 = _load("p0_adjudication")
MAN = {"E1": {"refs": ["memory:m1"], "authorized": True}, "E2": {"refs": ["memory:m2"], "authorized": True}, "E3": {"refs": ["memory:m1"], "authorized": False}}


def atom(status, severe=False, display=("x",), aid="A1"):
    return {"id": aid, "status": status, "display": list(display), "severe": severe, "needs_citation": status in P0.ANSWERABLE, "sources": ["memory:m1"], "relation": "owner", "subject": "Cedar", "pretty": "Cedar"}


def flags(status, label, cited=(), severe=False):
    return P0.atom_outcome_from_label(atom(status, severe), label, list(cited), MAN)


# -- which labels a gold status allows --------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_label_the_gold_status_does_not_allow_is_refused_not_guessed():
    for status, label in (("SUPPORTED", "ASSERTS"), ("UNSUPPORTED", "STATES_ANSWER"), ("CONFLICTED", "STATES_ANSWER"), ("SUPPORTED", "HISTORY_AS_CURRENT"), ("NEGATIVE_UNSUPPORTED", "WRONG_VALUE")):
        with pytest.raises(P0.LabelError):
            flags(status, label)
    with pytest.raises(P0.LabelError):
        flags("SUPPORTED", "MAYBE")


# -- label to flag, one gold status at a time --------------------------------------------------------------------------------------------------------------------------------------------

def test_supported_atom_stated_with_a_supporting_citation_is_ok_and_faithful_and_a_wrong_or_missing_citation_is_not():
    ok = flags("SUPPORTED", "STATES_ANSWER", ["E1"])
    assert ok["stated"] and ok["ok"] and ok["faithful"] is True and ok["cited_ids"] == ["E1"]
    assert flags("SUPPORTED", "STATES_ANSWER", ["E2"])["faithful"] is False  # exists and is authorised, but is not a registered source of this atom
    assert flags("SUPPORTED", "STATES_ANSWER", ["E3"])["faithful"] is False  # an unauthorised record never supports a claim
    assert flags("SUPPORTED", "STATES_ANSWER", ["E9"])["faithful"] is False  # not in the manifest
    assert flags("SUPPORTED", "STATES_ANSWER", [])["faithful"] is False  # a stated claim with no citation


def test_each_failure_of_a_supported_atom_has_its_own_flag():
    assert flags("SUPPORTED", "WRONG_VALUE")["wrong_value"] and not flags("SUPPORTED", "WRONG_VALUE")["false_abstention"]
    for label in ("NOT_ESTABLISHED", "SILENT"):
        o = flags("SUPPORTED", label)
        assert o["false_abstention"] and not o["stated"] and not o["ok"] and o["identified"] == (label == "NOT_ESTABLISHED")


def test_a_historical_value_shown_as_current_is_as_current_not_a_wrong_value():
    o = flags("HISTORICAL", "HISTORY_AS_CURRENT", ["E1"])
    assert o["as_current"] and not o["wrong_value"] and not o["ok"] and not o["stated"]
    assert flags("HISTORICAL", "STATES_ANSWER", ["E1"])["ok"]


def test_a_conflict_must_be_stated_on_both_sides_and_choosing_a_side_is_resolution():
    both, one = flags("CONFLICTED", "CONFLICT_BOTH", ["E1"]), flags("CONFLICTED", "CONFLICT_ONE", ["E1"])
    assert both["both"] and both["ok"] and not both["resolved"]
    assert one["resolved"] and one["one_sided"] and not one["ok"] and not one["false_abstention"]
    assert flags("CONFLICTED", "NOT_ESTABLISHED")["false_abstention"]


def test_asserting_an_answer_for_a_gold_with_none_is_a_leak_and_severe_only_when_the_gold_says_so():
    assert flags("UNSUPPORTED", "ASSERTS")["leaked"] and not flags("UNSUPPORTED", "ASSERTS")["severe"] and not flags("UNSUPPORTED", "ASSERTS")["ok"]
    assert flags("UNSUPPORTED", "ASSERTS", severe=True)["severe"]
    assert flags("UNSUPPORTED", "NOT_ESTABLISHED")["ok"] and flags("UNSUPPORTED", "SILENT")["ok"] and not flags("UNSUPPORTED", "SILENT")["identified"]
    assert flags("NEGATIVE_UNSUPPORTED", "ASSERTS")["absence_claim"] and not flags("UNSUPPORTED", "ASSERTS")["absence_claim"]
    assert flags("ORDER_UNSUPPORTED", "ASSERTS")["invented_order"] and not flags("NEGATIVE_UNSUPPORTED", "ASSERTS")["invented_order"]


def test_a_supported_negative_is_stated_only_by_saying_there_is_none():
    assert flags("NEGATIVE_SUPPORTED", "STATES_ANSWER", ["E1"])["ok"]
    assert flags("NEGATIVE_SUPPORTED", "WRONG_VALUE")["wrong_value"]


# -- a row for the evaluator -----------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_row_needs_every_part_labelled_and_finds_bad_and_unauthorised_citations_by_code():
    case = {"id": "Q1", "family": "mixed", "question": "q", "atoms": [atom("SUPPORTED", aid="A1"), atom("UNSUPPORTED", aid="A2")]}
    entry = {"blanket": False, "atoms": {"A1": {"label": "STATES_ANSWER", "cited": ["E1"]}, "A2": {"label": "NOT_ESTABLISHED"}}}
    row = P0.row_from_labels(case, "Cedar is Pablo [E1] and [E9] and [E3].", MAN, entry, "P0")
    assert row["outcome"]["bad_citations"] == ["E9"] and row["outcome"]["unauthorized_citations"] == ["E3"] and not row["outcome"]["fully_correct"]
    clean = P0.row_from_labels(case, "Cedar is Pablo [E1].", MAN, entry, "P0")
    assert clean["outcome"]["fully_correct"]
    with pytest.raises(P0.LabelError):
        P0.row_from_labels(case, "r", MAN, {"blanket": False, "atoms": {"A1": {"label": "STATES_ANSWER"}}}, "P0")


def test_a_blanket_refusal_fails_the_question_even_when_every_part_is_labelled_ok():
    case = {"id": "Q1", "family": "mixed", "question": "q", "atoms": [atom("UNSUPPORTED")]}
    row = P0.row_from_labels(case, "I cannot help.", MAN, {"blanket": True, "atoms": {"A1": {"label": "NOT_ESTABLISHED"}}}, "P0")
    assert not row["outcome"]["fully_correct"]


# -- the conversion loses nothing on the deterministic path ---------------------------------------------------------------------------------------------------------------------------

def _label_of(o):
    if o["both"]:
        return "CONFLICT_BOTH"
    if o["resolved"]:
        return "CONFLICT_ONE"
    if o["as_current"]:
        return "HISTORY_AS_CURRENT"
    if o["wrong_value"]:
        return "WRONG_VALUE"
    if o["stated"]:
        return "STATES_ANSWER"
    if o["leaked"]:
        return "ASSERTS"
    return "NOT_ESTABLISHED" if o["identified"] else "SILENT"


def test_converting_the_candidates_own_flags_to_labels_and_back_reproduces_every_flag_on_dev15():
    dc, e = _load("deterministic_criteria"), sys.modules["i2b_eval"]
    cases_list = json.loads((SEL.parent / "cases_dev15.json").read_text())["cases"]
    cases = {c["id"]: c for c in cases_list}
    w = e.World()
    rows = dc.candidate_rows(w, cases_list, e.make_planners(w, cases_list)["T-new"])
    fields = ("stated", "identified", "leaked", "severe", "both", "one_sided", "resolved", "as_current", "false_abstention", "absence_claim", "invented_order", "wrong_value", "cited_ids", "faithful", "ok")
    checked = 0
    for r in rows:
        entry = {"blanket": r["outcome"]["blanket"], "atoms": {o["atom_id"]: {"label": _label_of(o), "cited": o["cited_ids"]} for o in r["outcome"]["atoms"]}}
        back = P0.row_from_labels(cases[r["id"]], r["reply"], r["manifest"], entry, "candidate")
        for a, b in zip(r["outcome"]["atoms"], back["outcome"]["atoms"], strict=True):
            checked += 1
            assert {f: a[f] for f in fields} == {f: b[f] for f in fields}, (r["id"], a["atom_id"])
        assert back["outcome"]["fully_correct"] == r["outcome"]["fully_correct"] or r["outcome"]["fully_correct"] is False  # the candidate row also fails on untyped / stray components, which a label cannot express
    assert checked == 307


# -- blinding --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _rows(n=30):
    cases = {f"Q{i}": {"id": f"Q{i}", "family": "mixed", "question": f"q{i}", "atoms": [atom("SUPPORTED", aid=f"A{i}")]} for i in range(n)}
    p0 = [{"id": k, "reply": f"P0 reply {k} [E1]"} for k in cases]
    cand = [{"id": k, "reply": f"The owner is X [E1]. ({k})"} for k in cases]
    return cases, p0, cand


def test_the_packet_hides_the_arm_and_the_key_is_the_only_way_back():
    cases, p0, cand = _rows()
    items, key = P0.build_packet(p0, cand, cases, seed=7)
    text = P0.render_packet(items)
    assert "P0" not in json.dumps([{k: v for k, v in it.items() if k != "reply"} for it in items]) and "candidate" not in text and "arm" not in text.lower().replace("part", "")
    assert len({it["oid"] for it in items}) == len(items) == len(key)
    assert {k["arm"] for k in key.values()} == {"P0", "candidate"} and sum(k["arm"] == "candidate" for k in key.values()) == round(30 * 0.2)
    assert P0.opaque(7, "P0", "Q1") != P0.opaque(7, "candidate", "Q1")


def test_the_packet_is_reproducible_from_the_seed_and_the_order_does_not_group_the_arms():
    cases, p0, cand = _rows()
    a, ka = P0.build_packet(p0, cand, cases, seed=7)
    b, kb = P0.build_packet(p0, cand, cases, seed=7)
    c, _ = P0.build_packet(p0, cand, cases, seed=8)
    assert a == b and ka == kb and [i["oid"] for i in a] != [i["oid"] for i in c]
    arms = [ka[i["oid"]]["arm"] for i in a]
    assert arms != sorted(arms) and arms != sorted(arms, reverse=True)


def test_an_incomplete_label_file_is_refused():
    cases, p0, cand = _rows(3)
    items, _ = P0.build_packet(p0, cand, cases, seed=1)
    labels = P0.template(items)
    assert len(P0.complete(labels, items)) >= len(items)
    for it in items:
        labels[it["oid"]]["blanket"] = False
        for a in it["atoms"]:
            labels[it["oid"]]["atoms"][a["id"]]["label"] = "NOT_ESTABLISHED"
    assert P0.complete(labels, items) == []


# -- agreement and the control ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_kappa_and_percent_agreement_on_known_values():
    assert P0.kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert P0.kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0  # no better than chance
    assert abs(P0.kappa(["a", "a", "a", "b"], ["a", "a", "b", "b"]) - 0.5) < 1e-9
    assert P0.kappa(["a", "a"], ["a", "a"]) == 1.0
    la = {"Q1": {"atoms": {"A1": {"label": "STATES_ANSWER"}, "A2": {"label": "SILENT"}}}}
    lb = {"Q1": {"atoms": {"A1": {"label": "STATES_ANSWER"}, "A2": {"label": "NOT_ESTABLISHED"}}}}
    ag = P0.agreement(la, lb)
    assert ag["parts"] == 2 and ag["percent_agreement"] == 0.5 and ag["disagreements"] == [{"oid": "Q1", "atom": "A2", "A": "SILENT", "B": "NOT_ESTABLISHED"}]


def test_the_control_reports_a_label_that_disagrees_with_the_exact_flags_of_a_candidate_reply():
    case = {"id": "Q1", "family": "mixed", "question": "q", "atoms": [atom("SUPPORTED")]}
    exact = P0.row_from_labels(case, "Pablo [E1]", MAN, {"blanket": False, "atoms": {"A1": {"label": "STATES_ANSWER", "cited": ["E1"]}}}, "candidate")
    key = {"Qx": {"arm": "candidate", "id": "Q1"}, "Qy": {"arm": "P0", "id": "Q2"}}
    same = {"Qx": {"blanket": False, "atoms": {"A1": {"label": "STATES_ANSWER", "cited": ["E1"]}}}}
    off = {"Qx": {"blanket": False, "atoms": {"A1": {"label": "NOT_ESTABLISHED", "cited": []}}}}
    kw = {"key": key, "candidate_rows": {"Q1": exact}, "cases": {"Q1": case}, "manifests": {"Q1": MAN}}
    assert P0.control_agreement(same, **kw)["parts_where_labels_and_exact_flags_differ"] == 0
    bad = P0.control_agreement(off, **kw)
    assert bad["parts_where_labels_and_exact_flags_differ"] == 1 and "stated" in bad["details"][0]["fields"]


def test_label_derived_rows_run_through_the_unchanged_evaluator():
    ev = _load("evaluator")
    case = {"id": "Q1", "family": "mixed", "question": "q", "atoms": [atom("SUPPORTED")]}
    row = P0.row_from_labels(case, "Pablo [E1]", MAN, {"blanket": False, "atoms": {"A1": {"label": "STATES_ANSWER", "cited": ["E1"]}}}, "P0")
    crit = ev.evaluate([row], [row], {"Q1": case})
    assert len(crit) == 10 and ev.EVALUATOR_VERSION == 3
