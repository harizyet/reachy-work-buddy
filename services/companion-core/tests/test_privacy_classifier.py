import pytest
from companion_core.privacy_classifier import (
    classify_privacy,
    classify_question_privacy,
)

from shared.models.response import Privacy


def test_public_text_by_default() -> None:
    assert classify_privacy("what's the weather like today") == Privacy.PUBLIC


def test_sensitive_keyword_wins() -> None:
    assert classify_privacy("what is my salary this year") == Privacy.SENSITIVE
    assert classify_privacy("this is CONFIDENTIAL information") == Privacy.SENSITIVE


def test_work_private_keyword() -> None:
    assert classify_privacy("what's on my calendar today") == Privacy.WORK_PRIVATE


def test_sensitive_keyword_takes_priority_over_work_private() -> None:
    # "meeting" (work-private) and "confidential" (sensitive) both present —
    # the more restrictive classification must win.
    assert classify_privacy("the confidential meeting notes") == Privacy.SENSITIVE


@pytest.mark.parametrize("text", [
    "How do I schedule a meeting on Outlook?",
    "How do I write a polite email?",
    "What is a calendar year?",
    "I have a question about how to schedule a meeting in Outlook",
])
def test_a_general_question_with_a_work_word_is_public(text) -> None:
    # Owner decision 2026-09-26: work words alone don't make it private.
    assert classify_question_privacy(text) == Privacy.PUBLIC


@pytest.mark.parametrize("text", [
    "When is my next meeting?", "What's on my calendar today?", "Do I have any meetings tomorrow?",
    "Any meetings today?", "Who emailed me?", "Any new emails?", "Tell me today's agenda",
    "I have a meeting at noon.", "I'm meeting Sarah at 3",
])
def test_a_question_about_the_owners_own_work_data_is_work_private(text) -> None:
    assert classify_question_privacy(text) == Privacy.WORK_PRIVATE


def test_question_sensitive_keywords_still_count_anywhere() -> None:
    assert classify_question_privacy("What's the average salary for engineers?") == Privacy.SENSITIVE
