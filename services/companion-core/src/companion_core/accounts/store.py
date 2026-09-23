"""A single locked owner row serializes grant changes, refresh and disconnect."""
from contextlib import asynccontextmanager

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from companion_core.secrets import Keyring, PostgresSecretStore
from shared.database import check_schema

FLOW_COLUMNS = ("state_hash", "owner", "binding_hash", "capability", "generation",
                "expires_at", "verifier_ref", "code_ref", "error", "returned")


class AccountTransaction:
    def __init__(self, conn, secrets, data, flows):
        self.conn, self.secrets, self.data, self.flows = conn, secrets, data, flows

    async def put(self, context, value, ref=None):
        return await self.secrets.put(self.conn, context, value, ref)

    async def resolve(self, context, ref):
        return await self.secrets.resolve(self.conn, context, ref)

    async def delete(self, context, ref):
        if ref:
            await self.secrets.delete(self.conn, context, ref)


class PostgresAccountRepository:
    def __init__(self, pool, secrets):
        self.pool, self.secrets = pool, secrets

    @classmethod
    async def connect(cls, dsn, *, keyring=None):
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        try:
            async with pool.connection() as conn:
                await check_schema(conn)
            return cls(pool, PostgresSecretStore(keyring or Keyring.from_file()))
        except BaseException:
            await pool.close()
            raise

    async def close(self):
        await self.pool.close()

    @asynccontextmanager
    async def transaction(self):
        async with self.pool.connection() as conn:
            await conn.execute("SET LOCAL lock_timeout = '10s'")
            cursor = await conn.execute("SELECT data FROM google_accounts WHERE owner='owner' FOR UPDATE")
            data = (await cursor.fetchone())[0]
            cursor = await conn.execute("SELECT " + ",".join(FLOW_COLUMNS) + " FROM google_oauth_states")
            flows = [dict(zip(FLOW_COLUMNS, row, strict=True)) for row in await cursor.fetchall()]
            tx = AccountTransaction(conn, self.secrets, data, flows)
            yield tx
            await conn.execute("UPDATE google_accounts SET data=%s WHERE owner='owner'", (Jsonb(tx.data),))
            await conn.execute("DELETE FROM google_oauth_states")
            for flow in tx.flows:
                await conn.execute(
                    "INSERT INTO google_oauth_states (" + ",".join(FLOW_COLUMNS) +
                    ") VALUES (" + ",".join(["%s"] * len(FLOW_COLUMNS)) + ")",
                    tuple(flow.get(key) for key in FLOW_COLUMNS),
                )

    async def claim_reminders(self, events):
        result = []
        async with self.pool.connection() as conn:
            await conn.execute("DELETE FROM google_reminder_delivery WHERE expires_at < now()")
            for event in events:
                if not event.id.startswith("google:"):
                    result.append(event)
                    continue
                key = event.id + "@" + str(event.start.timestamp())
                cursor = await conn.execute(
                    "INSERT INTO google_reminder_delivery VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING event_id",
                    (key, event.end),
                )
                if await cursor.fetchone():
                    result.append(event)
        return result
