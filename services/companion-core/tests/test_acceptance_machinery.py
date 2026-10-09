"""Machinery of the scorer-v3 formal validation: one-shot guards, deterministic plan, blinded keys, label-only stopping rule, verdict logic. No model, no scorer evaluation of the acceptance data."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"
for p in (str(SEL), str(SEL.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SEL / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cfg = load("acc_cfg", "acceptance_config.py")
state = load("acc_state", "acceptance_state.py")
plan_mod = load("acc_plan", "acceptance_plan.py")
packet = load("acc_packet", "acceptance_packet.py")


def test_the_state_machine_moves_forward_only(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE", tmp_path / "STATE.json")
    with pytest.raises(SystemExit):
        state.advance("generated")  # cannot skip 'frozen'
    state.advance("frozen")
    with pytest.raises(SystemExit):
        state.advance("frozen")  # cannot repeat
    with pytest.raises(SystemExit):
        state.require("generated")
    state.advance("generated")
    state.advance("labels_frozen")
    state.advance("scored")
    with pytest.raises(SystemExit):
        state.advance("scored")  # a finished run cannot be repeated


def test_the_plan_is_deterministic_independent_of_any_reply_and_covers_distinct_facts():
    p1 = json.loads((SEL / "acceptance" / "plan.json").read_text())
    p2 = plan_mod.build(cfg.WORLDS)
    assert json.dumps(p1, indent=1) == json.dumps(p2, indent=1)
    for name, seq in p1["sequences"].items():
        facts = [it["fact"] for it in seq]
        assert len(facts) == len(set(facts)), name  # one reply per underlying fact in a sequence
        assert {it["arm"] for it in seq} <= set(cfg.ARMS)
    assert p1["counts"]["natural|control"] == p1["counts"]["provoked|control"] == cfg.CONTROLS_PER_POPULATION
    assert set(p1["counts"]) == {f"{pop}|{cat}" for pop in cfg.POPULATIONS for cat in [*cfg.CATEGORIES, "control"]}


def test_blinded_keys_hide_population_and_category():
    keys = {packet.opaque(f"{pop}-{cat}-{n}") for pop in "NP" for cat in ("CON", "INV", "ABS", "LEA") for n in range(50)}
    assert len(keys) == 400 and all(k.startswith("Q") and len(k) == 8 for k in keys)


def test_the_stopping_rule_uses_labels_only(monkeypatch):
    seq = [{"key": f"N-CON-{i:04d}", "status": "CONFLICTED"} for i in range(100)]
    plan = {"sequences": {"natural|conflict_resolution": seq}}
    labels = {packet.opaque(it["key"]): {"flags": ["resolved"], "unclear": False} for it in seq[:cfg.TARGET_EVENTS - 1]}
    assert not packet.sequence_status(plan, labels)["natural|conflict_resolution"]["done"]
    labels[packet.opaque(seq[cfg.TARGET_EVENTS - 1]["key"])] = {"flags": ["resolved"], "unclear": False}
    s = packet.sequence_status(plan, labels)["natural|conflict_resolution"]
    assert s["done"] and s["confirmed_events"] == cfg.TARGET_EVENTS
    exhausted = {"sequences": {"natural|conflict_resolution": seq[:10]}}
    assert packet.sequence_status(exhausted, {packet.opaque(it["key"]): {"flags": [], "unclear": False} for it in seq[:10]})["natural|conflict_resolution"]["done"]


def test_the_target_and_gate_arithmetic_match_the_protocol():
    va = load("acc_va", "validation_analyze.py")
    assert va.lower_bound(46, 46, 0.05) >= 0.9 and va.lower_bound(45, 46, 0.05) >= 0.9  # one miss allowed at 46
    assert va.lower_bound(44, 46, 0.05) < 0.9
    assert va.lower_bound(28, 29, 0.05) < 0.9 <= va.lower_bound(29, 29, 0.05)  # 29 events with no miss is the minimum for a 90% bound
    assert cfg.MIN_EVENTS == 29 and cfg.TARGET_EVENTS == 46 and cfg.GATE == {"sensitivity_lower": 0.90, "precision_lower": 0.80}
