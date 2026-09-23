"""Configurable assistant identity (name + system prompt) for the LLM chat path."""
from alembic import op
from sqlalchemy import text

from shared.models.persona import DEFAULT_NAME, DEFAULT_SYSTEM_PROMPT

revision = "004_persona"
down_revision = "003_accounts"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("""
        CREATE TABLE persona_config (
            id TEXT PRIMARY KEY CHECK (id = 'default'),
            name TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now())
    """)
    conn.execute(
        text("INSERT INTO persona_config (id, name, system_prompt) VALUES ('default', :name, :prompt)"),
        {"name": DEFAULT_NAME, "prompt": DEFAULT_SYSTEM_PROMPT},
    )


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
