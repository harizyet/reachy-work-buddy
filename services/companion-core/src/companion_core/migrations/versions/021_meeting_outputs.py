"""Generated meeting outputs: summary and minutes, each with the model tier that wrote it (Phase 43)."""
from alembic import op

revision = "021_meeting_outputs"
down_revision = "020_meeting_terms"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN summary JSONB")
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN minutes JSONB")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
