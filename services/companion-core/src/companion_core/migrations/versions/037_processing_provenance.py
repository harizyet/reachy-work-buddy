"""Processing provenance and the owner's name for outbound meeting email (ADR 0040): an append-only record per meeting of where each step that read its content ran, and the
name the dedicated sender's messages use for the owner. Both additive; existing meetings start with an empty record, which is never read as "processed privately"."""
from alembic import op

revision = "037_processing_provenance"
down_revision = "036_meeting_email"

_UP = [
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS processing_events JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE mail_sender ADD COLUMN IF NOT EXISTS owner_name TEXT NOT NULL DEFAULT ''",
]

_DOWN = [
    "ALTER TABLE mail_sender DROP COLUMN IF EXISTS owner_name",
    "ALTER TABLE meetings DROP COLUMN IF EXISTS processing_events",
]


def upgrade():
    conn = op.get_bind()
    for statement in _UP:
        conn.exec_driver_sql(statement)


def downgrade():
    conn = op.get_bind()
    for statement in _DOWN:
        conn.exec_driver_sql(statement)
