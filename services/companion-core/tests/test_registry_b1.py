"""Phase 44 I-2 follow-up: the typed entity registry, the relation registry and the model-name / known-subject collision. Fixtures are invented for these tests (no dev15 or dev16 content); no model, no I/O."""

import re
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
    admit,
    build_plan,
)
from companion_core.knowledge.answerability_b1.registry import (
    RELATIONS,
    EntityRegistry,
    EntityType,
    Registry,
)

P = EntityType
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
POLICY = AdmissionPolicy(expected_policy_version="p1")


def types(text, **kw):
    return {(m.subject, tuple(sorted(t.value for t in m.types))) for m in EntityRegistry().mentions(text, **kw)}


# -- entities are typed by form, so a name never seen before is a known type ----------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "subject", "type_"), [
    ("Who owns the Zeta stream?", "Zeta stream", "system"),
    ("Who owns the Quill ingest service?", "Quill ingest service", "system"),
    ("Who owns the Ember API?", "Ember API", "system"),
    ("Which host serves Orca-30B?", "Orca-30B", "model"),
    ("Which host serves Pika-1.5B?", "Pika-1.5B", "model"),
    ("Who leads Tidewater?", "Tidewater", "project"),
    ("Who attended the Garnet planning meeting?", "Garnet", "meeting"),
    ("Is Swift-6B on the GPU host?", "GPU host", "host"),
])
def test_unseen_names_have_a_known_type(text, subject, type_):
    assert (subject, (type_,)) in types(text)


def test_two_capitalised_words_are_a_person_or_a_vendor_until_a_slot_decides():
    assert ("Northwind Traders", ("person", "vendor")) in types("What are Northwind Traders' support hours?")
    assert ("Anna-Marie Oduya", ("person", "vendor")) in types("What does Anna-Marie Oduya review?")
    assert ("Liam O'Connor", ("person", "vendor")) in types("What does Liam O'Connor review?")


def test_a_sentence_opening_question_word_is_never_a_name():
    got = {s for s, _ in types("Which Quarry Data does Wen Zhao review?")}
    assert "Which Quarry" not in got and "Quarry Data" in got and "Wen Zhao" in got
    assert {s for s, _ in types("What Harbor lead?")} == {"Harbor"}
    assert not types("Who is on call?") and not types("On which day is it?")  # prepositions and wh-words open sentences with a capital


def test_months_and_days_are_not_entities():
    assert not types("In March or on Friday?")
    assert ("Harbor", ("project",)) in types("Who leads Harbor on Friday?")


def test_record_text_does_not_read_a_sentence_opening_capital_as_a_name():
    reg = EntityRegistry()
    assert not [m for m in reg.mentions("Failed Cedar jobs are retried.", initial_ok=False) if m.subject in ("Failed Cedar", "Failed")]
    assert "Cedar" not in {m.subject for m in reg.mentions("Failed Cedar jobs are retried.", initial_ok=False)}  # its words are not re-read as a bare name either
    assert "Cedar" in {m.subject for m in reg.mentions("Retry the Cedar jobs.", initial_ok=False)}


def test_the_longest_span_wins_so_a_shorter_entry_never_breaks_a_system_name():
    reg = EntityRegistry().with_entries([("Sluice", P.PROJECT, "Sluice")])
    assert {(m.subject, tuple(t.value for t in m.types)) for m in reg.mentions("Who owns the Sluice cache?")} == {("Sluice cache", ("system",))}
    assert {(m.subject, tuple(t.value for t in m.types)) for m in reg.mentions("Who leads Sluice?")} == {("Sluice", ("project",))}


def test_an_explicit_entry_types_a_lower_case_spelling():
    reg = EntityRegistry().with_entries([("Ferry queue", P.SYSTEM, "Ferry"), ("Harbor", P.PROJECT, "Harbor")])
    assert {(m.subject, m.alias) for m in reg.mentions("who owns the ferry queue and who leads harbor")} == {("Ferry queue", "Ferry"), ("Harbor", "Harbor")}
    assert not EntityRegistry().mentions("who owns the ferry queue")  # grammar alone needs the capitals


