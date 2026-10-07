"""Stretches of a recording with no captured audio, found by checking the recording after the meeting completes."""
from alembic import op

revision = "023_meeting_audio_gaps"
down_revision = "022_meeting_alignment"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN audio_gaps JSONB")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
