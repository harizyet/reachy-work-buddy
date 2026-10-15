"""SMTP delivery; credentials resolve only inside core at dispatch time (ADR 0020, ADR 0039).

`MailSender` is the one sender the dispatch loop calls. It builds the message with `email/mime.py`, enforces the configured identity and TLS, and reports what happened with a typed
outcome so the loop never has to guess whether a failure may have delivered the message:

* `SendRefused`   nothing was delivered and retrying cannot help (bad credentials, recipients or sender refused, a 5xx answer, disabled sender, changed identity);
* `SendTransient` nothing was delivered and a later attempt may work (could not connect, a 4xx answer before the message was accepted);
* `SendUnknown`   the server may have accepted the message (a timeout or a dropped connection after the message was sent): never retried automatically.

A draft of kind `meeting_minutes` may only use the owner-configured sender, never the deployment's environment fallback."""

from __future__ import annotations

import logging
import os
import ssl
from collections.abc import Awaitable, Callable

import aiosmtplib
import psycopg

from companion_core.email.mime import (
    AddressError,
    build_message,
    envelope_recipients,
    normalize_address,
)
from companion_core.email.models import (
    MEETING_MINUTES_KIND,
    SENDER_TEST_KIND,
    EmailDraft,
)
from companion_core.email.sender_config import (
    GMAIL_HOST,
    MailSenderStore,
    SenderSettings,
    env_settings,
)
from companion_core.secrets import Keyring, PostgresSecretStore, SecretContext
from shared.database import check_schema

log = logging.getLogger(__name__)
TIMEOUT_SECONDS = 30


class SendError(Exception):
    """Base for the typed outcomes. `str(error)` is safe to store and show: it never contains a credential."""


class SendRefused(SendError):
    pass


class SendTransient(SendError):
    pass


class SendUnknown(SendError):
    pass


def _safe(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text}"[:200]