def test_an_ambiguous_mention_is_not_registered_as_an_entry():
    reg = EntityRegistry()
    pool = reg.harvest(["Escalate to Olga Petrova today. Notes from Olga Petrova and the Ferry queue."])
    learned = reg.with_entries(pool)
    assert all(t in (P.SYSTEM, P.PROJECT, P.MODEL, P.HOST) for _, t, _ in learned.entries)  # the person-or-vendor name has two candidate types and is left to the grammar


def test_harvest_ignores_headings_and_sentence_opening_words():
    texts = ["# Overview\nCedar is an internal platform.\n\n# Jobs\nJobs flow through the Ferry queue. Deploy Cedar with the release script.\n\n# Root cause\nThe Cedar credentials were rotated."]
    found = {m.subject for m in EntityRegistry().harvest(texts)}
    assert found == {"Cedar", "Ferry queue"}


# -- relations: independent of the benchmark, and honest about what is held out ----------------------------------------------------------------------------------------------------------------------

def test_the_three_formerly_held_out_relations_are_defined_with_their_domain_meaning():
    by = {r.name: r for r in RELATIONS}
    assert by["release_day"].kind == "day" and by["release_day"].subject_types == {EntityType.PROJECT}
    assert by["escalation_contact"].kind == "person" and by["approver"].kind == "person"
    # the speaker of "I will escalate X" is not the contact, and a promise to approve is not an approval: no first-person path establishes either
    assert by["escalation_contact"].spec().structured is None and by["approver"].spec().structured is None
    assert by["owner"].spec().structured == "speaker"  # unchanged for the relations a speaker can establish


def test_the_registry_modules_do_not_depend_on_the_benchmark_or_the_gold():
    import companion_core.knowledge.answerability_b1.questions as q
    import companion_core.knowledge.answerability_b1.registry as r

    for mod in (q, r):
        src = Path(mod.__file__).read_text()
        assert not re.search(r"^\s*(?:from|import)\s+(?:benchmarks|selective|aq)\b", src, re.MULTILINE)
        assert "cases_dev1" not in src and "atoms_v4" not in src and "facts_v4" not in src


def test_every_relation_names_its_value_and_a_label_that_carries_the_subject():
    reg = Registry()
    for r in RELATIONS:
        assert "{S}" in r.label and r.asks() and r.subject_types
        assert reg.specs()[r.name].kind == r.kind
    m = EntityRegistry().mentions("the Ferry queue")[0]
    assert reg.label("owner", m) == "owner of the Ferry queue"
    assert reg.label("lead", EntityRegistry().mentions("Who leads Harbor?")[0]) == "lead of Harbor"


# -- the model-name / known-subject collision --------------------------------------------------------------------------------------------------------------------------------------------------------------

def item(ref, text, *, author="owner", title=""):
    store, rid = ref.split(":", 1)
    return DiscoveryItem(ref, text, {"store": store, "record_id": rid, "author_class": author, "created_at": NOW - timedelta(days=30), "retrieved_at": NOW - timedelta(minutes=1), "acl_revision": 1}, title)


def world(*items):
    auths = {i.ref: AuthDecision(True, NOW - timedelta(seconds=5), "p1", 1) for i in items}
    eids = {i.ref: f"E{n}" for n, i in enumerate(items, 1)}
    return list(items), auths, eids


def plan(relation, subject, items, *, old_known=None, ask=Ask.VALUE, scope=Scope.ANY, registry=None):
    """The same component, once with a flat list of every name as competing subjects (the first run) and once with the typed competitors."""
    registry = registry or Registry()
    items, auths, eids = world(*items)
    m = registry.entities.mentions(subject)[0]
    comp = Component("c1", m.subject, (m.alias,), relation, ask, scope, registry.label(relation, m))
    pool = registry.entities.harvest(i.text for i in items)

    def typed(c):
        return registry.competitors(relation, c.aliases, pool)

    return build_plan([comp], items, auths, now=NOW, specs=registry.specs(), eids=eids, known_subjects=old_known if old_known is not None else typed, policy=POLICY)


MODELS = ["Falcon-4B", "Wren-3B"]
PROJECTS = ["Harbor", "Lantern"]
ALL_NAMES = [*MODELS, *PROJECTS]


