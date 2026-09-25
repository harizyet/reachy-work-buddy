"""Owner location and time zone for the conversation context (Phase 24a follow-up)."""
from alembic import op

revision = "008_assistant_context"
down_revision = "007_search_providers"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE persona_config ADD COLUMN location TEXT")
    conn.exec_driver_sql("ALTER TABLE persona_config ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
