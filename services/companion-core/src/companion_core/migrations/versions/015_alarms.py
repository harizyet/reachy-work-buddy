"""Phase 38 alarms (ADR 0027): scheduled alarms, optionally linked to a reminder, and owner-saved stations."""
from alembic import op

revision = '015_alarms'
down_revision = '014_planner'


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql('''CREATE TABLE alarms (
        id TEXT PRIMARY KEY, label TEXT NOT NULL, due_at TIMESTAMPTZ NOT NULL,
        reminder_id TEXT, station_id TEXT, status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL, fired_at TIMESTAMPTZ, delivery TEXT
    )''')
    conn.exec_driver_sql('CREATE INDEX alarms_due ON alarms (due_at)')
    conn.exec_driver_sql('''CREATE TABLE stations (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, guide_id TEXT NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL
    )''')


def downgrade():
    raise RuntimeError('Restore a tested backup; automatic destructive downgrade is unsupported')
