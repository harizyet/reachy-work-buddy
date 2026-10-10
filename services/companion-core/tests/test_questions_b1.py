"""Phase 44 I-2 follow-up: the question-side decomposer, the period filter, the not-understood clause and the end-to-end plan. Fixtures are invented for these tests (no dev15 or dev16 content); no model, no I/O.
The decomposer's contract: type a clause only when the subject, relation, ask and time are unambiguous; otherwise withhold THAT clause with a reason and answer the rest."""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from companion_core.knowledge.answerability_b1 import (
    AdmissionPolicy,
    Ask,
    AuthDecision,
    Component,
    DiscoveryItem,
    Scope,
    State,
    build_plan,
)
from companion_core.knowledge.answerability_b1.questions import (
    decompose_question,
    plan_question,
)
from companion_core.knowledge.answerability_b1.registry import (
    EntityRegistry,
    EntityType,
    Registry,
)

REG = Registry()
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
POLICY = AdmissionPolicy(expected_policy_version="p1")


def typed(q, registry=REG):
    d = decompose_question(q, registry)
    return [(c.subject, c.relation, c.ask.value, c.scope.value, c.period) for c in d.typed], [c.reason for c in d.uncertain]


# -- structure: subject, relation, ask, time ---------------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("q", "want"), [
    ("Who owns the Zeta stream?", ("Zeta stream", "owner", "value", "any", None)),
    ("What is Harbor's default model?", ("Harbor", "default_model", "value", "any", None)),
    ("Which host serves Orca-30B?", ("Orca-30B", "runs_on", "value", "any", None)),
    ("What are Northwind Traders' support hours?", ("Northwind Traders", "support_hours", "value", "any", None)),
    ("What does Nadia Orlov review?", ("Nadia Orlov", "reviews", "value", "any", None)),
    ("Who was in the Harbor planning meeting?", ("Harbor", "attends", "value", "any", None)),
    ("Who is the security reviewer for Harbor?", ("Harbor", "security_reviewer", "value", "any", None)),
    ("Who reviews security for Cedar?", ("Cedar", "security_reviewer", "value", "any", None)),
    ("Who will fix the Harbor rollback test?", ("Harbor", "test_fixer", "value", "any", None)),
    ("How long do I have to roll back a failed Harbor deploy?", ("Harbor", "rollback_window", "value", "any", None)),
    ("Does Harbor have a staging environment?", ("Harbor", "staging_env", "existence", "any", None)),
    ("Which day is the Harbor design review?", ("Harbor", "review_day", "value", "any", None)),
    ("Was the Harbor design review day updated after the other memory gave a different answer?", ("Harbor", "review_day", "ordering", "any", None)),
    ("Who is in charge of the Ferry queue?", ("Ferry queue", "owner", "value", "any", None)),
    ("Could you tell me Harbor's default model?", ("Harbor", "default_model", "value", "any", None)),
])
def test_one_clause_is_typed_exactly(q, want):
    got, why = typed(q)
    assert got == [want] and not why


def test_the_role_word_in_the_lead_of_a_project_does_not_make_it_a_question_about_the_lead():
    assert typed("When will the Harbor lead be away next?")[0] == [("Harbor", "vacation", "value", "any", None)]
    assert typed("Who is the Harbor lead?")[0] == [("Harbor", "lead", "value", "any", None)]


@pytest.mark.parametrize(("q", "scope", "period"), [
    ("Who used to own the Ferry queue?", "past", None),
    ("What was the old retry limit of the Shale store?", "past", None),
    ("How many retries did the archived Kiln scheduler architecture allow?", "past", None),
    ("Which model did Aspen use by default in February?", "past", ("in", "february")),
    ("What was Willow's default model before November?", "past", ("before", "november")),
    ("What was the Zenith default model as of June?", "past", ("as of", "june")),
    ("What is Harbor's current default model?", "current", None),
    ("Who is on call for Cedar right now?", "current", None),
])
def test_the_time_qualification_is_read_from_the_question(q, scope, period):
    got, why = typed(q)
    assert not why and got[0][3] == scope and got[0][4] == period


def test_a_fronted_time_phrase_belongs_to_the_clause_after_it():
    assert typed("Before November, which model did Sable use by default?")[0] == [("Sable", "default_model", "value", "past", ("before", "november"))]


