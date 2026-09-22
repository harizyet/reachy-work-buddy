"""Single-owner bootstrap and salted password verification; no signup API."""

import asyncio
import hashlib
import secrets
from typing import Protocol

from psycopg_pool import AsyncConnectionPool

_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _ITERATIONS
    ).hex()
    return f"{_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    rounds, salt, expected = encoded.split("$")
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(rounds)
    ).hex()
    return secrets.compare_digest(actual, expected)


class UserStore(Protocol):
    async def owner(self) -> str | None: ...
    async def bootstrap(self, username: str, password: str) -> None: ...
    async def authenticate(self, username: str, password: str) -> bool: ...


class InMemoryUserStore:
    def __init__(self):
        self._username = None
        self._hash = None

    async def owner(self) -> str | None:
        return self._username

    async def bootstrap(self, username: str, password: str) -> None:
        if self._username is None:
            encoded = await asyncio.to_thread(hash_password, password)
            if self._username is None:
                self._username, self._hash = username, encoded

    async def authenticate(self, username: str, password: str) -> bool:
        if self._hash is None:
            return False
        valid = await asyncio.to_thread(verify_password, password, self._hash)
        return valid and secrets.compare_digest(
            username.encode(), self._username.encode()
        )


class PostgresUserStore:
    def __init__(self, pool):
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str):
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        async with pool.connection() as conn:
            await conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY CHECK (id = 'owner'), username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        return cls(pool)

    async def close(self):
        await self._pool.close()

    async def owner(self) -> str | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT username FROM users WHERE id = 'owner'")
            row = await cur.fetchone()
            return row[0] if row else None

    async def bootstrap(self, username: str, password: str) -> None:
        if await self.owner() is not None:
            return
        encoded = await asyncio.to_thread(hash_password, password)
        async with self._pool.connection() as conn:
            await conn.execute(
                """INSERT INTO users (id, username, password_hash)
                VALUES ('owner', %s, %s) ON CONFLICT DO NOTHING""",
                (username, encoded),
            )

    async def authenticate(self, username: str, password: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT username, password_hash FROM users WHERE id = 'owner'"
            )
            row = await cur.fetchone()
        if row is None:
            return False
        valid = await asyncio.to_thread(verify_password, password, row[1])
        return valid and secrets.compare_digest(username.encode(), row[0].encode())
