"""The dedicated outbound sender (Phase 55, ADR 0039): one row of settings, with the credential held only in the SecretStore (ADR 0020).

External delivery is OFF until the owner enables it. The settings never carry the password: `secret_ref` is an opaque id that only core resolves, and nothing returns or logs the value.
A sender with a username must use STARTTLS; an unauthenticated relay (Mailpit in tests) may use `none`."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Literal, Protocol

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from companion_core.email.mime import AddressError, normalize_address
from companion_core.secrets import (
    Keyring,
    PostgresSecretStore,
    SecretContext,
    SecretStore,
)
from shared.database import check_schema, close_pool, open_pool

CONTEXT = SecretContext("owner", "mail-sender", "password")
GMAIL_HOST = "smtp.gmail.com"
_INVISIBLE = re.compile(r"[\s\u200b-\u200f\u2060\ufeff]+")


def clean_password(host: str, password: str | None) -> str | None:
    """A Google app password is 16 letters that the Google page shows in groups with spaces; pasted, it can carry ordinary, non-breaking or zero-width spaces, and Google rejects those. For
    Gmail every whitespace and invisible character is removed (an app password has none). Other servers' passwords are kept exactly as typed."""
    if password and host.strip().lower() == GMAIL_HOST:
        return _INVISIBLE.sub("", password)
    return password


