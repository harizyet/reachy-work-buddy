"""Real SMTP send. No cloud email API key was available, so this speaks
plain SMTP directly (same local-infrastructure-over-cloud-key pattern as
Phase 8's local STT/TTS) — in the homelab compose stack this points at a
local Mailpit container (a real SMTP server, real protocol handshake, but
nothing leaves the machine), not a real mailbox. `smtp_send` is injectable
wherever it's used (see workflow.py's SendFn) specifically so tests never
open a real network connection.
"""

from __future__ import annotations

import os

import aiosmtplib

from companion_core.email.models import EmailDraft


async def smtp_send(draft: EmailDraft) -> None:
    host = os.environ.get("SMTP_HOST", "localhost")
    port = int(os.environ.get("SMTP_PORT", "1025"))
    sender = os.environ.get("SMTP_FROM", "companion@reachy.local")
    message = f"From: {sender}\r\nTo: {draft.to}\r\nSubject: {draft.subject}\r\n\r\n{draft.body}\r\n"
    await aiosmtplib.send(message, sender=sender, recipients=[draft.to], hostname=host, port=port)
