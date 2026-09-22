from companion_core.privacy_classifier import classify_privacy

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
