"""Phase 44 final development pass: the deterministic candidate is frozen by hash before acceptance (selective/candidate_freeze.py). This test fails when a frozen file, the relation definitions or the
registry change without a new freeze being written and named in the record. It does not freeze or touch dev16."""

import importlib.util
import json
import sys
from pathlib import Path

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load():
    spec = importlib.util.spec_from_file_location("candidate_freeze", SEL / "candidate_freeze.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["candidate_freeze"] = mod
    spec.loader.exec_module(mod)
    return mod


CF = _load()


def test_the_frozen_candidate_is_intact():
    assert CF.check() == [], "a frozen file changed: write a new freeze (candidate_freeze.py --write under a new name) and name it in the record"


def test_the_freeze_lists_the_registry_the_relations_and_never_dev16():
    text = CF.MANIFEST.read_text()
    for name in ("src/registry.py", "src/questions.py", "src/transitions.py", "src/admission.py", "src/contract.py", "selective/evaluator.py", "selective/deterministic_criteria.py", "selective/relation_definitions_frozen.json"):
        assert name in text
    assert "dev16" not in "".join(line for line in text.splitlines() if not line.startswith("#")) and "bank_d" not in text.lower()


def test_the_three_formerly_held_out_relations_are_in_the_frozen_definitions_with_their_cues():
    data = json.loads(CF.RELATIONS_JSON.read_text())
    by = {r["name"]: r for r in data["relations"]}
    assert data["defined_in_final_development_pass"] == ["release_day", "escalation_contact", "approver"]
    for name in data["defined_in_final_development_pass"]:
        assert by[name]["cues"] and by[name]["qcues"] and by[name]["label"]
    assert by["escalation_contact"]["speaker_ok"] is False and by["approver"]["speaker_ok"] is False
