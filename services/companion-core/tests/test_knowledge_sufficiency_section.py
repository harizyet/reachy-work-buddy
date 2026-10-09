"""Section-level coverage (knowledge/sufficiency_section.py): the unit of co-occurrence is a passage, not an item."""

from companion_core.knowledge.sufficiency import Piece, assess
from companion_core.knowledge.sufficiency_section import assess_sections, passages

ARCH = Piece("# Queue\nJobs flow through the Quill message queue. A failed job is retried up to 5 times.\n\n# Model serving\nHarbor serves Falcon-7B on the GPU host.", "Harbor architecture", "harbor")


def test_passages_are_sentences_that_keep_the_title_heading_and_scope():
    ps = passages(ARCH)
    assert [p.text for p in ps] == ["Jobs flow through the Quill message queue.", "A failed job is retried up to 5 times.", "Harbor serves Falcon-7B on the GPU host."]
    assert "Harbor architecture Queue" in ps[0].title and "Model serving" in ps[2].title and ps[0].scope == "harbor"


def test_a_name_in_one_sentence_does_not_vouch_for_an_aspect_in_another_sentence():
    # item level: the document holds Quill and a model, so it reads sufficient; passage level: no sentence holds both
    q = "Which model does the Quill run?"
    assert assess(q, [ARCH]).sufficient
    assert assess_sections(q, [ARCH]).verdict == "entity_mismatch"


def test_a_name_in_the_title_counts_for_every_passage_of_that_item():
    runbook = Piece("# Rollback\nRoll back within 30 minutes of a failed deploy.", "Lantern runbook", "lantern")
    assert assess_sections("What is the Lantern rollback window?", [runbook]).sufficient


def test_the_same_notes_verdicts_otherwise():
    assert assess_sections("Where does Falcon-3B run?", [ARCH]).verdict == "entity_absent"
    assert assess_sections("Who owns it?", []).verdict == "none"


def test_descriptor_exclusion_ignores_the_word_after_a_name():
    # "queue" in a sentence about Quill says nothing about which model the Quill queue uses
    pieces = [Piece("Jobs flow through the Quill message queue.", "Harbor architecture", "harbor"), Piece("Harbor serves the Falcon-7B model on the GPU host.", "Harbor architecture", "harbor")]
    q = "Which model does the Quill queue use?"
    assert assess_sections(q, pieces).sufficient
    assert assess_sections(q, pieces, descriptors=True).verdict == "entity_mismatch"
