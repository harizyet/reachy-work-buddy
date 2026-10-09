"""Selective-answering Stage A: the v4 corpus and question sets, the deterministic sub-claim scorer (hand-labelled and adversarial cases, metamorphic checks) and the operational acceptance evaluator."""

import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"
AQ = SEL.parent
for p in (str(SEL), str(AQ)):
    if p not in sys.path:
        sys.path.insert(0, p)


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SEL / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


scorer = load("sel_scorer", "scorer.py")
cases_mod = load("sel_scorer_cases", "scorer_cases.py")
evaluator = load("sel_evaluator", "evaluator.py")
banks = load("sel_banks", "banks.py")
PEOPLE = ["Amara Osei", "Bruno Keller", "Chiara Rossi", "Dmitri Volkov", "Elena Marsh", "Farid Haddad", "Greta Lindqvist", "Hiro Tanaka", "Ines Duarte", "Jonas Weiss", "Kavya Menon", "Liam Oconnor", "Mila Novak", "Nikhil Rao",
          "Olga Petrova", "Pablo Reyes", "Quinn Abbott", "Rania Said", "Sven Larsen", "Tara Brennan", "Umar Bello", "Vera Kovac", "Wen Zhao", "Yusuf Demir"]


# -- corpus and sets ----------------------------------------------------------------------------------------------------------------

def test_the_v4_corpus_is_deterministic_and_has_no_duplicate_gold():
    gen = load("sel_corpus_gen", "corpus_gen.py")
    corpus, registry = gen.build()
    assert json.loads((SEL / "corpus_v4.json").read_text()) == corpus
    assert json.loads((SEL / "facts_v4.json").read_text()) == registry
    assert gen.check_unique(registry) == []


def test_every_atom_status_follows_the_registry_and_conflicts_are_date_unconfounded():
    registry = json.loads((SEL / "facts_v4.json").read_text())
    atoms = json.loads((SEL / "atoms_v4.json").read_text())
    states = {"SUPPORTED": "established", "NEGATIVE_SUPPORTED": "negative_supported", "HISTORICAL": "superseded"}
    by_rel = {(f["subject"], f["relation"]): f for f in registry["facts"]}
    for a in atoms:
        if a["status"] == "CONFLICTED":
            f = by_rel[(a["subject"], a["relation"])]
            assert f["state"] == "conflicted" and f.get("sameday") is True  # same-day memories: the label dates shown to a model cannot order them
        if a["status"] in states and a["relation"] in {x[1] for x in by_rel}:
            f = by_rel.get((a["subject"], a["relation"]))
            if f is not None:
                assert f["state"] == states[a["status"]]
        if a["status"] in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED"):
            assert a["sources"] == []
    assert {a["status"] for a in atoms} >= {"SUPPORTED", "UNSUPPORTED", "CONFLICTED", "HISTORICAL", "NEGATIVE_SUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED"}


def test_design_and_acceptance_candidate_sets_are_disjoint_and_the_acceptance_set_is_not_frozen_yet():
    d15 = json.loads((AQ / "cases_dev15.json").read_text())["cases"]
    d16 = json.loads((AQ / "cases_dev16.json").read_text())["cases"]
    assert not ({c["question"] for c in d15} & {c["question"] for c in d16})
    assert not any(c["held_out"] for c in d15) and all(c["held_out"] for c in d16)
    assert not (AQ / "dev16_freeze.json").exists()  # frozen only after the owner approves the criteria and coverage amendments
    assert all(c["bank"] == "C" for c in d15) and all(c["bank"] == "D" for c in d16)


def test_bank_d_unchanged_relations_are_byte_identical_to_the_pre_scorer_commit():
    out = subprocess.run(["git", "show", "bd050ec:services/companion-core/benchmarks/answer_quality/selective/banks.py"], capture_output=True, text=True, check=False, cwd=SEL)
    if out.returncode != 0:
        pytest.skip("git history not available")
    ns: dict = {}
    exec(compile(out.stdout, "old_banks", "exec"), ns)  # noqa: S102 - evaluates the committed bank file from git to prove it is unchanged
    changed = {"order_figure", "standup", "review_day"}
    recorded = (SEL / "bank_d_unchanged.sha256").read_text().split()[0]
    mine = hashlib.sha256(json.dumps({k: banks.BANKS[k][2:] for k in sorted(ns["BANKS"]) if k not in changed}, sort_keys=True).encode()).hexdigest()
    theirs = hashlib.sha256(json.dumps({k: ns["BANKS"][k][2:] for k in sorted(ns["BANKS"]) if k not in changed}, sort_keys=True).encode()).hexdigest()
    assert mine == theirs == recorded


