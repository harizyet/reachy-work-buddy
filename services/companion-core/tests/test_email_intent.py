from companion_core.email.models import DraftStatus, EmailDraft, EmailMessage
from companion_core.email_intent import (
    find_draft_by_query,
    format_approve_reply,
    format_draft_reply,
    format_inbox_reply,
    format_send_not_approved_reply,
    format_send_not_found_reply,
    format_send_success_reply,
    match_approve,
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


def test_format_send_success_reply() -> None:
    reply = format_send_success_reply(_draft(status=DraftStatus.SENT))
    assert "Sent" in reply
    assert "a@example.com" in reply


def test_format_send_not_found_reply() -> None:
    assert "couldn't find" in format_send_not_found_reply("bob").lower()


def test_format_send_not_approved_reply() -> None:
    reply = format_send_not_approved_reply(_draft())
    assert "approval" in reply.lower()
    assert "a@example.com" in reply
