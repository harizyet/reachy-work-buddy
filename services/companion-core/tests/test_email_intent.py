import pytest
from companion_core import email_intent
from companion_core.email.models import DraftStatus, EmailDraft, EmailMessage
from companion_core.email_intent import (
    find_draft_by_query,
    format_approve_reply,
    format_cancel_send_reply,
    format_draft_reply,
    format_inbox_reply,
    format_send_not_approved_reply,
    format_send_not_found_reply,
    format_send_queued_reply,
    match_approve,
    match_cancel_send,
    match_draft,
    match_list_inbox,
    match_send,
)


def _draft(to: str = "a@example.com", subject: str = "Hi", status: DraftStatus = DraftStatus.DRAFT) -> EmailDraft:
    return EmailDraft(to=to, subject=subject, body="body", status=status)


def test_match_list_inbox() -> None:
    assert match_list_inbox("what's in my inbox")
    assert match_list_inbox("read my email")
    assert match_list_inbox("check my inbox")
    assert not match_list_inbox("what's next")


def test_match_draft_extracts_recipient_and_body() -> None:
    assert match_draft("draft email to bob@example.com about the quarterly numbers") == (
        "bob@example.com",
        "the quarterly numbers",
    )
    assert match_draft("draft an email to alice@example.com about rescheduling") == (
        "alice@example.com",
        "rescheduling",
    )


def test_match_draft_returns_none_for_unrelated_text() -> None:
    assert match_draft("remember that I like tea") is None
    assert match_draft("draft email to bob@example.com") is None  # missing "about ..."


def test_match_approve_and_send_prefixes() -> None:
    assert match_approve("approve draft bob@example.com") == "bob@example.com"
    assert match_approve("approve the draft to bob@example.com") == "bob@example.com"
    assert match_send("send draft bob@example.com") == "bob@example.com"
    assert match_send("send the draft to bob@example.com") == "bob@example.com"


def test_match_approve_returns_none_for_unrelated_text() -> None:
    assert match_approve("what's next") is None


def test_match_approve_tolerates_stt_punctuation() -> None:
    """See memory_intent.py's equivalent test — STT transcripts add
    punctuation (commas, trailing periods) a literal prefix match would
    otherwise reject."""
    assert match_approve("Approve draft, bob@example.com.") == "bob@example.com"
    assert match_send("Send draft, bob@example.com.") == "bob@example.com"


def test_format_inbox_reply_empty() -> None:
    assert format_inbox_reply([]) == "Your inbox is empty."


def test_format_inbox_reply_lists_messages() -> None:
    messages = [EmailMessage(sender="boss@example.com", subject="Q3 report", body="see attached")]
    reply = format_inbox_reply(messages)
    assert "Q3 report" in reply
    assert "boss@example.com" in reply


def test_format_draft_reply_mentions_approval_is_required() -> None:
    reply = format_draft_reply(_draft())
    assert "a@example.com" in reply
    assert "approve" in reply.lower()


def test_find_draft_by_query_matches_recipient_or_subject() -> None:
    drafts = [_draft(to="bob@example.com", subject="Numbers"), _draft(to="alice@example.com", subject="Reschedule")]
    assert find_draft_by_query(drafts, "bob").to == "bob@example.com"
    assert find_draft_by_query(drafts, "reschedule").to == "alice@example.com"
    assert find_draft_by_query(drafts, "nobody") is None


def test_format_approve_reply_not_found() -> None:
    assert "couldn't find" in format_approve_reply(None, "bob").lower()


def test_format_approve_reply_found() -> None:
    reply = format_approve_reply(_draft(status=DraftStatus.APPROVED), "bob")
    assert "Approved" in reply
    assert "send draft" in reply.lower()


def test_match_cancel_send_prefixes() -> None:
    assert match_cancel_send("cancel send bob@example.com") == "bob@example.com"
    assert match_cancel_send("undo send bob@example.com") == "bob@example.com"
    assert match_cancel_send("what's next") is None


def test_format_send_queued_reply_mentions_delay_and_cancel() -> None:
    reply = format_send_queued_reply(_draft(status=DraftStatus.QUEUED), delay_seconds=600)
    assert "10 minutes" in reply
    assert "cancel send" in reply.lower()
    assert "a@example.com" in reply


def test_format_cancel_send_reply() -> None:
    reply = format_cancel_send_reply(_draft(status=DraftStatus.APPROVED))
    assert "Cancelled" in reply
    assert "a@example.com" in reply


def test_format_send_not_found_reply() -> None:
    assert "couldn't find" in format_send_not_found_reply("bob").lower()


def test_format_send_not_approved_reply() -> None:
    reply = format_send_not_approved_reply(_draft())
    assert "approval" in reply.lower()
    assert "a@example.com" in reply


@pytest.mark.parametrize(
    "text",
    [
        "Delete all my emails.",
        "Yes, send it.",
        "Approve it.",
        "Okay, delete them.",
        "Please forward the email to Bob",
        "Can you send an email to Bob?",
        "Clear my inbox",
        "Delete the draft to Bob",
    ],
)
def test_unsupported_email_actions_are_caught(text: str) -> None:
    assert email_intent.match_unsupported_email_action(text)


@pytest.mark.parametrize(
    "text",
    [
        "How do I send an email?",
        "What is email?",
        "Tell me a joke",
        "Send my regards",
        "I sent an email yesterday",
        "Drop an email to test at example dot com saying hello.",
    ],
)
def test_questions_and_other_turns_are_left_alone(text: str) -> None:
    assert not email_intent.match_unsupported_email_action(text)