# -- scorer: hand-labelled and adversarial ----------------------------------------------------------------------------------------

def run_cases():
    out = []
    for c in cases_mod.CASES:
        res = scorer.score_question(c["reply"], c["atoms"], cases_mod.MAN, PEOPLE)
        diffs = []
        for i, exp in enumerate(c["expect"]):
            for k, v in exp.items():
                got = getattr(res.atoms[i], k)
                if got != v and not (v is False and got is None):
                    diffs.append((i, k, v, got))
        if c.get("bad") and res.bad_citations != c["bad"]:
            diffs.append(("bad", c["bad"], res.bad_citations))
        if c.get("unauth") and res.unauthorized_citations != c["unauth"]:
            diffs.append(("unauth", c["unauth"], res.unauthorized_citations))
        out.append((c, diffs))
    return out


def test_every_hand_labelled_case_agrees_except_the_documented_limits():
    for c, diffs in run_cases():
        if c.get("limit"):
            continue
        assert diffs == [], (c["name"], diffs)


def test_documented_limits_stay_few_and_are_real():
    limits = [(c, d) for c, d in run_cases() if c.get("limit")]
    assert len(limits) <= 3 and all(d for _, d in limits)  # a limit that silently passed would mean the case list is stale


def test_replies_are_scored_independently_of_case_whitespace_and_independent_sentence_order():
    multi = next(c for c in cases_mod.CASES if c["name"] == "mixed: two supported, one conflict, all stated")
    base = scorer.score_question(multi["reply"], multi["atoms"], cases_mod.MAN, PEOPLE)
    sentences = re.split(r"(?<=\.)\s+", multi["reply"])
    rnd = random.Random(3)
    for _ in range(6):
        rnd.shuffle(sentences)
        again = scorer.score_question("  ".join(sentences).upper().lower().replace("  ", "   "), multi["atoms"], cases_mod.MAN, PEOPLE)
        assert [(a.stated, a.both, a.leaked) for a in again.atoms] == [(a.stated, a.both, a.leaked) for a in base.atoms]


def test_a_refusal_never_counts_as_stating_and_a_statement_never_counts_as_a_refusal():
    own = cases_mod.OWN
    refusal = scorer.score_question(f"I don't have a record of who owns the {own['subject']}.", [own], cases_mod.MAN, PEOPLE).atoms[0]
    stated = scorer.score_question(f"{own['display'][0]} owns the {own['subject']}.", [own], cases_mod.MAN, PEOPLE).atoms[0]
    assert not refusal.stated and refusal.false_abstention and stated.stated and not stated.identified


def test_an_unsupported_value_is_never_credited_to_the_wrong_subject():
    unsup = cases_mod.APPR
    other = scorer.score_question("Amara Osei approved the Hopper release.", [unsup], cases_mod.MAN, PEOPLE).atoms[0]
    assert not other.leaked or unsup["project"] == "Hopper"


# -- evaluator on synthetic arms -----------------------------------------------------------------------------------------------------

def fake_rows(n_mixed=10, leak=0, fa=0):
    rows = []
    for i in range(n_mixed):
        atoms = [{"atom_id": "s", "status": "SUPPORTED", "stated": True, "identified": False, "leaked": False, "severe": False, "both": False, "one_sided": False, "resolved": False, "as_current": False, "false_abstention": False, "absence_claim": False,
                      "invented_order": False, "cited_ids": ["E1"], "faithful": True, "ok": True},
                 {"atom_id": "u", "status": "UNSUPPORTED", "stated": False, "identified": not (i < leak), "leaked": i < leak, "severe": i < leak, "both": False, "one_sided": False, "resolved": False, "as_current": False, "false_abstention": False,
                      "absence_claim": False, "invented_order": False, "cited_ids": [], "faithful": None, "ok": not (i < leak)}]
        if i < fa:
            atoms[0].update(stated=False, false_abstention=True, identified=True, ok=False, faithful=None)
        rows.append({"family": "mixed", "outcome": {"atoms": atoms, "blanket": False, "bad_citations": [], "unauthorized_citations": [], "fully_correct": all(a["ok"] for a in atoms)}})
    return rows


