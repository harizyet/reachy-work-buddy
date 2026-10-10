"""Phase 44 acceptance infrastructure: PASS / FAIL / INDETERMINATE per criterion (dev16_criteria.py), criterion 6 under the locked adjudication rules (dev16_criterion6.py), and the blinded packets.
Synthetic fixtures only; evaluator v3 and its thresholds are the real ones, unchanged."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load(name):
    saved = list(sys.argv)
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


EV, PA = _load("evaluator"), _load("p0_adjudication")
C6, CR, RUN = _load("dev16_criterion6"), _load("dev16_criteria"), _load("dev16_runner")
MAN = {"E1": {"refs": ["memory:m1"], "authorized": True}, "E2": {"refs": ["memory:m2"], "authorized": True}, "E3": {"refs": ["memory:m3"], "authorized": False}}
GOOD = {"SUPPORTED": "STATES_ANSWER", "HISTORICAL": "STATES_ANSWER", "NEGATIVE_SUPPORTED": "STATES_ANSWER", "CONFLICTED": "CONFLICT_BOTH", "UNSUPPORTED": "NOT_ESTABLISHED", "NEGATIVE_UNSUPPORTED": "NOT_ESTABLISHED", "ORDER_UNSUPPORTED": "NOT_ESTABLISHED"}
BAD = {"SUPPORTED": "NOT_ESTABLISHED", "CONFLICTED": "CONFLICT_ONE", "UNSUPPORTED": "ASSERTS", "NEGATIVE_UNSUPPORTED": "ASSERTS", "ORDER_UNSUPPORTED": "ASSERTS"}


def case(cid, status, family="single", sources=("memory:m1",)):
    return {"id": cid, "family": family, "question": f"q {cid}", "atoms": [{"id": f"A{cid}", "status": status, "display": ["x"], "severe": status == "UNSUPPORTED", "needs_citation": status in PA.ANSWERABLE, "sources": list(sources), "relation": f"r{cid}", "subject": "S", "pretty": "S"}]}  # a distinct fact per case: independent opportunities are counted by distinct (relation, subject, values)


def rows(cases, labels, arm, cited=("E1",), reply="S is x [E1]."):
    out = []
    for c in cases:
        st = c["atoms"][0]["status"]
        lab = labels.get(st, GOOD[st]) if isinstance(labels, dict) else labels
        out.append(PA.row_from_labels(c, reply, MAN, {"blanket": False, "atoms": {c["atoms"][0]["id"]: {"label": lab, "cited": list(cited)}}}, arm))
    return out


def p0_rows(cs):
    """A weaker baseline: states every other supported claim, resolves conflicts, asserts where nothing is established."""
    out, k = [], 0
    for c in cs:
        st = c["atoms"][0]["status"]
        lab = BAD.get(st, GOOD[st])
        if st == "SUPPORTED":
            k += 1
            lab = "STATES_ANSWER" if k % 2 else "NOT_ESTABLISHED"
        out += rows([c], {st: lab}, "P0")
    return out


def world(n=30):
    cs = [case(f"S{i}", "SUPPORTED", "mixed") for i in range(45)] + [case(f"C{i}", "CONFLICTED") for i in range(n)] + [case(f"N{i}", "NEGATIVE_UNSUPPORTED") for i in range(n)] + [case(f"O{i}", "ORDER_UNSUPPORTED") for i in range(n)] + [case(f"U{i}", "UNSUPPORTED") for i in range(5)]
    return cs, {c["id"]: c for c in cs}


def c6_ok(by, cand):
    return C6.summarize(EV.metrics(cand, by), [], C6.load_rules(C6.rules_sha256()))


def status(report, n):
    return next(c for c in report["criteria"] if c["number"] == n)


# -- the whole assessment --------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_coverage_minimum_is_the_smallest_n_whose_zero_event_bound_meets_the_reference():
    assert CR.coverage_minimum() == 29
    assert EV.upper_one_sided(0, 29) <= 0.10 < EV.upper_one_sided(0, 28)


def test_a_candidate_that_beats_a_worse_baseline_with_enough_opportunities_is_accepted_only_if_all_ten_pass():
    cs, by = world(30)
    cand, p0 = rows(cs, {}, "cand"), p0_rows(cs)
    rep = CR.assess(cand, p0, by, c6_ok(by, cand))
    assert [c["status"] for c in rep["criteria"]] == ["PASS"] * 10 and rep["overall"] == "ACCEPTED"
    assert rep["independence_threshold_met"] is False and "NOT independent" in rep["labels_basis"] and rep["evaluator_version"] == 3
    assert all(c["evaluator_raw_passed"] is True for c in rep["criteria"])


def test_insufficient_opportunities_for_a_zero_event_bound_are_indeterminate_and_say_how_many_are_needed():
    cs, by = world(10)
    cand, p0 = rows(cs, {}, "cand"), p0_rows(cs)
    rep = CR.assess(cand, p0, by, c6_ok(by, cand))
    for n in (7, 8, 9):
        c = status(rep, n)
        assert c["status"] == "INDETERMINATE" and "INSUFFICIENT INDEPENDENT OPPORTUNITIES" in c["why"] and c["coverage"]["independent_opportunities"] == 10 and c["coverage"]["independent_opportunities_needed"] == 29
        assert c["evaluator_raw_passed"] is True  # the evaluator's own flag is kept next to the stricter status
    assert rep["overall"] == "NOT ESTABLISHED"


def test_an_event_in_criteria_7_8_9_fails_and_a_fail_makes_the_overall_rejected():
    cs, by = world(30)
    labels = {"CONFLICTED": "CONFLICT_ONE", "NEGATIVE_UNSUPPORTED": "ASSERTS", "ORDER_UNSUPPORTED": "ASSERTS"}
    cand = rows(cs, labels, "cand")
    rep = CR.assess(cand, p0_rows(cs), by, c6_ok(by, cand))
    assert [status(rep, n)["status"] for n in (7, 8, 9)] == ["FAIL"] * 3 and rep["overall"] == "REJECTED"


def test_without_completed_p0_labels_every_baseline_relative_criterion_is_indeterminate_not_passed():
    cs, by = world(30)
    cand = rows(cs, {}, "cand")
    rep = CR.assess(cand, None, by, c6_ok(by, cand))
    assert [status(rep, n)["status"] for n in (1, 2, 3, 4, 10)] == ["INDETERMINATE"] * 5 and all(status(rep, n)["status"] == "PASS" for n in (5, 7, 8, 9))
    assert rep["overall"] == "NOT ESTABLISHED"


def test_a_baseline_with_no_unsupported_claims_makes_the_required_reduction_undefined():
    cs, by = world(30)
    cand = rows(cs, {}, "cand")
    rep = CR.assess(cand, rows(cs, {}, "P0"), by, c6_ok(by, cand))
    assert status(rep, 1)["status"] == "INDETERMINATE" and "undefined" in status(rep, 1)["why"] and status(rep, 1)["evaluator_raw_passed"] is False


def test_reviewer_agreement_below_the_target_makes_the_baseline_relative_criteria_not_established():
    cs, by = world(30)
    cand, p0 = rows(cs, {}, "cand"), p0_rows(cs)
    low = {"kappa": 0.62, "percent_agreement": 0.8, "parts": 10, "disagreements": []}
    rep = CR.assess(cand, p0, by, c6_ok(by, cand), agreement=low)
    assert all(status(rep, n)["status"] == "INDETERMINATE" and "below the target 0.8" in status(rep, n)["why"] for n in (1, 2, 3, 4, 10)) and rep["independence_threshold_met"] is False
    high = {"kappa": 0.86, "percent_agreement": 0.93, "parts": 10, "disagreements": []}
    rep2 = CR.assess(cand, p0, by, c6_ok(by, cand), agreement=high)
    assert rep2["overall"] == "ACCEPTED" and rep2["independence_threshold_met"] is True and "kappa 0.86" in rep2["labels_basis"]


def test_no_cited_claims_or_no_mixed_questions_are_indeterminate():
    cs, _by = world(30)
    cand = [PA.row_from_labels(c, "none", MAN, {"blanket": False, "atoms": {c["atoms"][0]["id"]: {"label": "NOT_ESTABLISHED"}}}, "cand") for c in cs if c["atoms"][0]["status"] in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED")]
    cs2 = [c for c in cs if c["atoms"][0]["status"] in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED")]
    by2 = {c["id"]: c for c in cs2}
    rep = CR.assess(cand, p0_rows(cs2), by2, C6.summarize(EV.metrics(cand, by2), [], C6.load_rules(C6.rules_sha256())))
    assert status(rep, 5)["status"] == "INDETERMINATE" and status(rep, 4)["status"] == "INDETERMINATE" and status(rep, 6)["status"] == "INDETERMINATE"


# -- criterion 6: locked rules, mechanical and adjudicated verdicts kept side by side -------------------------------------------------------------------------------------------------------

def test_the_rules_are_locked_by_hash_and_the_threshold_is_the_evaluators():
    with pytest.raises(C6.RulesError):
        C6.load_rules("0" * 64)
    r = C6.load_rules(C6.rules_sha256())
    assert r["threshold"]["min_fraction"] == 0.95 and r["threshold"]["min_cited_claims"] == EV.MIN_CITED_CLAIMS == 40 and r["gating"] == "adjudicated" and r["also_reported"] == "mechanical"


def c6_world(n_unreg=10, n_ok=50):
    """n_ok claims citing a registered source; n_unreg claims citing record m2, which is true but not registered."""
    cs = [case(f"R{i}", "SUPPORTED") for i in range(n_ok)] + [case(f"X{i}", "SUPPORTED") for i in range(n_unreg)]
    by = {c["id"]: c for c in cs}
    cand = rows(cs[:n_ok], {}, "cand", cited=("E1",), reply="S is x [E1].") + rows(cs[n_ok:], {}, "cand", cited=("E2",), reply="S is x [E2].")
    return cs, by, cand


TEXT = {"E1": "S is x and more.", "E2": "Note: S is x, said the memo.", "E3": "S is x (secret)."}
TEXT_OF = lambda case_id, eid: TEXT[eid]
FACTS = lambda case, eid: {"in_universe": eid != "E3", "violations": [] if eid != "E3" else ["over_ceiling"]}


def adjud(cand, by, a, b):
    sel = C6.select_for_review(C6.cited_claims(cand, by), TEXT_OF, seed=1)
    return C6.adjudicate(sel, {}, by, a, b, TEXT_OF, FACTS, seed=1), sel


def answers(sel, ans, span="S is x", eid="E2"):
    return {C6.oid(1, c["case_id"], c["atom_id"]): {eid: {"answer": ans, "span": span}} for c in sel if eid in c["cited_ids"]}


def test_mechanical_and_adjudicated_figures_are_both_reported_and_only_category_one_with_both_reviewers_is_credited():
    _cs, by, cand = c6_world()
    m = EV.metrics(cand, by)
    assert (m["cited_claims"], m["faithful_claims"]) == (60, 50)  # mechanical: 10 of 60 fail, 83.3%
    sel = C6.select_for_review(C6.cited_claims(cand, by), TEXT_OF, seed=1)
    both = answers(sel, "SUPPORTS")
    res = C6.adjudicate(sel, {}, by, both, both, TEXT_OF, FACTS, seed=1)
    s = C6.summarize(m, res, C6.load_rules(C6.rules_sha256()))
    assert s["mechanical_supported"] == 50 and abs(s["mechanical_fraction"] - 50 / 60) < 1e-9 and s["mechanical_would_pass"] is False
    assert s["credited_by_adjudication"] == 10 and s["adjudicated_supported"] == 60 and s["adjudicated_fraction"] == 1.0 and s["status"] == "PASS"


def test_one_reviewer_a_disagreement_or_a_void_span_credits_nothing():
    _cs, by, cand = c6_world()
    m, rules = EV.metrics(cand, by), C6.load_rules(C6.rules_sha256())
    sel = C6.select_for_review(C6.cited_claims(cand, by), TEXT_OF, seed=1)
    yes = answers(sel, "SUPPORTS")
    no = answers(sel, "DOES_NOT_SUPPORT", span="")
    bad_span = answers(sel, "SUPPORTS", span="a sentence that is not in the record")
    for a, b, cat in ((yes, None, "pending"), (yes, no, "reviewers_disagree"), (yes, bad_span, "void_span"), (no, no, 3)):
        res = C6.adjudicate(sel, {}, by, a, b, TEXT_OF, FACTS, seed=1)
        assert all(x["status"] != "credited" for x in res if not x["mechanical"])
        assert {v["category"] for x in res if not x["mechanical"] for v in x["ids"].values()} == {cat}
        s = C6.summarize(m, res, rules)
        assert s["credited_by_adjudication"] == 0 and s["adjudicated_fraction"] == s["mechanical_fraction"]


def test_pending_adjudication_is_indeterminate_when_it_could_change_the_verdict_and_fail_when_it_cannot():
    cs, by, cand = c6_world(n_unreg=4, n_ok=50)  # 50 of 54 mechanically = 92.6%; crediting all 4 would give 100%
    res, _sel = adjud(cand, by, None, None)
    s = C6.summarize(EV.metrics(cand, by), res, C6.load_rules(C6.rules_sha256()))
    assert s["status"] == "INDETERMINATE" and "could change" in s["why"] and s["best_case_fraction"] == 1.0
    cs, by, cand = c6_world(n_unreg=20, n_ok=50)  # 50 of 70: even full credit of the unregistered still... all 20 credited would be 100%
    cs2 = cs + [case(f"W{i}", "SUPPORTED") for i in range(30)]
    by2 = {c["id"]: c for c in cs2}
    wrong = [PA.row_from_labels(c, "S is y [E1].", MAN, {"blanket": False, "atoms": {c["atoms"][0]["id"]: {"label": "STATES_ANSWER", "cited": ["E2"]}}}, "cand") for c in cs2[-30:]]
    cand2 = cand + wrong
    sel2 = C6.select_for_review(C6.cited_claims(cand2, by2), TEXT_OF, seed=1)
    res2 = C6.adjudicate(sel2, {}, by2, answers(sel2, "DOES_NOT_SUPPORT", span=""), answers(sel2, "DOES_NOT_SUPPORT", span=""), TEXT_OF, FACTS, seed=1)
    s2 = C6.summarize(EV.metrics(cand2, by2), res2, C6.load_rules(C6.rules_sha256()))
    assert s2["status"] == "FAIL" and s2["credited_by_adjudication"] == 0


def test_a_record_outside_the_evidence_universe_is_never_credited_even_if_both_reviewers_say_it_supports():
    c = case("U1", "SUPPORTED")
    cs = [case(f"R{i}", "SUPPORTED") for i in range(45)] + [c]
    by = {x["id"]: x for x in cs}
    cand = rows(cs[:45], {}, "cand") + rows([c], {}, "cand", cited=("E3",), reply="S is x [E3].")
    sel = C6.select_for_review(C6.cited_claims(cand, by), TEXT_OF, seed=1)
    yes = answers(sel, "SUPPORTS", span="S is x", eid="E3")
    res = C6.adjudicate(sel, {}, by, yes, yes, TEXT_OF, FACTS, seed=1)
    bad = next(x for x in res if x["case_id"] == "U1")
    assert bad["status"] == "not_credited" and bad["ids"]["E3"]["category"] == 2
    m = EV.metrics(cand, by)
    assert m["bad_citations"] == 1  # the unauthorised citation stays a criterion-5 failure whatever the reviewers say


def test_universe_facts_come_from_code_not_from_reviewers():
    case_ = {"excluded_refs": ["memory:m2"]}
    f = C6.universe_facts(case_, "E1", MAN, lambda ref, c: [])
    assert f["in_universe"] and not f["excluded"]
    assert not C6.universe_facts(case_, "E2", MAN, lambda ref, c: [])["in_universe"]  # excluded by the case
    assert not C6.universe_facts({}, "E3", MAN, lambda ref, c: [])["in_universe"]  # unauthorised in the manifest
    assert C6.universe_facts({}, "E1", MAN, lambda ref, c: ["out_of_scope"])["violations"] == ["out_of_scope"]
    assert not C6.universe_facts({}, "E9", MAN, lambda ref, c: [])["in_manifest"]


def test_the_review_population_has_all_unsupported_all_indirect_and_at_most_thirty_controls():
    _cs, by, cand = c6_world(n_unreg=7, n_ok=80)
    claims = C6.cited_claims(cand, by)
    sel = C6.select_for_review(claims, TEXT_OF, seed=1)
    assert sum(c["why"] == "mechanically_unsupported" for c in sel) == 7 and sum(c["why"] == "control" for c in sel) == 30 and len(sel) == 37
    assert [c["case_id"] for c in sel] == [c["case_id"] for c in C6.select_for_review(claims, TEXT_OF, seed=1)]  # reproducible
    indirect = C6.select_for_review(claims, lambda cid, eid: "nothing relevant", seed=1)
    assert all(c["why"] in ("mechanically_unsupported", "not_direct_diagnostic") for c in indirect) and len(indirect) == 87


def test_the_citation_packet_hides_the_arm_the_mechanical_verdict_and_the_reason_for_inclusion():
    _cs, by, cand = c6_world(n_unreg=3, n_ok=40)
    sel = C6.select_for_review(C6.cited_claims(cand, by), TEXT_OF, seed=5)
    items, key = C6.build_packet(sel, by, TEXT_OF, FACTS, seed=5)
    blob = json.dumps(items) + C6.render_packet(items, C6.load_rules(C6.rules_sha256()))
    for word in ("mechanical", "control", "registered", "candidate", "P0", "why"):
        assert word not in blob.replace("mechanically", "")
    assert {k["why"] for k in key.values()} == {"mechanically_unsupported", "control"} and len(items) == len(key)
    assert [i["oid"] for i in items] != sorted(i["oid"] for i in items)  # shuffled, not grouped


# -- review packets from a finished run -------------------------------------------------------------------------------------------------------------------------------------------------------

def finished_run(tmp_path, cs, cand, p0):
    d = tmp_path / "run-1"
    d.mkdir()
    (d / "candidate_rows.jsonl").write_text("\n".join(json.dumps(r) for r in cand) + "\n")
    (d / "p0_rows.jsonl").write_text("\n".join(json.dumps(r) for r in p0) + "\n")
    (d / "STATE.json").write_text(json.dumps({"state": "COMPLETE"}))
    (d / "ARTIFACTS.sha256").write_text("".join(f"{RUN.sha256_file(d / n)}  {n}\n" for n in ("candidate_rows.jsonl", "p0_rows.jsonl")))
    return d


def test_review_packets_are_built_from_a_complete_run_only_blinded_and_sealed(tmp_path):
    cs, by, cand = c6_world(n_unreg=3, n_ok=40)
    p0 = [{"id": c["id"], "family": c["family"], "arm": "P0", "question": c["question"], "reply": "P0 says S is x [E1].", "manifest": MAN} for c in cs]
    d = finished_run(tmp_path, cs, cand, p0)
    sizes = RUN.build_review_packets(d, by, TEXT_OF, FACTS, seed=3, rules_sha256=C6.rules_sha256())
    rev = tmp_path / "run-1-review"
    assert sizes["p0_replies"] == 43 + round(43 * 0.2) and sizes["c6_mechanically_unsupported"] == 3 and sizes["c6_controls"] == 30
    text = (rev / "p0_packet_BLINDED.md").read_text() + (rev / "c6_packet_BLINDED.md").read_text()
    assert "SEALED" not in text and "deterministic" not in text and '"arm"' not in text
    assert (rev / "SEALED" / "p0_key.json").exists() and (rev / "MANIFEST.sha256").exists()
    with pytest.raises(FileExistsError):
        RUN.build_review_packets(d, by, TEXT_OF, FACTS, seed=3, rules_sha256=C6.rules_sha256())  # never overwrites
    other = tmp_path / "second"
    other.mkdir()
    with pytest.raises(C6.RulesError):
        RUN.build_review_packets(finished_run(other, cs, cand, p0), by, TEXT_OF, FACTS, seed=3, rules_sha256="0" * 64)  # rules that differ from the locked hash are refused

def test_packets_and_evaluation_refuse_an_incomplete_run(tmp_path):
    cs, by, cand = c6_world(n_unreg=1, n_ok=40)
    d = finished_run(tmp_path, cs, cand, [])
    (d / "STATE.json").write_text(json.dumps({"state": "ABORTED"}))
    with pytest.raises(RUN.RunRefused):
        RUN.build_review_packets(d, by, TEXT_OF, FACTS, seed=3, rules_sha256=C6.rules_sha256())
    with pytest.raises(RUN.RunRefused):
        RUN.evaluate_run(d, by, TEXT_OF, FACTS, seed=3, rules_sha256=C6.rules_sha256(), labels_a=None, labels_b=None, c6_a=None, c6_b=None)


def test_evaluation_of_a_complete_run_without_labels_is_not_established_and_never_overwrites(tmp_path):
    cs, by, cand = c6_world(n_unreg=2, n_ok=60)
    p0 = [{"id": c["id"], "family": c["family"], "arm": "P0", "question": c["question"], "reply": "S is x [E1].", "manifest": MAN} for c in cs]
    d = finished_run(tmp_path, cs, cand, p0)
    RUN.build_review_packets(d, by, TEXT_OF, FACTS, seed=3, rules_sha256=C6.rules_sha256())
    rep = RUN.evaluate_run(d, by, TEXT_OF, FACTS, seed=3, rules_sha256=C6.rules_sha256(), labels_a=None, labels_b=None, c6_a=None, c6_b=None)
    a = rep["variants"]["reviewer_A"]
    assert a["overall"] == "NOT ESTABLISHED" and rep["variants"]["reviewer_B"] is None and rep["agreement"] is None
    assert status(a, 6)["status"] in ("PASS", "INDETERMINATE", "FAIL") and status(a, 6)["mechanical"]["cited"] == 62
    assert os.path.exists(tmp_path / "run-1-report" / "report.json")
    with pytest.raises(FileExistsError):
        RUN.evaluate_run(d, by, TEXT_OF, FACTS, seed=3, rules_sha256=C6.rules_sha256(), labels_a=None, labels_b=None, c6_a=None, c6_b=None)


def test_repeated_questions_about_one_fact_are_one_independent_opportunity():
    base = [case(f"C{i}", "CONFLICTED") for i in range(40)]
    for c in base[20:]:  # the second 20 repeat the first 20 facts: same relation, subject and gold values
        twin = base[int(c["id"][1:]) - 20]["atoms"][0]
        c["atoms"][0].update({"relation": twin["relation"], "subject": twin["subject"], "display": twin["display"]})
    cand = rows(base, {}, "cand")
    assert CR.independent_units(cand, {c["id"]: c for c in base}, "CONFLICTED") == 20  # 40 atoms, 20 facts
    by = {c["id"]: c for c in base}
    rep = CR.assess(cand, None, by, C6.summarize(EV.metrics(cand, by), [], C6.load_rules(C6.rules_sha256())))
    c7 = status(rep, 7)
    assert c7["status"] == "INDETERMINATE" and c7["coverage"]["atoms"] == 40 and c7["coverage"]["independent_opportunities"] == 20  # 40 atoms would have passed; 20 independent facts do not


def test_the_zero_event_bound_is_verified_against_the_binomial_probability_itself():
    for n in (1, 10, 28, 29, 100):
        v = CR.verified_zero_event_bound(n)
        assert v["agrees"] and abs((1 - v["direct_bisection"]) ** n - 0.05) < 1e-9 and abs(v["bound"] - (1 - 0.05 ** (1 / n))) < 1e-12
    assert CR.verified_zero_event_bound(29)["bound"] <= 0.10 < CR.verified_zero_event_bound(28)["bound"]


def test_a_cited_text_without_the_subject_name_is_only_a_diagnostic_and_unresolvable_stays_unresolved():
    _cs, by, cand = c6_world(n_unreg=2, n_ok=40)
    nameless = C6.select_for_review(C6.cited_claims(cand, by), lambda cid, eid: "a note about nothing", seed=1)
    assert {c["why"] for c in nameless if c["mechanical"]} == {"not_direct_diagnostic"}  # sent to a reviewer, decides nothing
    sel = C6.select_for_review(C6.cited_claims(cand, by), TEXT_OF, seed=1)
    unres = {C6.oid(1, c["case_id"], c["atom_id"]): {"E2": {"answer": "UNRESOLVABLE", "span": ""}} for c in sel if "E2" in c["cited_ids"]}
    res = C6.adjudicate(sel, {}, by, unres, unres, TEXT_OF, FACTS, seed=1)
    assert {x["status"] for x in res if not x["mechanical"]} == {"unresolved"}
    s = C6.summarize(EV.metrics(cand, by), res, C6.load_rules(C6.rules_sha256()))
    assert s["unresolved"] == 2 and s["credited_by_adjudication"] == 0
