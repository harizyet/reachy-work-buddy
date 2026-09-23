"""Frozen baseline and explicit historical repairs. Never blindly stamp legacy DBs."""

from pathlib import Path

from sqlalchemy import text

BASELINE = Path(__file__).with_name("baseline.sql").read_text()
REPAIRS = {
    "sessions": {"dnd": "BOOLEAN NOT NULL DEFAULT false", "last_interruption_at": "TIMESTAMPTZ"},
    "audit_log": {"action": "TEXT"},
    "memories": {"forgotten_at": "TIMESTAMPTZ"},
    "email_drafts": {"dispatch_at": "TIMESTAMPTZ"},
    "llm_usage_log": {"escalation_reason": "TEXT"},
}


def shape(conn, schema):
    columns = conn.execute(text("""
        SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod),
               a.attnotnull, pg_get_expr(d.adbin,d.adrelid)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname=:schema AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attname
    """), {"schema": schema}).all()
    result = {}
    for table, name, kind, required, default in columns:
        if table == "alembic_version":
            continue
        result.setdefault(table, {})[name] = (kind, required, default)
    return result


def constraints(conn, schema, table):
    return set(conn.execute(text("""
        SELECT pg_get_constraintdef(co.oid) FROM pg_constraint co
        JOIN pg_class c ON c.oid=co.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=:schema AND c.relname=:table
    """), {"schema": schema, "table": table}).scalars())


def adopt(conn, allowed):
    existing = shape(conn, "public")
    if existing and not allowed:
        raise RuntimeError("Legacy database detected: back up, stop old apps, then use --adopt-legacy")
    # Reference schema is transactional and removed before recording the baseline.
    conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    conn.exec_driver_sql("CREATE SCHEMA migration_reference")
    conn.exec_driver_sql("SET LOCAL search_path TO migration_reference, public")
    for statement in BASELINE.split(";"):
        if statement.strip() and "CREATE EXTENSION" not in statement:
            conn.exec_driver_sql(statement)
    expected = shape(conn, "migration_reference")
    conn.exec_driver_sql("SET LOCAL search_path TO public")
    if set(existing) - set(expected):
        raise RuntimeError("Unknown legacy tables; review schema drift before adoption")
    for table, cols in existing.items():
        target = expected[table]
        if set(cols) - set(target):
            raise RuntimeError(f"Unknown legacy columns in {table}; review schema drift")
        for name, specification in cols.items():
            if specification != target[name]:
                raise RuntimeError(f"Incompatible column {table}.{name}; review type/nullability/default")
        if constraints(conn, "public", table) != constraints(conn, "migration_reference", table):
            raise RuntimeError(f"Incompatible constraints in {table}; review schema drift")
        for name in set(target) - set(cols):
            definition = REPAIRS.get(table, {}).get(name)
            if definition is None:
                raise RuntimeError(f"Unsupported missing column {table}.{name}")
            conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
    for statement in BASELINE.split(";"):
        if statement.strip():
            conn.exec_driver_sql(statement)
    if shape(conn, "public") != expected:
        raise RuntimeError("Baseline validation failed")
    def indexes(schema):
        rows = conn.execute(text("""
            SELECT tablename, indexname, indexdef FROM pg_indexes
            WHERE schemaname=:schema AND tablename <> 'alembic_version'
        """), {"schema": schema}).all()
        return {(table, name): definition.replace(f" ON {schema}.", " ON ")
                for table, name, definition in rows}

    if indexes("public") != indexes("migration_reference"):
        raise RuntimeError("Incompatible indexes; review schema drift before adoption")
    # Reject triggers, RLS, or non-table relations that could change write semantics.
    if conn.execute(text("""
        SELECT EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND NOT t.tgisinternal)
        OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND (c.relrowsecurity OR c.relkind IN ('v','m','f','p')))
    """)).scalar():
        raise RuntimeError("Unsupported triggers, policies or relations in legacy database")
    conn.exec_driver_sql("DROP SCHEMA migration_reference CASCADE")
    conn.exec_driver_sql("""
        INSERT INTO llm_config (id, config) VALUES ('default',
        '{"local":null,"cloud":null,"routing":{"mode":"local_only"},"updated_at":null}'::jsonb)
        ON CONFLICT DO NOTHING
    """)