@pytest.mark.parametrize("q", [
    "What was the Harbor default model in 2025?", "Who was on call for Cedar last week?", "Who is on call for Lantern this month?", "What did Aspen use by default after March?",
    "Who is on call for Harbor on Friday?", "Who leads Harbor next year?"])
def test_a_period_the_records_cannot_be_matched_to_is_withheld_not_ignored(q):
    got, why = typed(q)
    assert not got and why[0] in ("unsupported_period", "unsupported_qualifier")


def test_next_is_part_of_a_vacation_question_but_a_period_for_anything_else():
    assert typed("When is the Harbor lead's next vacation?")[0]
    assert typed("Who is the next lead of Harbor?")[1] == ["unsupported_period"]


# -- several clauses ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_clauses_are_split_and_each_is_typed_on_its_own():
    got, why = typed("Who owns the Beacon queue, who leads Meadow, and what is Zenith's default model?")
    assert [g[:2] for g in got] == [("Beacon queue", "owner"), ("Meadow", "lead"), ("Zenith", "default_model")] and not why
    assert [g[:2] for g in typed("Who leads Harbor; who is on call for Lantern?")[0]] == [("Harbor", "lead"), ("Lantern", "on_call")]
    assert [g[:2] for g in typed("Who leads Harbor? Who is on call for Lantern?")[0]] == [("Harbor", "lead"), ("Lantern", "on_call")]


def test_a_bare_second_subject_continues_the_relation_and_a_bare_second_relation_continues_the_subject():
    assert [g[:2] for g in typed("Who owns the Ember API and the Kiln scheduler?")[0]] == [("Ember API", "owner"), ("Kiln scheduler", "owner")]
    assert [g[:2] for g in typed("What are Harbor's default model and rollback window?")[0]] == [("Harbor", "default_model"), ("Harbor", "rollback_window")]


def test_an_untypeable_clause_is_withheld_and_the_typeable_ones_are_kept():
    got, why = typed("Who owns the Ferry queue, and what is its retry limit?")
    assert [g[:2] for g in got] == [("Ferry queue", "owner")] and why == ["pronoun_reference"]
    got, why = typed("What is Cedar's favourite colour, and who leads Marlin?")
    assert [g[:2] for g in got] == [("Marlin", "lead")] and why == ["no_relation_cue"]


# -- what must be withheld rather than guessed -------------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("q", "reason"), [
    ("Who owns it?", "pronoun_reference"), ("Who is on call?", "no_subject"), ("What is the retry limit?", "no_subject"), ("Why did Cedar switch models?", "unsupported_question_type"),
    ("How many employees does Harbor have?", "no_relation_cue"), ("Summarise the Harbor project.", "no_relation_cue"), ("Is Pablo Reyes the Cedar lead?", "value_in_question"),
    ("Is Cedar's default model Kestrel-3B?", "value_in_question"), ("Does the Ferry queue retry 5 times?", "value_in_question"), ("Is the Harbor standup on Monday?", "unsupported_qualifier"),
    ("Who owns the Ferry queue at Cedar?", "ambiguous_subject"), ("Where is the Harbor lead?", "answer_type_mismatch"), ("Who is the rollback window for Cedar?", "answer_type_mismatch"),
    ("Who is in charge of Cedar?", "ambiguous_relation"), ("Who leads Swift-6B?", "subject_type_mismatch"), ("Which host serves Harbor?", "subject_type_mismatch"), ("Who runs Cedar?", "subject_type_mismatch"),
    ("Does Cedar have a lead?", "existence_mismatch"), ("Which staging environment does Harbor use?", "existence_mismatch"), ("What is the latest Harbor standup time?", "weak_ordering_cue"),
    ("What is the old and current retry limit of the Shale store?", "no_relation_cue"),
])
def test_a_clause_that_cannot_be_typed_unambiguously_is_withheld_with_its_reason(q, reason):
    got, why = typed(q)
    assert not got and why[0] == reason


