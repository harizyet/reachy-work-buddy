"""Run once with old app writers stopped; never invoked by app startup."""

import argparse
import asyncio
import os
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from companion_core.secrets import Keyring, PostgresSecretStore, SecretContext
from shared.database import SCHEMA_REVISION, check_schema

LOCK_ID = 230022001


def upgrade(dsn: str, keys: Keyring, *, adopt_legacy: bool = False):
    # SQLAlchemy receives a connection creator so credentials are never URL-logged.
    engine = create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(dsn, connect_timeout=10),
        hide_parameters=True,
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL search_path TO public")
            conn.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '120s'")
            acquired = conn.exec_driver_sql(
                f"SELECT pg_try_advisory_xact_lock({LOCK_ID})"
            ).scalar()
            if not acquired:
                raise RuntimeError("Another migration is running; retry after it finishes")
            versioned = conn.exec_driver_sql("SELECT to_regclass('public.alembic_version')").scalar()
            current = conn.exec_driver_sql(
                "SELECT version_num FROM public.alembic_version"
            ).scalars().all() if versioned else []
            if current != [SCHEMA_REVISION] and conn.exec_driver_sql("""
                SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                WHERE datname=current_database() AND pid<>pg_backend_pid()
                AND backend_type='client backend')
            """).scalar():
                raise RuntimeError("Stop hub/core and other database clients before upgrading")
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).parent))
            config.attributes.update(connection=conn, keyring=keys, adopt_legacy=adopt_legacy)
            command.upgrade(config, "head")
            # Wrong/missing keys fail even on repeat upgrades, before services start.
            for row in conn.exec_driver_sql(
                "SELECT id, owner, provider, purpose, key_id, version, nonce, ciphertext FROM secrets"
            ).mappings():
                keys.decrypt(row["id"], SecretContext(
                    row["owner"], row["provider"], row["purpose"],
                ), row)
    finally:
        engine.dispose()


async def rotate(dsn, keys):
    store = PostgresSecretStore(keys)
    async with await psycopg.AsyncConnection.connect(
        dsn, connect_timeout=10, autocommit=True,
    ) as conn:
        cursor = await conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
        if not (await cursor.fetchone())[0]:
            raise RuntimeError("Another migration or rotation is running; retry later")
        await check_schema(conn)
        while True:
            async with conn.transaction():
                await conn.execute("SET LOCAL lock_timeout = '10s'")
                await conn.execute("SET LOCAL statement_timeout = '120s'")
                count = await store.rotate_batch(conn)
            if not count:
                break



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upgrade", "rotate"), nargs="?", default="upgrade")
    parser.add_argument("--adopt-legacy", action="store_true")
    args = parser.parse_args()
    try:
        keys = Keyring.from_file()
        dsn = os.environ["DATABASE_URL"]
        if args.action == "rotate":
            asyncio.run(rotate(dsn, keys))
        else:
            upgrade(dsn, keys, adopt_legacy=args.adopt_legacy)
    except Exception as exc:  # noqa: BLE001 — CLI boundary must redact driver parameters
        # Driver/validation exceptions may contain values or connection strings.
        if type(exc) is RuntimeError:
            parser.exit(1, f"Migration refused: {exc}\n")
        parser.exit(1, "Migration failed; check schema, database access and encryption keys. No revision was advanced.\n")
    print("Database operation complete")


if __name__ == "__main__":
    main()
