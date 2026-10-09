"""Evidence sufficiency (knowledge/sufficiency.py): a deterministic, lexical check of whether the evidence speaks to what was asked. It is a note and a retry trigger, never a proof; these tests pin
what it does and, as importantly, what it deliberately does not do (paraphrase and candidate numbers are not gaps)."""

from companion_core.knowledge.sufficiency import (
    Piece,
    abstention,
    assess,
    coverage_note,
    question_terms,
    retry_query,
)

RUNBOOK = Piece("Roll back within 30 minutes of a failed deploy by running the rollback script.", "Lantern runbook", "lantern")
ARCH = Piece("Harbor serves Falcon-7B on the GPU host. A failed job is retried up to 5 times before it is parked.", "Harbor architecture", "harbor")
OWNER = Piece("Tomas Weber owns the Quill message queue.", "", "harbor")


def test_names_and_other_words_are_separated():
    names, aspects = question_terms("What is the rollback window for Harbor's Falcon-7B?")
    assert names == ["Harbor", "Falcon-7B"] and "rollback" in aspects and "window" in aspects and "what" not in aspects


def test_the_opening_question_word_is_not_a_name():
    assert question_terms("Who owns the Quill queue?")[0] == ["Quill"]
    assert question_terms("Which model runs on the GPU host?")[0] == ["GPU"]


def test_evidence_that_covers_the_question_is_sufficient():
    a = assess("Who owns the Quill message queue?", [OWNER])
    assert a.sufficient and coverage_note(a) is None and abstention(a) is None and retry_query(a) is None


def test_no_evidence_is_none_and_gets_the_fixed_abstention():
    a = assess("What is the Quill queue port?", [])
    assert a.verdict == "none" and "don't have anything" in abstention(a)


def test_a_name_the_evidence_never_mentions_is_absent_and_a_family_member_is_named():
    a = assess("Where does Falcon-3B run?", [ARCH])
    assert a.verdict == "entity_absent" and a.absent_entities == ("Falcon-3B",) and a.all_absent and a.similar == ("Falcon-7B",)
    assert "Falcon-3B" in coverage_note(a) and "Falcon-7B" in coverage_note(a)
    assert "Falcon-3B" in abstention(a)


def test_one_missing_name_among_present_ones_is_noted_but_never_a_gate():
    a = assess("What is the Beacon support line number and when does support close on Saturdays?", [Piece("Beacon Analytics support hours are 9 to 5 on weekdays. The support line is 555-0142.", "Vendor note")])
    assert a.verdict == "entity_absent" and a.absent_entities == ("Saturdays",) and not a.all_absent
    assert abstention(a) is None and "Saturdays" in coverage_note(a)


def test_the_aspect_asked_about_found_only_for_another_entity_is_a_mismatch():
    a = assess("What is the rollback window for Harbor?", [RUNBOOK, Piece("The Lantern rollback window is 60 minutes after a failed deploy.", "", "lantern")])
    assert a.verdict == "entity_absent" and a.all_absent  # Harbor appears nowhere in this evidence
    both = assess("What is the rollback window for Harbor?", [RUNBOOK, ARCH])
    assert both.verdict == "entity_mismatch" and "Lantern runbook" in both.aspect_titles
    assert "Lantern runbook" in abstention(both) and "Harbor" in abstention(both)


def test_paraphrase_is_not_a_gap():
    # "date", "long" and "keep" rarely appear verbatim in the evidence that answers; ordinary words never produce a partial verdict
    assert assess("How long should I watch the dashboard after deploying Lantern?", [Piece("Deploy Lantern with the release script and watch the dashboard for ten minutes.", "Lantern runbook", "lantern")]).sufficient


def test_a_number_the_question_offers_is_a_candidate_not_a_subject():
    assert assess("Is the Lantern rollback window 45 minutes?", [RUNBOOK]).sufficient


def test_an_identifier_like_word_the_evidence_lacks_is_partial():
    a = assess("Who benchmarked Falcon-7B and what was the p95 latency?", [Piece("Tomas Weber: I benchmarked Falcon-7B and the interactive latency is acceptable.", "Harbor planning")])
    assert a.verdict == "partial" and a.uncovered_aspects == ("p95",) and "p95" in coverage_note(a)
    assert abstention(a) is None and retry_query(a) == "Falcon-7B p95"


def test_the_entity_present_but_the_whole_topic_missing_is_a_note_not_a_gate():
    a = assess("What is Harbor's on-call rotation?", [ARCH])
    assert a.verdict == "topic_missing" and abstention(a) is None and "on-call" in coverage_note(a)


def test_stemming_joins_retry_retries_retried():
    assert assess("How often is a Harbor job retried?", [ARCH]).sufficient and assess("Harbor retry policy?", [ARCH]).verdict in ("sufficient", "topic_missing")


def test_a_retry_query_uses_the_names_and_the_words_no_item_held():
    a = assess("What is Harbor's on-call rotation?", [ARCH])
    assert retry_query(a) == "Harbor on-call rotation"
