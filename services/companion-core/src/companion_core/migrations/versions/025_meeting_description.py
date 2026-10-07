"""A short description under each meeting's title, and who named the meeting (owner, generated or default)."""
from alembic import op

revision = "025_meeting_description"
down_revision = "024_alarm_repeat"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN description TEXT")
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN title_source TEXT NOT NULL DEFAULT 'default'")
    # A title that is not the apps' own "Meeting 7 Oct 12:05" was chosen by the owner and must never be replaced.
    conn.exec_driver_sql(
        r"UPDATE meetings SET title_source = 'owner' "
        r"WHERE title !~ '^\s*(Meeting|Recording)(\s+[0-9][\s0-9:A-Za-z.,/-]{0,23})?\s*$'"
    )


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