@pytest.mark.parametrize(("q", "relation"), [
    ("Which day does Cedar release?", "release_day"), ("What day do Cedar releases ship on?", "release_day"), ("What day is the Zenith release?", "release_day"),
    ("Who approved the Cedar release?", "approver"), ("Who signed off the Marlin release?", "approver"), ("Who is the release approver for Willow?", "approver"),
    ("Who should I escalate Cedar incidents to?", "escalation_contact"), ("Who is the escalation contact for Harbor?", "escalation_contact"), ("Who handles escalations for the Hopper ingest service?", "escalation_contact")])
def test_the_formerly_held_out_relations_are_typed_to_themselves_and_not_to_a_neighbour(q, relation):
    got, why = typed(q)
    assert [g[1] for g in got] == [relation] and not why


@pytest.mark.parametrize("q", ["Who gives the go-ahead for the Lantern release?", "Who has to approve a Meadow deploy?", "When does Briar deploy?", "Who authorised the Harbor release?"])
def test_a_synonym_or_neighbour_the_relation_does_not_cover_is_withheld_never_typed_as_a_neighbour(q):
    """Only the release approver is defined: a deploy is not a release, and "go-ahead" / "authorised" are not in the relation's words. The risk is a near-miss typing them as another relation."""
    got, why = typed(q)
    assert not got and why == ["no_relation_cue"]


@pytest.mark.parametrize(("q", "reason"), [
    ("Who approved the budget for Fennel?", "answer_type_mismatch"), ("Who is the budget approver for Grove?", None), ("When was the last Nimbus release?", None),
    ("Which day was the Drift release approved?", None), ("Is the Fennel release on a Friday?", None), ("Who approved the Cobalt release last month?", "unsupported_period")])
def test_a_near_miss_of_a_defined_relation_is_withheld(q, reason):
    got, why = typed(q)
    assert not got
    if reason:
        assert why[0] == reason


def test_the_budget_question_is_still_a_budget_question():
    assert typed("Through when is Nimbus's budget approved?")[0] == [("Nimbus", "budget_through", "value", "any", None)]


def test_the_decomposer_never_raises_on_odd_input():
    for q in ("", "   ", "?", "Who", "and and and", "Who owns the?", "🙂", "A" * 5000):
        d = decompose_question(q, REG)
        assert isinstance(d.fallback, bool)


def test_a_lower_case_spelling_needs_an_explicit_entry():
    q = "who owns the ferry queue"
    assert typed(q)[0] == []
    reg = Registry(entities=EntityRegistry().with_entries([("Ferry queue", EntityType.SYSTEM, "Ferry")]))
    assert typed(q, reg)[0] == [("Ferry queue", "owner", "value", "any", None)]


# -- the period filter on a past answer -------------------------------------------------------------------------------------------------------------------------------------------------------------

def item(ref, text, *, author="owner", title=""):
    store, rid = ref.split(":", 1)
    return DiscoveryItem(ref, text, {"store": store, "record_id": rid, "author_class": author, "created_at": NOW - timedelta(days=30), "retrieved_at": NOW - timedelta(minutes=1), "acl_revision": 1}, title)


def ask(q, *items):
    its = list(items)
    auths = {i.ref: AuthDecision(True, NOW - timedelta(seconds=5), "p1", 1) for i in its}
    eids = {i.ref: f"E{n}" for n, i in enumerate(its, 1)}
    return plan_question(q, REG, its, auths, now=NOW, eids=eids, policy=POLICY)


MARCH = item("memory:m1", "As of March, the Harbor default model was Wren-3B.")
OCTOBER = item("memory:m2", "As of October, the Harbor default model is Falcon-4B.")


def test_a_named_month_must_be_matched_by_the_records_own_dating():
    assert ask("Which model did Harbor use by default in March?", MARCH, OCTOBER)[0].claims[0].state is State.HISTORICAL
    p = ask("Which model did Harbor use by default in January?", MARCH, OCTOBER)[0]
    assert p.claims[0].state is State.UNSUPPORTED and "no_record_for_requested_period" in p.claims[0].reasons and "Wren" not in p.answer
    assert ask("What was Harbor's default model before October?", MARCH, OCTOBER)[0].claims[0].state is State.HISTORICAL
    assert ask("What was Harbor's default model before March?", MARCH, OCTOBER)[0].claims[0].state is State.UNSUPPORTED  # March is not before March
    assert ask("What was Harbor's default model as of March?", MARCH, OCTOBER)[0].claims[0].state is State.HISTORICAL


