"""Phase 44 I-2 follow-up: the deterministic definitions of the per-atom flags that feed the (unchanged) dev16 criteria. Each flag is pinned with a synthetic atom; no model, no corpus, dev16 untouched."""

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load():
    saved = list(sys.argv)  # i2_eval replaces sys.argv with the B-1 configuration flags at import
    sys.path[:0] = [str(SEL), str(SEL.parent)]
    try:
        spec = importlib.util.spec_from_file_location("deterministic_criteria", SEL / "deterministic_criteria.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv[:] = saved
        del sys.path[:2]


DC = _load()


@dataclass
class T:
    values: tuple = ()


@dataclass
class C:
    assertable: tuple = field(default_factory=tuple)


def atom(status, display=(), severe=False, sources=("memory:m1",), relation="owner"):
    return {"id": "A1", "status": status, "display": list(display), "severe": severe, "needs_citation": status in ("SUPPORTED", "HISTORICAL", "CONFLICTED", "NEGATIVE_SUPPORTED"), "sources": list(sources), "relation": relation}


MAN = {"E1": {"refs": ["memory:m1"], "authorized": True}, "E2": {"refs": ["memory:m2"], "authorized": True}, "E3": {"refs": ["memory:m1"], "authorized": False}}


def out(a, state, values=(), cites=()):
    return DC.atom_outcome(a, state, T(tuple((v, ("x",)) for v in values)) if state else None, C(tuple((v, c) for v, c in zip(values, cites or [("E1",)] * len(values), strict=False))) if state else None, MAN)


def test_a_supported_atom_answered_with_its_value_is_stated_ok_and_faithful():
    o = out(atom("SUPPORTED", ["Pablo Reyes"]), "SUPPORTED", ["Pablo Reyes"])
    assert o["stated"] and o["ok"] and o["faithful"] is True and not o["false_abstention"] and not o["wrong_value"] and o["cited_ids"] == ["E1"]


def test_a_supported_atom_withheld_or_not_typed_is_a_false_abstention():
    for state in ("UNSUPPORTED", None):
        o = out(atom("SUPPORTED", ["Pablo Reyes"]), state)
        assert o["false_abstention"] and not o["stated"] and not o["ok"]
    assert out(atom("SUPPORTED", ["Pablo Reyes"]), "UNSUPPORTED")["identified"] and not out(atom("SUPPORTED", ["Pablo Reyes"]), None)["identified"]


def test_an_existence_atom_is_stated_by_its_state_alone():
    a = {**atom("SUPPORTED", ["yes"], relation="staging_env"), "kind": "bool"}
    o = out(a, "SUPPORTED", ["present"])
    assert o["stated"] and o["ok"] and not o["wrong_value"]


def test_a_wrong_value_is_neither_stated_nor_ok():
    o = out(atom("SUPPORTED", ["Pablo Reyes"]), "SUPPORTED", ["Olga Petrova"])
    assert o["wrong_value"] and not o["stated"] and not o["ok"]


def test_a_cited_record_that_is_not_a_registered_source_or_not_authorised_is_not_faithful():
    assert out(atom("SUPPORTED", ["P"]), "SUPPORTED", ["P"], [("E2",)])["faithful"] is False
    assert out(atom("SUPPORTED", ["P"]), "SUPPORTED", ["P"], [("E3",)])["faithful"] is False
    assert out(atom("SUPPORTED", ["P"]), "SUPPORTED", ["P"], [("E1", "E2")])["faithful"] is False  # every displayed id must support the claim (evaluator v3)


def test_a_many_valued_relation_must_show_exactly_the_gold_set():
    a = atom("SUPPORTED", ["A B", "C D"], relation="attends")
    assert out(a, "SUPPORTED", ["A B", "C D"])["stated"]
    assert out(a, "SUPPORTED", ["A B"])["wrong_value"]


def test_a_conflict_needs_both_values_and_one_side_is_a_resolution():
    a = atom("CONFLICTED", ["10", "12"])
    both = out(a, "CONFLICTED", ["10", "12"])
    assert both["both"] and both["ok"] and not both["resolved"]
    one = out(a, "SUPPORTED", ["10"])
    assert one["resolved"] and one["one_sided"] and not one["ok"]
    assert out(a, "UNSUPPORTED")["false_abstention"]


def test_history_shown_as_current_is_not_ok():
    a = atom("HISTORICAL", ["Merlin-2B"])
    assert out(a, "HISTORICAL", ["Merlin-2B"])["ok"]
    o = out(a, "SUPPORTED", ["Merlin-2B"])
    assert o["as_current"] and not o["ok"]


def test_any_answer_to_a_withheld_gold_is_a_leak_and_severe_when_the_gold_says_so():
    for status in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED"):
        a = atom(status, severe=True)
        assert out(a, status)["ok"] and not out(a, status)["leaked"]
        o = out(a, "SUPPORTED", ["X"])
        assert o["leaked"] and o["severe"] and not o["ok"]
    assert out(atom("UNSUPPORTED", severe=False), "SUPPORTED", ["X"])["severe"] is False
    assert out(atom("NEGATIVE_UNSUPPORTED"), "NEGATIVE_SUPPORTED")["absence_claim"]
    assert out(atom("ORDER_UNSUPPORTED"), "SUPPORTED", ["a", "b"])["invented_order"]


def test_a_withheld_gold_that_was_not_typed_is_not_a_leak_but_is_not_identified_either():
    o = out(atom("UNSUPPORTED"), None)
    assert o["ok"] and not o["leaked"] and not o["identified"]
