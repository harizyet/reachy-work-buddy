"""Aligned transcript: each transcript segment with its speaker (Phase 27.4 alignment)."""
from alembic import op

revision = "022_meeting_alignment"
down_revision = "021_meeting_outputs"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN aligned_segments JSONB")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
