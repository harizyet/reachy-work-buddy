"""Core-owned authenticated credential storage. No HTTP decrypt surface."""

import base64
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Credential unavailable; check the encryption key file and restore procedure")


@dataclass(frozen=True)
class SecretContext:
    owner: str
    provider: str
    purpose: str


@dataclass(frozen=True)
class Keyring:
    active: str
    keys: dict[str, bytes] = field(repr=False)

    @classmethod
    def from_file(cls, path: str | None = None):
        try:
            target = Path(path or os.environ["SECRET_KEY_FILE"])
            # Read the same descriptor whose permissions were checked.
            with target.open("rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise ValueError("permissions")
                data = json.load(stream)
            if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
                raise TypeError("format")
            keys = {
                name: base64.b64decode(value, validate=True)
                for name, value in data["keys"].items()
            }
            if (
                not keys or data["active"] not in keys
                or any(not isinstance(name, str) or not name or len(value) != 32
                       for name, value in keys.items())
            ):
                raise ValueError("keys")
            return cls(data["active"], keys)
        except (OSError, KeyError, ValueError, TypeError):
            raise SecretUnavailable() from None

    @staticmethod
    def aad(ref: str, ctx: SecretContext, key_id: str, version: int) -> bytes:
        return json.dumps(
            [version, ref, ctx.owner, ctx.provider, ctx.purpose, key_id],
            separators=(",", ":"), ensure_ascii=True,
        ).encode()

    def encrypt(self, ref: str, ctx: SecretContext, value: str) -> dict:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.keys[self.active]).encrypt(
            nonce, value.encode(), self.aad(ref, ctx, self.active, 1),
        )
        return {"key_id": self.active, "version": 1, "nonce": nonce, "ciphertext": ciphertext}

    def decrypt(self, ref: str, ctx: SecretContext, record) -> str:
        try:
            if record["version"] != 1:
                raise ValueError("version")
            return AESGCM(self.keys[record["key_id"]]).decrypt(
                bytes(record["nonce"]), bytes(record["ciphertext"]),
                self.aad(ref, ctx, record["key_id"], record["version"]),
            ).decode()
        except (InvalidTag, KeyError, ValueError, TypeError):
            raise SecretUnavailable() from None


class SecretStore(Protocol):
    async def put(self, conn, ctx: SecretContext, value: str, ref: str | None = None) -> str: ...
    async def resolve(self, conn, ctx: SecretContext, ref: str) -> str: ...
    async def delete(self, conn, ctx: SecretContext, ref: str) -> None: ...
    async def rotate_batch(self, conn, limit: int = 100) -> int: ...


class PostgresSecretStore:
    """Caller supplies a transaction so config/reference changes commit together."""

    def __init__(self, keyring: Keyring):
        self.keyring = keyring

    async def put(self, conn, ctx: SecretContext, value: str, ref: str | None = None) -> str:
        if ref is not None:
            # Lock and authenticate before replacing an existing credential.
            await self.resolve(conn, ctx, ref)
        ref = ref or str(uuid4())
        record = self.keyring.encrypt(ref, ctx, value)
        cursor = await conn.execute(
            """INSERT INTO secrets (id, owner, provider, purpose, key_id, version, nonce, ciphertext)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET key_id=EXCLUDED.key_id, version=EXCLUDED.version,
            nonce=EXCLUDED.nonce, ciphertext=EXCLUDED.ciphertext, updated_at=now()
            WHERE secrets.owner=EXCLUDED.owner AND secrets.provider=EXCLUDED.provider
            AND secrets.purpose=EXCLUDED.purpose RETURNING id""",
            (ref, ctx.owner, ctx.provider, ctx.purpose, record["key_id"],
             record["version"], record["nonce"], record["ciphertext"]),
        )
        if await cursor.fetchone() is None:
            raise SecretUnavailable()
        return ref

    async def resolve(self, conn, ctx: SecretContext, ref: str) -> str:
        cursor = await conn.execute(
            """SELECT key_id, version, nonce, ciphertext FROM secrets
            WHERE id=%s AND owner=%s AND provider=%s AND purpose=%s FOR UPDATE""",
            (ref, ctx.owner, ctx.provider, ctx.purpose),
        )
        row = await cursor.fetchone()
        if row is None:
            raise SecretUnavailable()
        return self.keyring.decrypt(
            ref, ctx, dict(zip(("key_id", "version", "nonce", "ciphertext"), row, strict=True)),
        )

    async def delete(self, conn, ctx: SecretContext, ref: str) -> None:
        await conn.execute(
            "DELETE FROM secrets WHERE id=%s AND owner=%s AND provider=%s AND purpose=%s",
            (ref, ctx.owner, ctx.provider, ctx.purpose),
        )

    async def rotate_batch(self, conn, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("Batch size must be between 1 and 1000")
        cursor = await conn.execute(
            """SELECT id, owner, provider, purpose, key_id, version, nonce, ciphertext
            FROM secrets WHERE key_id <> %s ORDER BY id LIMIT %s FOR UPDATE""",
            (self.keyring.active, limit),
        )
        rows = await cursor.fetchall()
        for ref, owner, provider, purpose, key_id, version, nonce, ciphertext in rows:
            ctx = SecretContext(owner, provider, purpose)
            value = self.keyring.decrypt(ref, ctx, {
                "key_id": key_id, "version": version, "nonce": nonce, "ciphertext": ciphertext,
            })
            await self.put(conn, ctx, value, ref)
        return len(rows)
