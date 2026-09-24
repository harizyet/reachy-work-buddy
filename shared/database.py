"""Schema compatibility contract shared by SQL stores; no startup DDL."""

SCHEMA_REVISION = "005_desktop_oauth"


async def check_schema(conn) -> None:
    cursor = await conn.execute("SELECT to_regclass('public.alembic_version')")
    if (await cursor.fetchone())[0] is None:
        raise RuntimeError("Database is unversioned; run the documented migration command first")
    cursor = await conn.execute("SELECT version_num FROM public.alembic_version")
    if await cursor.fetchall() != [(SCHEMA_REVISION,)]:
        raise RuntimeError("Database revision is incompatible; run the documented upgrade")
