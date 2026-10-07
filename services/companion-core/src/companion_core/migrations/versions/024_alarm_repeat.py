"""Alarm clock: weekdays an alarm repeats on, and the on/off switch (docs/phase-38.md 38.8)."""
from alembic import op

revision = "024_alarm_repeat"
down_revision = "023_meeting_audio_gaps"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE alarms ADD COLUMN repeat JSONB NOT NULL DEFAULT '[]'::jsonb")
    conn.exec_driver_sql("ALTER TABLE alarms ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT TRUE")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
