"""Saved recipient groups (Phase 55): named lists of addresses the owner approved once. A group is only a shortcut for filling the recipient list of ONE message; choosing it never sends anything,
and the complete expanded list is shown for review every time. Nothing is ever created automatically (no group from attendees or speakers)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from companion_core.email.mime import AddressError, normalize_address
from shared.database import check_schema, close_pool, open_pool

MAX_GROUPS = 50
MAX_MEMBERS = 20


class Group(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    addresses: list[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GroupError(ValueError):
    pass


def clean(name: str, addresses: list[str]) -> tuple[str, list[str]]:
    name = " ".join((name or "").split())
    if not name or len(name) > 60:
        raise GroupError("a group needs a name of up to 60 characters")
    try:
        cleaned = list(dict.fromkeys(normalize_address(a) for a in addresses))
    except AddressError as exc:
        raise GroupError(str(exc)) from None
    if not cleaned or len(cleaned) > MAX_MEMBERS:
        raise GroupError(f"a group holds 1 to {MAX_MEMBERS} addresses")
    return name, cleaned


class GroupStore(Protocol):
    async def list(self) -> list[Group]: ...

    async def get(self, group_id: str) -> Group | None: ...

    async def save(self, name: str, addresses: list[str], group_id: str | None = None) -> Group | None: ...

    async def delete(self, group_id: str) -> bool: ...


class InMemoryGroupStore:
    def __init__(self) -> None:
        self._groups: dict[str, Group] = {}

    async def list(self) -> list[Group]:
        return sorted(self._groups.values(), key=lambda g: g.name.lower())

    async def get(self, group_id: str) -> Group | None:
        return self._groups.get(group_id)

    async def save(self, name: str, addresses: list[str], group_id: str | None = None) -> Group | None:
        name, cleaned = clean(name, addresses)
        if any(g.name.lower() == name.lower() and g.id != group_id for g in self._groups.values()):
            raise GroupError("a group with that name already exists")
        if group_id is None:
            if len(self._groups) >= MAX_GROUPS:
                raise GroupError("too many groups")
            group = Group(name=name, addresses=cleaned)
        else:
            current = self._groups.get(group_id)
            if current is None:
                return None
            group = current.model_copy(update={"name": name, "addresses": cleaned, "updated_at": datetime.now(UTC)})
        self._groups[group.id] = group
        return group

    async def delete(self, group_id: str) -> bool:
        return self._groups.pop(group_id, None) is not None


class PostgresGroupStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresGroupStore:
        pool = await open_pool(dsn)
        async with pool.connection() as conn:
            await check_schema(conn)
        return cls(pool)

    async def close(self) -> None:
        await close_pool(self._pool)

    @staticmethod
    def _g(row) -> Group:
        return Group(id=row[0], name=row[1], addresses=list(row[2]), created_at=row[3], updated_at=row[4])

    async def list(self) -> list[Group]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT id, name, addresses, created_at, updated_at FROM meeting_recipient_groups ORDER BY lower(name)")
            return [self._g(r) for r in await cur.fetchall()]

    async def get(self, group_id: str) -> Group | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT id, name, addresses, created_at, updated_at FROM meeting_recipient_groups WHERE id = %s", (group_id,))
            row = await cur.fetchone()
            return self._g(row) if row else None

    async def save(self, name: str, addresses: list[str], group_id: str | None = None) -> Group | None:
        name, cleaned = clean(name, addresses)
        now = datetime.now(UTC)
        async with self._pool.connection() as conn:
            clash = await (await conn.execute("SELECT id FROM meeting_recipient_groups WHERE lower(name) = lower(%s) AND id IS DISTINCT FROM %s", (name, group_id))).fetchone()
            if clash:
                raise GroupError("a group with that name already exists")
            if group_id is None:
                if (await (await conn.execute("SELECT count(*) FROM meeting_recipient_groups")).fetchone())[0] >= MAX_GROUPS:
                    raise GroupError("too many groups")
                group = Group(name=name, addresses=cleaned, created_at=now, updated_at=now)
                await conn.execute("INSERT INTO meeting_recipient_groups (id, name, addresses, created_at, updated_at) VALUES (%s,%s,%s,%s,%s)", (group.id, name, Json(cleaned), now, now))
                return group
            cur = await conn.execute(
                "UPDATE meeting_recipient_groups SET name = %s, addresses = %s, updated_at = %s WHERE id = %s RETURNING id, name, addresses, created_at, updated_at",
                (name, Json(cleaned), now, group_id))
            row = await cur.fetchone()
            return self._g(row) if row else None

    async def delete(self, group_id: str) -> bool:
        async with self._pool.connection() as conn:
            return (await conn.execute("DELETE FROM meeting_recipient_groups WHERE id = %s", (group_id,))).rowcount > 0