def test_the_evaluator_passes_a_perfect_arm_and_fails_each_criterion_for_the_right_reason(monkeypatch):
    monkeypatch.setattr(evaluator, "PREREG_MIXED_LOWER_BOUND", 0.5)  # test value only: the real bound is the owner's to set
    base = fake_rows(40, leak=20)
    good = fake_rows(40, leak=10)
    res = {c.number: c for c in evaluator.evaluate(good, base)}
    assert res[1].passed and res[2].passed and res[3].passed and res[4].passed and res[5].passed and res[6].passed and res[10].passed
    worse = {c.number: c for c in evaluator.evaluate(fake_rows(40, leak=18), base)}
    assert not worse[1].passed  # only a 10% reduction
    lossy = {c.number: c for c in evaluator.evaluate(fake_rows(40, leak=0, fa=5), fake_rows(40, leak=0))}
    assert not lossy[2].passed and not lossy[10].passed
    assert evaluator.upper_bound_zero(10) > 0.25 and evaluator.upper_bound_zero(60) < 0.07  # what a clean result on few cases can and cannot show


# -- owner decisions 2026-10-12 (criteria forms, fully-correct definition, date semantics) -------------------------------------------------

def _row(atoms, blanket=False, family="mixed"):
    return {"family": family, "outcome": {"atoms": atoms, "blanket": blanket, "bad_citations": [], "unauthorized_citations": [], "fully_correct": True}}


def _atom(status, **kw):
    base = {"status": status, "stated": False, "ok": True, "faithful": None, "wrong_value": False, "leaked": False, "severe": False, "false_abstention": False, "resolved": False,
            "absence_claim": False, "invented_order": False}
    return {**base, **kw}


def test_zero_event_upper_bounds_are_one_sided_and_flag_thin_coverage():
    assert evaluator.upper_one_sided(0, 19) == pytest.approx(1 - 0.05 ** (1 / 19))
    assert evaluator.upper_one_sided(0, 100) < 0.03 < evaluator.upper_one_sided(0, 6)
    assert "INSUFFICIENT COVERAGE" in evaluator.bound_note(0, 6)
    assert "INSUFFICIENT" not in evaluator.bound_note(0, 40)


def test_fully_correct_v2_rejects_whole_answer_abstention_and_wrong_values():
    ok = _row([_atom("SUPPORTED", stated=True), _atom("UNSUPPORTED")])
    assert evaluator.fully_correct_v2(ok)
    abstained = _row([_atom("SUPPORTED", ok=False, false_abstention=True), _atom("UNSUPPORTED")], blanket=True)
    assert not evaluator.fully_correct_v2(abstained)
    assert not evaluator.fully_correct_v2(_row([_atom("SUPPORTED", stated=True, wrong_value=True)]))
    assert not evaluator.fully_correct_v2(_row([_atom("SUPPORTED", stated=True, faithful=False)]))


def test_criterion_4_is_not_evaluable_without_a_preregistered_bound_and_6_needs_forty_claims():
    rows = [_row([_atom("SUPPORTED", stated=True, faithful=True)]) for _ in range(30)]
    by = {c.number: c for c in evaluator.evaluate(rows, rows)}
    assert not by[4].passed and "NOT EVALUABLE" in by[4].note
    assert not by[6].passed and "NOT EVALUABLE" in by[6].note  # 30 cited claims < 40


def test_ordering_and_conflict_gold_never_rests_on_retrieval_or_creation_time():
    """Owner date rule: retrieval time and record creation time never establish recency or supersession. Conflict and ordering atoms are built only from same-day memory pairs."""
    for name in ("cases_dev15.json", "cases_dev16.json"):
        for case in json.loads((AQ / name).read_text())["cases"]:
            for a in case["atoms"]:
                assert a["status"] != "SUPERSEDED"
                if a["status"] in ("CONFLICTED", "ORDER_UNSUPPORTED"):
                    assert all(s.startswith("memory:") for s in a["sources"]), (case["id"], a["sources"])
