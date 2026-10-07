"""Owner speaker names and transcript corrections for meetings (Phase 41, ADR 0030)."""
from alembic import op

revision = "019_meeting_annotations"
down_revision = "018_action_receipts"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN speaker_names JSONB NOT NULL DEFAULT '{}'")
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN transcript_corrections JSONB NOT NULL DEFAULT '{}'")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
