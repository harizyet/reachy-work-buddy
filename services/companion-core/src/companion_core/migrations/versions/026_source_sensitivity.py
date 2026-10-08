"""Phase 44A (docs/phase-44.md): classification and scope on the authoritative records, whether or not a knowledge index is ever enabled.

Every existing row becomes 'work-private' and unscoped (project_scope NULL). Nothing is inferred: no scope is guessed from content.
NULL means unscoped, not public and not "every project"."""
from alembic import op

revision = "026_source_sensitivity"
down_revision = "025_meeting_description"

_SENSITIVITY = "sensitivity TEXT NOT NULL DEFAULT 'work-private' CHECK (sensitivity IN ('public', 'work-private', 'sensitive'))"
_TABLES = {
    "document_chunks": True,
    "notes": True,
    "tasks": True,
    "reminders": False,
    "meetings": False,
}


def upgrade():
    conn = op.get_bind()
    for table, with_scope in _TABLES.items():
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {_SENSITIVITY}")
        if with_scope:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN project_scope TEXT")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
