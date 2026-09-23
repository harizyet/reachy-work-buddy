"""SMTP delivery; credentials resolve only inside core at dispatch time."""

from __future__ import annotations

import os

import aiosmtplib
import psycopg

from companion_core.email.models import EmailDraft
from companion_core.secrets import Keyring, PostgresSecretStore, SecretContext
from shared.database import check_schema


async def smtp_send(draft: EmailDraft) -> None:
    host = os.environ.get("SMTP_HOST", "localhost")
    port = int(os.environ.get("SMTP_PORT", "1025"))
    sender = os.environ.get("SMTP_FROM", "companion@reachy.local")
    message = f"From: {sender}\r\nTo: {draft.to}\r\nSubject: {draft.subject}\r\n\r\n{draft.body}\r\n"
    username = os.environ.get("SMTP_USERNAME") or None
    # Environment injection is an explicit bootstrap source, never copied to DB.
    password = os.environ.get("SMTP_PASSWORD") or None
    ref = os.environ.get("SMTP_SECRET_REF")
    if ref:
        secrets = PostgresSecretStore(Keyring.from_file())
        async with await psycopg.AsyncConnection.connect(
            os.environ["DATABASE_URL"], connect_timeout=10,
        ) as conn:
            await check_schema(conn)
            password = await secrets.resolve(
                conn, SecretContext("owner", "smtp", "password"), ref,
            )
    options = {}
    if username or password:
        if not username or password is None:
            raise ValueError("SMTP authentication requires both username and credential")
        # Authenticated SMTP must negotiate TLS before sending credentials.
        options.update(username=username, password=password, start_tls=True)
    await aiosmtplib.send(
        message, sender=sender, recipients=[draft.to], hostname=host, port=port,
        timeout=30, **options,
    )
