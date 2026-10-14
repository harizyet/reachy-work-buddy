"""Address validation and MIME message construction (Phase 55, ADR 0039).

Every outgoing message is built here with the stdlib `email` package under `policy.SMTP`, which refuses a newline inside a header value, so a recipient or subject can never add headers.
Addresses are validated before they are stored and again before sending: lower-case, one plain `local@domain`, no display name, no quoting, no whitespace, no control characters."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.message import EmailMessage as MimeMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import format_datetime, make_msgid

from companion_core.email.models import EmailDraft, Recipients

MAX_RECIPIENTS = 20
MAX_SUBJECT = 200
MAX_BODY = 60_000
_LOCAL = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class AddressError(ValueError):
    pass


def normalize_address(raw: str) -> str:
    """Lower-case a plain address or raise AddressError. Display names, comments, quoted locals, whitespace and control characters are all refused."""
    value = (raw or "").strip().lower()
    if not value or len(value) > 254 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise AddressError(f"not a valid email address: {raw[:60]!r}")
    local, sep, domain = value.rpartition("@")
    if not sep or not local or len(local) > 64 or not _LOCAL.match(local):
        raise AddressError(f"not a valid email address: {raw[:60]!r}")
    labels = domain.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels) or labels[-1].isdigit():
        raise AddressError(f"not a valid email address: {raw[:60]!r}")
    return value


def clean_recipients(to: list[str], cc: list[str] | None = None, bcc: list[str] | None = None, *, require_to: bool = True) -> Recipients:
    """Validate, lower-case and de-duplicate across the three lists (an address appears once, in the first list that names it). At least one To is required."""
    seen: set[str] = set()
    lists: list[list[str]] = []
    for group in (to, cc or [], bcc or []):
        out: list[str] = []
        for raw in group:
            address = normalize_address(raw)
            if address not in seen:
                seen.add(address)
                out.append(address)
        lists.append(out)
    if require_to and not lists[0]:
        raise AddressError("at least one To recipient is required")
    if len(seen) > MAX_RECIPIENTS:
        raise AddressError(f"at most {MAX_RECIPIENTS} recipients are allowed in one message")
    return Recipients(to=lists[0], cc=lists[1], bcc=lists[2])


def clean_subject(subject: str) -> str:
    value = " ".join((subject or "").split())
    if not value:
        raise AddressError("the subject cannot be empty")
    if len(value) > MAX_SUBJECT:
        raise AddressError(f"the subject is limited to {MAX_SUBJECT} characters")
    return value


def clean_body(body: str) -> str:
    value = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not value.strip():
        raise AddressError("the message body cannot be empty")
    if len(value) > MAX_BODY:
        raise AddressError(f"the message body is limited to {MAX_BODY} characters")
    return value


def build_message(draft: EmailDraft, *, sender: str, attachments: list[tuple[str, str, bytes]] | None = None) -> MimeMessage:
    """The message exactly as it will go out. Bcc recipients are not in any header: they are only SMTP envelope recipients (see `envelope_recipients`)."""
    recipients = draft.recipients or Recipients(to=[normalize_address(draft.to)])
    message = MimeMessage(policy=SMTP_POLICY)
    message["From"] = normalize_address(sender)
    message["To"] = ", ".join(recipients.to)
    if recipients.cc:
        message["Cc"] = ", ".join(recipients.cc)
    message["Subject"] = clean_subject(draft.subject)
    message["Date"] = format_datetime(draft.approved_at or datetime.now(UTC))
    message["Message-ID"] = draft.message_id or make_msgid(domain=normalize_address(sender).rpartition("@")[2])
    if draft.in_reply_to:
        message["In-Reply-To"] = " ".join(draft.in_reply_to.split())
    message.set_content(clean_body(draft.body), charset="utf-8", cte="quoted-printable")
    for name, content_type, data in attachments or []:
        maintype, _, subtype = content_type.partition("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return message


def envelope_recipients(draft: EmailDraft) -> list[str]:
    recipients = draft.recipients or Recipients(to=[normalize_address(draft.to)])
    return recipients.everyone()
