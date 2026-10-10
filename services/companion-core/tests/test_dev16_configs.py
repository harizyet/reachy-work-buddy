"""Phase 44 acceptance infrastructure: the declared P0 and candidate configurations, per-case authorisation of the candidate arm, and a full rehearsal of the runner on already-consumed dev15 data. No model call
is made (the P0 arm replays stored replies); dev16 is not touched. The check that the real P0 declaration still matches the production code is a runtime guard of the acceptance runner, not a unit test, so an
unrelated edit to a production module cannot break this suite."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load(name):
    saved = list(sys.argv)
    sys.path[:0] = [str(SEL), str(SEL.parent), str(SEL.parents[1] / "knowledge_retrieval")]
    try:
        spec = importlib.util.spec_from_file_location(name, SEL / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv[:] = saved
        del sys.path[:3]


P0, CA, REH = _load("dev16_p0"), _load("dev16_candidate_arm"), _load("dev16_rehearsal")


# -- the P0 declaration ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_declared_p0_pins_model_prompt_decoding_context_order_and_schema():
    d = P0.DECLARED
    assert d["decoding"] == {"temperature": 0, "seed": 44, "max_tokens": 350, "n": 1, "other": "server defaults; none overridden"}
    assert d["model"]["served_name"] == "reachy-local" and d["model"]["nothink"] is False
    assert d["harness"]["budget_tokens"] == 1500 and d["retrieval"]["limit"] == 10 and d["evidence_context"]["header_version"] == "v1"
    assert d["input_order"]["messages"][-1].startswith("user") and "no shuffling" in d["input_order"]["cases"] and "one P0 run" in d["runs"]
    assert "free text" in d["output_schema"]["reply"] and d["output_schema"]["labels"].startswith("none")


def test_the_effective_p0_facts_come_from_the_code_and_match_the_pilot_arm_without_any_call():
    eff = P0.effective()["computed"]
    assert eff["client"]["seed"] == 44 and eff["client"]["nothink"] is False and eff["client"]["model"] == "reachy-local"
    assert eff["message_roles"] == ["system", "system", "system", "user"] and len(eff["system_message_sha256"]) == 3
    assert eff["retrieval_config_b1a"]["vector"] is False and eff["retrieval_config_b1a"]["rerank"] is False
    assert eff["clock_now"] == "2026-10-08T12:00:00+00:00" and "aq/conditions.py" in eff["source_sha256"]


def test_drift_between_the_declared_and_the_effective_p0_is_reported(tmp_path, monkeypatch):
    cfg = json.loads(json.dumps(P0.effective()))
    cfg["decoding"]["temperature"] = 0.7
    cfg["computed"]["system_message_sha256"][1] = "0" * 64
    cfg["computed"]["source_sha256"]["aq/conditions.py"] = "1" * 64
    path = tmp_path / "p0.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(P0, "CONFIG_PATH", path)
    problems = P0.verify_declared()
    assert any("decoding" in x for x in problems) and any("computed fact differs: system_message_sha256" in x for x in problems) and any("source_sha256" in x for x in problems)
    cfg2 = json.loads(json.dumps(P0.effective()))
    cfg2["computed"]["client"]["nothink"] = True
    path.write_text(json.dumps(cfg2))
    assert any("nothink" in x for x in P0.verify_declared())


def test_the_real_executor_makes_no_call_until_opened_and_replay_makes_none_ever():
    ex = P0.RealP0Executor(SEL / "corpus_v4.json")
    assert ex.llm is None and ex.env is None and ex.effective_config()["arm"] == "P0"
    rp = P0.ReplayP0Executor([{"id": "Q1", "reply": "r", "manifest": {"E1": {"refs": ["memory:m1"], "authorized": True}}}])
    assert rp.run_case({"id": "Q1", "family": "f", "question": "q"})["reply"] == "r" and rp.calls == 1


def test_the_candidate_declaration_matches_the_frozen_code_and_names_the_per_case_authorisation():
    assert CA.verify_declared() == []
    d = json.loads(CA.CONFIG_PATH.read_text())
    assert d["planner"].endswith("['T-new']  (question text only; entity registry = grammar + entries harvested from the record pool)") and "access profile" in d["authorisation_model"]
    assert d["admission_policy"]["expected_policy_version"] == "p1" and d["evaluation_clock_now"].startswith("2026-10-13")


# -- per-case authorisation, on consumed data -------------------------------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dev15():
    cases = json.loads((SEL.parent / "cases_dev15.json").read_text())["cases"]
    world, meta, profiles = CA.load_world(SEL / "corpus_v4.json")
    import i2b_eval as e

    return cases, world, meta, profiles, e.make_planners(world, cases)["T-new"]


def test_owner_private_per_case_authorisation_reproduces_the_frozen_default_on_all_dev15_rows(dev15):
    cases, world, meta, profiles, planner = dev15
    import deterministic_criteria as dc

    new = CA.candidate_rows(world, cases, planner, meta, profiles)
    old = dc.candidate_rows(world, cases, planner)
    assert len(new) == 173 and all(json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str) for a, b in zip(new, old, strict=True))


@pytest.mark.parametrize("profile", ["shared_speaker", "harbor_only"])
def test_a_restricted_access_profile_never_lets_the_candidate_cite_a_record_outside_it(dev15, profile):
    cases, world, meta, profiles, planner = dev15
    restricted = [{**c, "access": profile} for c in cases[:60]]
    rows = CA.candidate_rows(world, restricted, planner, meta, profiles)
    viol = CA.record_violations(meta, profiles[profile])
    cited = 0
    for r in rows:
        assert not r["outcome"]["unauthorized_citations"]
        for eid, ent in r["manifest"].items():
            cited += 1
            assert all(viol(ref) == [] for ref in ent["refs"]), (r["id"], eid, ent)
    if profile == "shared_speaker":
        assert cited == 0 and all(not a["stated"] for r in rows for a in r["outcome"]["atoms"])  # the public ceiling authorises nothing in this corpus: everything is withheld, nothing leaks


# -- the whole runner, rehearsed ------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_full_rehearsal_on_dev15_runs_once_leaves_immutable_artifacts_and_reproduces_known_figures(tmp_path):
    summary = REH.rehearse(tmp_path / "reh")
    assert summary["state"] == "COMPLETE" and summary["overall_without_labels"] == "NOT ESTABLISHED"
    assert summary["criterion6"]["cited_claims"] == 191 and summary["criterion6"]["mechanical_supported"] == 183
    assert summary["packet_sizes"]["c6_mechanically_unsupported"] == 8 and summary["packet_sizes"]["p0_replies"] == 208
    assert all(summary["statuses_without_labels"][n] == "INDETERMINATE" for n in (1, 2, 3, 4, 10))  # no labels: nothing baseline-relative is passed
    run = tmp_path / "reh" / "runs" / "run-rehearsal-dev15"
    assert json.loads((run / "provenance.json").read_text())["mode"] == "rehearsal"
    with pytest.raises(FileExistsError):
        REH.rehearse(tmp_path / "reh")  # the manifest, authorisation and run already exist: nothing is overwritten
