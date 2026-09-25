"""Hosted web-search provider rotation with per-provider monthly caps (Phase 24d)."""
from alembic import op

revision = "007_search_providers"
down_revision = "006_search_config"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("""
        CREATE TABLE search_provider (
            provider TEXT PRIMARY KEY CHECK (provider IN ('brave', 'exa', 'tavily')),
            enabled BOOLEAN NOT NULL DEFAULT false,
            secret_ref TEXT,
            monthly_limit INTEGER NOT NULL CHECK (monthly_limit > 0))
    """)
    conn.exec_driver_sql("""
        INSERT INTO search_provider (provider, monthly_limit)
        VALUES ('brave', 900), ('exa', 900), ('tavily', 900)
    """)
    conn.exec_driver_sql("""
        CREATE TABLE search_usage (
            provider TEXT NOT NULL REFERENCES search_provider (provider),
            period TEXT NOT NULL,
            used INTEGER NOT NULL CHECK (used >= 0),
            PRIMARY KEY (provider, period))
    """)
    # A Brave provider chosen under 006 becomes the enabled Brave rotation
    # entry; its secret was written under the same websearch:brave context,
    # so the ref moves over unchanged. SearXNG becomes the fallback tier.
    conn.exec_driver_sql("""
        UPDATE search_provider p SET enabled = true, secret_ref = c.secret_ref
        FROM search_config c
        WHERE c.id = 'default' AND c.provider = 'brave' AND p.provider = 'brave'
    """)
    conn.exec_driver_sql("""
        UPDATE search_config SET provider = 'builtin_searxng', secret_ref = NULL
        WHERE provider = 'brave'
    """)
    # 006's column default was 'searxng' although the model default is the
    # built-in container; only a never-configured row is corrected.
    conn.exec_driver_sql("""
        UPDATE search_config SET provider = 'builtin_searxng'
        WHERE provider = 'searxng' AND base_url IS NULL AND secret_ref IS NULL
    """)
    conn.exec_driver_sql("ALTER TABLE search_config RENAME COLUMN provider TO fallback")
    conn.exec_driver_sql("ALTER TABLE search_config ALTER COLUMN fallback SET DEFAULT 'builtin_searxng'")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
