"""Web-search grounding configuration (Phase 24a) for the generic-conversation LLM path."""
from alembic import op

revision = "006_search_config"
down_revision = "005_desktop_oauth"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("""
        CREATE TABLE search_config (
            id TEXT PRIMARY KEY CHECK (id = 'default'),
            policy TEXT NOT NULL DEFAULT 'off',
            provider TEXT NOT NULL DEFAULT 'searxng',
            base_url TEXT,
            secret_ref TEXT,
            result_count INTEGER NOT NULL DEFAULT 5,
            timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now())
    """)
    conn.exec_driver_sql("INSERT INTO search_config (id) VALUES ('default')")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
