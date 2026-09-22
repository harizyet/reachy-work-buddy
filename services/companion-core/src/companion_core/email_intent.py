"""Placeholder intent detection for email — same honesty-about-scope as
calendar_intent.py/task_intent.py/memory_intent.py/rag_intent.py: prefix/
pattern matchers, not real NLU, and no real drafting/summarization either
(there's no LLM wired into this codebase yet) — "draft email to X about Y"
just stores Y verbatim as the body, the same way "remember that X" stores
X verbatim. Phase 14's exit criterion is about the approval *gate*
(email/workflow.py), not about the writing being sophisticated.
"""

from __future__ import annotations

import re

from companion_core.email.models import EmailDraft, EmailMessage

_INBOX_PHRASES = ("what's in my inbox", "whats in my inbox", "read my email", "check my inbox", "list emails")
_DRAFT_PATTERN = re.compile(r"^draft (?:an? )?email to (\S+) about (.+)$", re.IGNORECASE)
_APPROVE_PREFIXES = ("approve draft ", "approve the draft to ", "approve email to ")
_SEND_PREFIXES = ("send draft ", "send the draft to ", "send email to ")


def match_list_inbox(text: str) -> bool:
    return text.strip().lower() in _INBOX_PHRASES


def match_draft(text: str) -> tuple[str, str] | None:
    """Returns (to, body) if text matches "draft email to <address> about
    <content>", else None."""
    match = _DRAFT_PATTERN.match(text.strip())
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def _match_prefix(text: str, prefixes: tuple[str, ...]) -> str | None:
    lowered = text.strip().lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text.strip()[len(prefix) :].strip() or None
    return None


def match_approve(text: str) -> str | None:
    return _match_prefix(text, _APPROVE_PREFIXES)


def match_send(text: str) -> str | None:
    return _match_prefix(text, _SEND_PREFIXES)


def format_inbox_reply(messages: list[EmailMessage]) -> str:
    if not messages:
        return "Your inbox is empty."
    lines = "; ".join(f"'{m.subject}' from {m.sender}" for m in messages)
    return f"You have {len(messages)} email(s): {lines}."


def format_draft_reply(draft: EmailDraft) -> str:
    return (
        f"Drafted an email to {draft.to}: '{draft.subject}'. "
        f"It won't send until you approve it — say \"approve draft {draft.to}\" then "
        f'"send draft {draft.to}".'
    )


def format_approve_reply(draft: EmailDraft | None, query: str) -> str:
    if draft is None:
        return f"I couldn't find a pending draft matching '{query}'."
    return f"Approved the draft to {draft.to}: '{draft.subject}'. Say \"send draft {draft.to}\" to send it."


def find_draft_by_query(drafts: list[EmailDraft], query: str) -> EmailDraft | None:
    lowered = query.lower()
    return next((d for d in drafts if lowered in d.to.lower() or lowered in d.subject.lower()), None)


def format_send_success_reply(draft: EmailDraft) -> str:
    return f"Sent the email to {draft.to}: '{draft.subject}'."


def format_send_not_found_reply(query: str) -> str:
    return f"I couldn't find a draft matching '{query}'."


def format_send_not_approved_reply(draft: EmailDraft) -> str:
    return f"That draft to {draft.to} needs approval first — say \"approve draft {draft.to}\"."