class SenderSettings(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "none"] = "starttls"
    from_address: str = ""
    username: str = ""
    secret_ref: str | None = None
    verified_at: datetime | None = None
    verified_ok: bool | None = None
    verified_detail: str = ""
    updated_at: datetime | None = None

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_address)

    def view(self) -> dict:
        """What clients may see: no reference, no credential, only whether one is stored."""
        return {
            "enabled": self.enabled, "configured": self.configured, "host": self.host, "port": self.port, "security": self.security,
            "from_address": self.from_address, "username": self.username, "has_credential": self.secret_ref is not None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None, "verified_ok": self.verified_ok, "verified_detail": self.verified_detail,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SenderConfigError(ValueError):
    pass


def validate(settings: SenderSettings, *, has_password: bool) -> None:
    if not settings.host or any(c.isspace() for c in settings.host) or len(settings.host) > 253:
        raise SenderConfigError("a valid SMTP host is required")
    try:
        normalize_address(settings.from_address)
    except AddressError as exc:
        raise SenderConfigError(f"the sender address is not valid: {exc}") from None
    if settings.username or has_password:
        if not settings.username or not has_password:
            raise SenderConfigError("authentication needs both a username and a credential")
        if settings.security != "starttls":
            raise SenderConfigError("an authenticated sender must use STARTTLS")  # credentials never cross an unencrypted connection
        if settings.host.lower() == GMAIL_HOST and settings.username.strip().lower() != settings.from_address.strip().lower():
            raise SenderConfigError("a Gmail sender must send as the account it signs in with")  # Gmail would rewrite From; the identity must be the account


class MailSenderStore(Protocol):
    async def get(self) -> SenderSettings: ...

    async def password(self) -> str | None: ...

    async def save(self, settings: SenderSettings, *, password: str | None, clear_password: bool = False) -> SenderSettings: ...

    async def set_enabled(self, enabled: bool) -> SenderSettings: ...

    async def record_verification(self, ok: bool, detail: str) -> SenderSettings: ...

    async def disconnect(self) -> SenderSettings: ...


def _merged(current: SenderSettings, new: SenderSettings, *, password: str | None, clear: bool) -> tuple[SenderSettings, bool]:
    has_password = (current.secret_ref is not None and not clear) or bool(password)
    merged = new.model_copy(update={"secret_ref": current.secret_ref, "enabled": current.enabled, "updated_at": datetime.now(UTC)})
    # Any change to where or as whom we send invalidates the last verification and switches sending off: the owner re-verifies and re-enables on purpose.
    changed = (current.host, current.port, current.security, current.from_address.lower(), current.username) != (new.host, new.port, new.security, new.from_address.lower(), new.username) or bool(password) or clear
    if changed:
        merged = merged.model_copy(update={"enabled": False, "verified_at": None, "verified_ok": None, "verified_detail": ""})
    return merged, has_password


class InMemoryMailSenderStore:
    """Test double. The credential lives only in this object's memory."""

    def __init__(self) -> None:
        self._settings = SenderSettings()
        self._password: str | None = None

    async def get(self) -> SenderSettings:
        return self._settings

    async def password(self) -> str | None:
        return self._password

    async def save(self, settings: SenderSettings, *, password: str | None, clear_password: bool = False) -> SenderSettings:
        password = clean_password(settings.host, password)
        merged, has_password = _merged(self._settings, settings, password=password, clear=clear_password)
        validate(merged, has_password=has_password)
        if clear_password:
            self._password = None
        if password:
            self._password = password
        self._settings = merged.model_copy(update={"secret_ref": "memory" if self._password else None})
        return self._settings

    async def set_enabled(self, enabled: bool) -> SenderSettings:
        if enabled and not (self._settings.configured and self._settings.verified_ok):
            raise SenderConfigError("verify the connection before enabling sending")
        self._settings = self._settings.model_copy(update={"enabled": enabled, "updated_at": datetime.now(UTC)})
        return self._settings

    async def record_verification(self, ok: bool, detail: str) -> SenderSettings:
        self._settings = self._settings.model_copy(update={"verified_at": datetime.now(UTC), "verified_ok": ok, "verified_detail": detail[:300], "enabled": self._settings.enabled and ok})
        return self._settings

    async def disconnect(self) -> SenderSettings:
        self._settings, self._password = SenderSettings(updated_at=datetime.now(UTC)), None
        return self._settings


_COLUMNS = "enabled, host, port, security, from_address, username, secret_ref, verified_at, verified_ok, verified_detail, updated_at"


def _row(row: tuple) -> SenderSettings:
    return SenderSettings(enabled=row[0], host=row[1], port=row[2], security=row[3], from_address=row[4], username=row[5], secret_ref=row[6],
                          verified_at=row[7], verified_ok=row[8], verified_detail=row[9], updated_at=row[10])


class PostgresMailSenderStore:
    """Row `id = 1` of `mail_sender`. The credential is written and read only through the SecretStore, in the same transaction as the row that references it."""

    def __init__(self, pool: AsyncConnectionPool, secrets: SecretStore) -> None:
        self._pool, self._secrets = pool, secrets

    @classmethod
    async def connect(cls, dsn: str, *, keyring: Keyring | None = None) -> PostgresMailSenderStore:
        pool = await open_pool(dsn)
        async with pool.connection() as conn:
            await check_schema(conn)
        return cls(pool, PostgresSecretStore(keyring or Keyring.from_file()))

    async def close(self) -> None:
        await close_pool(self._pool)

    async def _locked(self, conn) -> SenderSettings:
        await conn.execute("INSERT INTO mail_sender (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        cur = await conn.execute(f"SELECT {_COLUMNS} FROM mail_sender WHERE id = 1 FOR UPDATE")
        return _row(await cur.fetchone())

    async def get(self) -> SenderSettings:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM mail_sender WHERE id = 1")
            row = await cur.fetchone()
            return _row(row) if row else SenderSettings()

    async def password(self) -> str | None:
        async with self._pool.connection() as conn:
            current = await self._locked(conn)
            return await self._secrets.resolve(conn, CONTEXT, current.secret_ref) if current.secret_ref else None

    async def _write(self, conn, s: SenderSettings) -> SenderSettings:
        await conn.execute(
            "UPDATE mail_sender SET enabled=%s, host=%s, port=%s, security=%s, from_address=%s, username=%s, secret_ref=%s, verified_at=%s, verified_ok=%s, verified_detail=%s, updated_at=%s WHERE id = 1",
            (s.enabled, s.host, s.port, s.security, s.from_address, s.username, s.secret_ref, s.verified_at, s.verified_ok, s.verified_detail, s.updated_at))
        return s

    async def save(self, settings: SenderSettings, *, password: str | None, clear_password: bool = False) -> SenderSettings:
        password = clean_password(settings.host, password)
        async with self._pool.connection() as conn, conn.transaction():
            current = await self._locked(conn)
            merged, has_password = _merged(current, settings, password=password, clear=clear_password)
            validate(merged, has_password=has_password)
            ref = current.secret_ref
            if clear_password and ref:
                await self._secrets.delete(conn, CONTEXT, ref)
                ref = None
            if password:
                ref = await self._secrets.put(conn, CONTEXT, password, ref)  # rotation reuses the reference: the old value is replaced in place
            return await self._write(conn, merged.model_copy(update={"secret_ref": ref}))

    async def set_enabled(self, enabled: bool) -> SenderSettings:
        async with self._pool.connection() as conn, conn.transaction():
            current = await self._locked(conn)
            if enabled and not (current.configured and current.verified_ok):
                raise SenderConfigError("verify the connection before enabling sending")
            return await self._write(conn, current.model_copy(update={"enabled": enabled, "updated_at": datetime.now(UTC)}))

    async def record_verification(self, ok: bool, detail: str) -> SenderSettings:
        async with self._pool.connection() as conn, conn.transaction():
            current = await self._locked(conn)
            return await self._write(conn, current.model_copy(update={"verified_at": datetime.now(UTC), "verified_ok": ok, "verified_detail": detail[:300], "enabled": current.enabled and ok}))

    async def disconnect(self) -> SenderSettings:
        async with self._pool.connection() as conn, conn.transaction():
            current = await self._locked(conn)
            if current.secret_ref:
                await self._secrets.delete(conn, CONTEXT, current.secret_ref)
            return await self._write(conn, SenderSettings(updated_at=datetime.now(UTC)))


def env_settings() -> SenderSettings | None:
    """The deployment's original SMTP environment (Mailpit in simulation). Only a plain text draft may use it; a meeting package never does."""
    host = os.environ.get("SMTP_HOST", "localhost")
    return SenderSettings(enabled=True, host=host, port=int(os.environ.get("SMTP_PORT", "1025")), security="starttls" if os.environ.get("SMTP_USERNAME") else "none",
                          from_address=os.environ.get("SMTP_FROM", "companion@reachy.local"), username=os.environ.get("SMTP_USERNAME", ""))
