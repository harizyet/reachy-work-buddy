"""Owner's notes and timed reminders entered through the web UI."""
from alembic import op

revision = '014_planner'
down_revision = '013_coding_agent'


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql('''CREATE TABLE notes (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
    )''')
    conn.exec_driver_sql('CREATE INDEX notes_updated ON notes (updated_at DESC)')
    conn.exec_driver_sql('''CREATE TABLE reminders (
        id TEXT PRIMARY KEY, text TEXT NOT NULL, due_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ, notified_at TIMESTAMPTZ
    )''')
    conn.exec_driver_sql('CREATE INDEX reminders_due ON reminders (due_at)')


def downgrade():
    raise RuntimeError('Restore a tested backup; automatic destructive downgrade is unsupported')
