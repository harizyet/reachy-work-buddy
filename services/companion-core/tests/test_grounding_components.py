"""Groundedness components C1 to C5 (experimental; no model, no database). Each is tested alone; C5 is tested with seeded invalid citations, because the guardrail is ZERO accepted citations to a
nonexistent or unauthorised source span, and a model-written citation or quote is never proof by itself."""

from companion_core.knowledge.grounding import (
    answerability,
    claims,
    propositions,
    routes,
    validate,
)
from companion_core.knowledge.sufficiency import Piece

PEOPLE = ["Amara Osei", "Bruno Keller", "Chiara Rossi"]
ARCH = Piece("# Jobs\nJobs flow through the Ferry queue. A failed job is retried up to 5 times before it is parked.\n\n# Model serving\nCedar serves Kestrel-3B on the GPU host. Interactive requests use the fast path and scheduled jobs use the deep path.", "Cedar architecture", "cedar")
OWNER = Piece("Bruno Keller owns the Ferry queue.", "", "cedar")
SIBLING = Piece("Chiara Rossi owns the Hopper ingest service.", "", "osprey")
CONFLICT = Piece("Failed Cedar jobs are retried 9 times before they are parked.", "", "cedar")
ARCHIVED = Piece("Jobs flow through the Ferry queue. A failed job is retried up to 2 times before it is parked.", "Cedar architecture v1 (archived)", "cedar")


def test_c1_selects_the_record_that_asserts_the_relation_for_the_subject_and_drops_the_rest():
    pieces = [SIBLING, ARCH, OWNER]
    sel = propositions.select("Who owns the Ferry queue?", pieces, known_people=PEOPLE)
    assert sel.selected == [2]
    shown = propositions.reorder(pieces, sel, "filter")
    assert pieces[2] in shown and pieces[0] not in shown[:1]


def test_c1_a_sibling_entitys_fact_does_not_assert_the_subjects_fact():
    sel = propositions.select("Who owns the Gantry scheduler?", [SIBLING, OWNER], known_people=PEOPLE)
    assert sel.selected == [] and sel.other_subject_assertions[0] >= 1


def test_c1_the_qualifier_keeps_a_cross_sentence_combination_from_counting():
    # the document names the model and, in another sentence, the deep path; no sentence joins them
    sel = propositions.select("Which model does the deep path serve for Cedar?", [ARCH], known_people=PEOPLE)
    assert sel.assertions[0] == [] or all("deep" not in a.unit.lower() for a in sel.assertions[0])
    assert answerability.assess(sel).state == answerability.UNESTABLISHED


def test_c1_a_possessive_cue_is_a_modifier_not_the_relation():
    props = propositions.read_question("When is the Cedar lead's next vacation?")
    assert props[0].relation is None


def test_c2_states_are_computed_without_any_generator():
    established = answerability.assess(propositions.select("Who owns the Ferry queue?", [OWNER], known_people=PEOPLE))
    assert established.state == answerability.ESTABLISHED and answerability.note(established) is None
    missing = answerability.assess(propositions.select("Who owns the Gantry scheduler?", [SIBLING], known_people=PEOPLE))
    assert missing.state == answerability.UNESTABLISHED and missing.reason == "related_other_subject"
    assert "don't have a record" in answerability.template_reply(missing)
    conflicted = answerability.assess(propositions.select("How many times does the Ferry queue retry a failed job?", [ARCH, CONFLICT], known_people=PEOPLE))
    assert conflicted.state == answerability.CONFLICTED


def test_c2_past_statements_do_not_conflict_with_the_present_one():
    present_only = answerability.assess(propositions.select("How many times does the Ferry queue retry a failed job?", [ARCH, ARCHIVED], known_people=PEOPLE))
    assert present_only.state == answerability.ESTABLISHED
    history = answerability.assess(propositions.select("How many times did the Ferry queue retry a failed job previously?", [ARCH, ARCHIVED], known_people=PEOPLE))
    assert history.state == answerability.ESTABLISHED and "2" in history.clauses[0].values


def test_c2_the_template_reply_exists_only_for_unestablished_and_names_nothing_else():
    a = answerability.assess(propositions.select("Who owns the Gantry scheduler?", [SIBLING], known_people=PEOPLE))
    reply = answerability.template_reply(a)
    assert "Chiara" not in reply and "Hopper" not in reply  # related records elsewhere are not described
    est = answerability.assess(propositions.select("Who owns the Ferry queue?", [OWNER], known_people=PEOPLE))
    assert answerability.template_reply(est) is None