def test_a_model_named_in_a_decision_is_a_value_not_a_competing_subject():
    items = [item("meeting:m1", "So the decision is to keep Falcon-4B as the default model.", author="attendee", title="Harbor planning")]
    flat = plan("decision", "Harbor", items, old_known=ALL_NAMES).tickets[0]
    typed = plan("decision", "Harbor", items).tickets[0]
    assert flat.state is State.UNSUPPORTED  # the first run: the model name made the sentence look like it was about another subject
    assert typed.state is State.SUPPORTED and typed.values[0][0] == "keep Falcon-4B as the default model"


def test_a_model_named_in_a_past_default_is_a_value_not_a_competing_subject():
    items = [item("memory:m1", "As of March, the Harbor default model was Wren-3B.")]
    flat = plan("default_model", "Harbor", items, old_known=ALL_NAMES, scope=Scope.PAST).tickets[0]
    typed = plan("default_model", "Harbor", items, scope=Scope.PAST).tickets[0]
    assert flat.state is State.UNSUPPORTED
    assert typed.state is State.HISTORICAL and typed.values == (("Wren-3B", ("memory:m1",)),)


def test_a_sentence_that_really_names_two_projects_stays_ambiguous_after_the_fix():
    items = [item("memory:m1", "Harbor and Lantern both default to Falcon-4B.")]
    t = plan("default_model", "Harbor", items).tickets[0]
    assert t.state is State.UNSUPPORTED and t.ambiguous_refs == ("memory:m1",)  # the other project is still a competing subject, only the model stopped being one


def test_for_a_model_subject_the_other_models_still_compete_but_a_sharing_project_does_not():
    shared = [item("document:d1", "Harbor serves Falcon-4B on the edge host.", author="third_party")]
    assert plan("runs_on", "Falcon-4B", shared).tickets[0].state is State.SUPPORTED  # a project and its model naturally share the sentence
    two = [item("document:d2", "Falcon-4B and Wren-3B run on the edge host.", author="third_party")]
    t = plan("runs_on", "Falcon-4B", two).tickets[0]
    assert t.state is State.UNSUPPORTED and t.ambiguous_refs == ("document:d2",)  # two models in one sentence: whose host is it?


def test_a_value_type_never_competes_and_a_subject_type_always_does():
    reg = Registry()
    pool = reg.entities.harvest(["Note that Harbor serves Falcon-4B. Remember that Pablo Reyes owns the Beacon queue. Also Lantern differs. Vendor info: Quarry Data support hours are 9 to 5 on weekdays."])
    assert "Falcon-4B" not in reg.competitors("default_model", ["Harbor"], pool) and "Lantern" in reg.competitors("default_model", ["Harbor"], pool)
    assert "Falcon-4B" not in reg.competitors("decision", ["Harbor"], pool)
    assert "Wren-3B" in reg.competitors("runs_on", ["Falcon-4B"], [*pool, *reg.entities.mentions("Wren-3B")])
    assert "Harbor" not in reg.competitors("runs_on", ["Falcon-4B"], pool)
    assert "Pablo" not in reg.competitors("owner", ["Beacon"], pool)  # a person is the VALUE of owner


# -- the admission stem fix: a cue that starts with a regex escape must not hide the relation word from the qualified-object rule ------------------------------------------------------------------------------

def test_a_cue_starting_with_a_word_boundary_does_not_make_its_own_first_word_a_qualifier():
    items = [item("memory:m1", "Harbor design reviews are on Tuesday."), item("memory:m2", "Harbor design reviews are on Friday.")]
    t = plan("review_day", "Harbor", items).tickets[0]
    assert t.state is State.CONFLICTED and {v for v, _ in t.values} == {"Tuesday", "Friday"}


def test_the_qualified_object_tightening_still_holds_with_registry_cues():
    reg = Registry()
    comp = Component("c1", "Beacon queue", ("Beacon",), "owner", Ask.VALUE, Scope.ANY, "owner of the Beacon queue")

    def facts(text):
        its, auths, _ = world(item("note:n1", text))
        return [f.value for f in admit(comp, its, auths, now=NOW, spec=reg.specs()["owner"], known_subjects=[], policy=POLICY).facts]

    assert facts("Pablo Reyes owns the Beacon queue.") == ["Pablo Reyes"]  # the control: the same sentence without the qualified object is admitted
    assert facts("Pablo Reyes owns the Beacon queue schedule.") == []  # about the schedule, not about the queue