class MailSender:
    """Callable as the dispatch loop's `SendFn`. `tls_context` is for tests only (a self-signed Mailpit certificate); production always verifies."""

    def __init__(self, store: MailSenderStore | None, *, allow_env: bool = True, tls_context: ssl.SSLContext | None = None, timeout: float = TIMEOUT_SECONDS) -> None:
        self.store, self.allow_env, self.tls_context, self.timeout = store, allow_env, tls_context, timeout

    async def _settings(self, draft: EmailDraft | None) -> tuple[SenderSettings, str | None]:
        configured = await self.store.get() if self.store is not None else SenderSettings()
        if configured.configured:
            return configured, await self.store.password()
        if draft is not None and draft.kind in (MEETING_MINUTES_KIND, SENDER_TEST_KIND):
            raise SendRefused("no outbound sender is configured")  # a meeting package or a sender test never falls back to the deployment environment
        if not self.allow_env:
            raise SendRefused("no outbound sender is configured")
        env = env_settings()
        return env, await _env_password()

    def _check(self, settings: SenderSettings, password: str | None, draft: EmailDraft | None) -> str:
        if not settings.enabled:
            raise SendRefused("external sending is turned off")
        try:
            sender = normalize_address(settings.from_address)
        except AddressError as exc:
            raise SendRefused(str(exc)) from None
        if settings.username or password:
            if not settings.username or password is None:
                raise SendRefused("the sender's credential is missing")
            if settings.security != "starttls":
                raise SendRefused("authenticated sending requires STARTTLS")
        if settings.host.lower() == GMAIL_HOST and settings.username and settings.username.strip().lower() != sender:
            raise SendRefused("the sender identity does not match the account")
        if draft is not None and draft.sender and draft.sender != sender:
            raise SendRefused("the sender identity changed since this message was approved")
        return sender

    async def _connect(self, settings: SenderSettings, password: str | None) -> aiosmtplib.SMTP:
        # start_tls=False: the library would otherwise upgrade by itself with its own defaults. TLS is negotiated below, explicitly, with our context, and only for a sender configured for it.
        client = aiosmtplib.SMTP(hostname=settings.host, port=settings.port, timeout=self.timeout, start_tls=False, use_tls=False)
        try:
            await client.connect()
            if settings.security == "starttls":
                await client.starttls(tls_context=self.tls_context or ssl.create_default_context())
            if settings.username and password is not None:
                await client.ehlo()  # after TLS the server's capabilities (including AUTH) are asked for again; the library refreshes them only lazily
                await self._sign_in(client, settings.username, password)
        except aiosmtplib.SMTPAuthenticationError as exc:
            await _close(client)
            hint = (
                " Google rejected the username or password. Use an app password made for this account (Google Account > Security > App passwords; the account needs 2-Step Verification), not the account's own password."
                if settings.host.strip().lower() == GMAIL_HOST else ""
            )
            raise SendRefused(f"authentication failed ({exc.code}).{hint}" if hint else f"authentication failed: {exc.code} {_one_line(exc.message)}") from None
        except SendRefused:
            await _close(client)
            raise
        except (aiosmtplib.SMTPException, OSError, TimeoutError, ssl.SSLError) as exc:
            await _close(client)
            raise SendTransient(f"could not connect or authenticate: {_safe(exc)}") from None
        return client

    @staticmethod
    async def _sign_in(client: aiosmtplib.SMTP, username: str, password: str) -> None:
        """AUTH PLAIN, else AUTH LOGIN, chosen from what the server advertises after TLS. The library's generic `login()` tries other mechanisms first (CRAM-MD5 and others), and Gmail answers
        an attempt it does not support by dropping the connection ("Connection lost") instead of refusing it, so a correct credential could never get through."""
        offered = {m.upper() for m in str(client.esmtp_extensions.get("auth", "")).split()}
        if "PLAIN" in offered:
            await client.auth_plain(username, password)
        elif "LOGIN" in offered:
            await client.auth_login(username, password)
        else:
            raise SendRefused("the mail server does not offer password sign-in (PLAIN or LOGIN)")

    async def __call__(self, draft: EmailDraft) -> str | None:
        settings, password = await self._settings(draft)
        sender = self._check(settings, password, draft)
        try:
            message = build_message(draft, sender=sender, attachments=list(draft.attachment_blobs))
            envelope = envelope_recipients(draft)
        except (AddressError, ValueError) as exc:
            raise SendRefused(f"the message could not be built: {exc}") from None
        client = await self._connect(settings, password)
        try:
            _errors, response = await client.send_message(message, sender=sender, recipients=envelope)
        except (aiosmtplib.SMTPRecipientsRefused, aiosmtplib.SMTPSenderRefused) as exc:
            raise SendRefused(f"the server refused the sender or recipients: {_safe(exc)}") from None
        except aiosmtplib.SMTPResponseException as exc:
            # A final answer to the message itself: 5xx is a refusal, 4xx means the server did not take it.
            if exc.code >= 500:
                raise SendRefused(f"the server rejected the message: {exc.code} {_one_line(exc.message)}") from None
            raise SendTransient(f"the server deferred the message: {exc.code} {_one_line(exc.message)}") from None
        except (aiosmtplib.SMTPException, OSError, TimeoutError, ssl.SSLError) as exc:
            # No final answer: the server may have the message already.
            raise SendUnknown(f"no final answer after sending: {_safe(exc)}") from None
        finally:
            await _close(client)
        return _one_line(getattr(response, "message", response))  # aiosmtplib returns the server's line as a string (older versions: an object)

    async def verify(self) -> dict:
        """Connect, negotiate TLS and authenticate, then quit: **no message is sent** and no recipient is named. Never raises."""
        try:
            settings, password = await self._settings(None)
            if not settings.configured:
                return {"ok": False, "stage": "settings", "detail": "no sender is configured"}
            if settings.username or password:
                if not settings.username or password is None:
                    return {"ok": False, "stage": "settings", "detail": "the sender's credential is missing"}
                if settings.security != "starttls":
                    return {"ok": False, "stage": "settings", "detail": "authenticated sending requires STARTTLS"}
            client = await self._connect(settings, password)
            try:
                await client.noop()
            finally:
                await _close(client)
            return {"ok": True, "stage": "authenticated" if settings.username else "connected", "detail": f"connected to {settings.host}:{settings.port}" + (" and signed in" if settings.username else "")}
        except SendError as exc:
            return {"ok": False, "stage": "connect", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a verification must report, not crash the route
            return {"ok": False, "stage": "unexpected", "detail": _safe(exc)}


def _one_line(value: object) -> str:
    return " ".join(str(value).split())[:160]


async def _close(client: aiosmtplib.SMTP) -> None:
    try:
        if client.is_connected:
            await client.quit()
    except Exception:  # noqa: BLE001 - closing is best effort
        try:
            client.close()
        except Exception:
            log.debug("smtp close failed", exc_info=True)


async def _env_password() -> str | None:
    """The deployment's original bootstrap sources: an explicit environment password, or a SecretStore reference (never persisted by us)."""
    ref = os.environ.get("SMTP_SECRET_REF")
    if ref:
        secrets = PostgresSecretStore(Keyring.from_file())
        async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"], connect_timeout=10) as conn:
            await check_schema(conn)
            return await secrets.resolve(conn, SecretContext("owner", "smtp", "password"), ref)
    return os.environ.get("SMTP_PASSWORD") or None


SendFn = Callable[[EmailDraft], Awaitable[str | None]]


async def smtp_send(draft: EmailDraft) -> str | None:
    """The deployment-environment sender (Mailpit in simulation, or a relay named by SMTP_*), for plain text drafts only."""
    return await MailSender(None)(draft)