def test_c3_attendees_come_from_the_meeting_record_and_a_missing_meeting_is_stated_plainly():
    meetings = [{"id": "mt-cedar", "title": "Cedar planning", "speaker_names": {"SPEAKER_00": "Amara Osei", "SPEAKER_01": "Bruno Keller"}}]
    r = routes.route_attendees("Who attended the Cedar planning meeting?", meetings)
    assert r and r.found and "Amara Osei" in r.text and "Bruno Keller" in r.text and r.sources == ("meeting:mt-cedar",)
    none = routes.route_attendees("Who attended the Marlin planning meeting?", meetings)
    assert none and not none.found and "don't have a record" in none.text
    assert routes.route_attendees("Who owns the Ferry queue?", meetings) is None


def test_c4_parse_rejects_anything_that_is_not_the_requested_json_and_render_uses_only_given_claims():
    assert claims.parse("The owner is Bruno.") is None
    parsed = claims.parse('{"claims":[{"claim":"Bruno Keller owns the Ferry queue.","evidence":"E1","quote":"Bruno Keller owns the Ferry queue."}],"unknown":["its on-call contact"]}')
    assert parsed and len(parsed[0]) == 1
    text = claims.render(parsed[0], parsed[1], 0)
    assert "[E1]" in text and "on-call contact" in text and "don't have a record" in text
    assert "don't have a record" in claims.render([], [], 0)


EVIDENCE = {
    "E1": validate.Evidence(("memory:m001",), "Bruno Keller owns the Ferry queue.", "memory Cedar", True),
    "E2": validate.Evidence(("document:doc-cedar-arch#2",), "Cedar serves Kestrel-3B on the GPU host. Interactive requests use the fast path and scheduled jobs use the deep path.", "Cedar architecture", True),
    "E3": validate.Evidence(("document:doc-secret",), "Dana Ito will audit all build logs.", "incident", False),
}


def claim(text, eid, quote):
    return {"claim": text, "evidence": eid, "quote": quote}


def test_c5_accepts_a_claim_whose_source_authorization_span_and_relation_all_check_out():
    v = validate.validate([claim("Bruno Keller owns the Ferry queue.", "E1", "Bruno Keller owns the Ferry queue.")], EVIDENCE)
    assert len(v.accepted) == 1 and v.spans[0][0] == "E1"


def test_c5_rejects_every_seeded_invalid_citation():
    seeded = [
        (claim("Bruno Keller owns the Ferry queue.", "E9", "Bruno Keller owns the Ferry queue."), "unknown_source"),  # id not in this turn
        (claim("Dana Ito will audit all build logs.", "E3", "Dana Ito will audit all build logs."), "unauthorized_source"),  # exists but not authorised
        (claim("Bruno Keller owns the Ferry queue.", "E1", ""), "trivial_quote"),  # empty quote
        (claim("Bruno Keller owns the Ferry queue.", "E1", "owns"), "trivial_quote"),  # trivial quote
        (claim("Bruno Keller owns the Ferry queue.", "E1", "Amara Osei owns the Ferry queue."), "quote_not_in_item"),  # fabricated quote
        (claim("The deep path serves Kestrel-3B.", "E2", "scheduled jobs use the deep path"), "claim_value_not_in_span"),  # joins two sentences: the model name is not in the quote
        (claim("Bruno Keller leads the Ferry queue.", "E1", "Bruno Keller owns the Ferry queue."), "relation_not_in_span"),  # the claim's relation is not what the quote says
    ]
    v = validate.validate([c for c, _ in seeded], EVIDENCE)
    assert v.accepted == []
    assert [r for _, r in v.rejected] == [reason for _, reason in seeded]


def test_c5_a_model_written_offset_or_extra_field_changes_nothing():
    c = claim("Bruno Keller owns the Ferry queue.", "E1", "Bruno Keller owns the Ferry queue.") | {"start": 999, "end": 1000}
    v = validate.validate([c], EVIDENCE)
    assert v.spans[0][1:] == (0, len("bruno keller owns the ferry queue."))  # offsets are computed by code