def test_an_undated_or_year_dated_past_record_never_answers_a_named_month():
    undated = item("memory:m3", "Formerly the Harbor default model was Wren-3B.")
    dated = item("memory:m4", "As of March 2024, the Harbor default model was Wren-3B.")
    assert ask("Which model did Harbor use by default in March?", undated)[0].claims[0].state is State.UNSUPPORTED
    assert ask("Which model did Harbor use by default in March?", dated)[0].claims[0].state is State.UNSUPPORTED
    assert ask("What was Harbor's previous default model?", undated)[0].claims[0].state is State.HISTORICAL  # no month asked: the explicit past wording is enough


# -- end to end ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

OWNER = item("memory:o1", "Pablo Reyes owns the Beacon queue.")
LEAD = item("memory:l1", "Nadia Orlov is the Harbor lead.")


def test_end_to_end_answers_the_supported_part_and_says_what_it_could_not_work_out():
    p, d = ask("Who owns the Beacon queue, and what is its retry limit?", OWNER, LEAD)
    assert p.answer.split("\n")[0] == "The owner of the Beacon queue is Pablo Reyes [E1]."
    assert p.answer.split("\n")[1] == "I could not work out one part of the question, so I have not answered it."
    assert d.fallback and p.fallback and p.claims[1].reasons[:2] == ("no_relation_spec", "clause_not_understood") and not p.claims[1].assertable


def test_end_to_end_several_unclear_clauses_are_one_line_and_never_claim_the_records_are_silent():
    p, _ = ask("Who leads Harbor, and why, and what about it?", OWNER, LEAD)
    assert p.answer == "The lead of Harbor is Nadia Orlov [E2].\nI could not work out 2 parts of the question, so I have not answered them."
    assert "records do not" not in p.answer


def test_end_to_end_a_question_with_no_typeable_clause_is_a_fallback_with_no_claim_about_the_records():
    p, d = ask("Tell me about Cedar.", OWNER)
    assert d.all_uncertain and p.fallback and p.answer == "I could not work out one part of the question, so I have not answered it."


def test_end_to_end_an_unsupported_typed_clause_is_still_the_records_do_not_say_template():
    p, _ = ask("Who is on call for Harbor?", OWNER, LEAD)
    assert p.answer == "The records do not say the person on call for Harbor."


def test_the_not_understood_text_has_no_path_for_a_value_or_a_citation():
    comp = Component("c1", "", (), None)
    p = build_plan([comp], [OWNER], {}, now=NOW, specs=REG.specs(), eids={}, known_subjects=[], policy=POLICY)
    assert p.claims[0].text == "I could not work out one part of the question, so I have not answered it." and p.claims[0].assertable == () and p.tickets[0].values == ()
    assert p.tickets[0].component.ask is Ask.VALUE and p.tickets[0].component.scope is Scope.ANY


# -- the labelled development set and the frozen review sample -----------------------------------------------------------------------------------------------------------------------------------------

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load(name):
    sys.path.insert(0, str(SEL))
    try:
        spec = importlib.util.spec_from_file_location(name, SEL / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(SEL))


def test_the_labelled_set_is_frozen_and_the_decomposer_invents_no_structure_on_it():
    ev = _load("decomp_eval")
    ev.verify_freeze()  # raises if the set or its authoring script changed after the freeze
    r = ev.evaluate(Registry())
    c = r["counts"]
    assert c["questions"] == 164 and c["parts_expected"] == 160
    assert c["invented_structures"] <= 1 and c["exact"] / c["questions"] >= 0.90  # development-set floor, not an acceptance threshold
    assert all(f["hard"] or f["id"] in ("L089", "L152") for f in r["failures"])  # every miss is a marked hard case or one of two known label ambiguities, documented in the record


def test_the_review_sample_was_frozen_before_any_new_reply_and_has_not_changed():
    import hashlib

    for line in (SEL / "REVIEW_SAMPLE_FREEZE.sha256").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        digest, name = line.split()
        assert hashlib.sha256((SEL / name).read_bytes()).hexdigest() == digest
