"""Durable coding-agent projects, sessions, events and usage (Phase 29.27)."""
from alembic import op

revision = '013_coding_agent'
down_revision = '012_web_chats'


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql('''CREATE TABLE coding_agent_projects (
        id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL
    )''')
    conn.exec_driver_sql('''CREATE TABLE coding_agent_sessions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES coding_agent_projects(id),
        status TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL
    )''')
    conn.exec_driver_sql('CREATE INDEX coding_agent_sessions_status ON coding_agent_sessions (status)')
    conn.exec_driver_sql('CREATE INDEX coding_agent_sessions_started ON coding_agent_sessions (started_at)')
    conn.exec_driver_sql('''CREATE TABLE coding_agent_events (
        sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL,
        session_id TEXT NOT NULL REFERENCES coding_agent_sessions(id), data JSONB NOT NULL
    )''')
    conn.exec_driver_sql('CREATE INDEX coding_agent_events_session ON coding_agent_events (session_id, sequence)')
    conn.exec_driver_sql('''CREATE TABLE coding_agent_usage_snapshots (
        sequence BIGSERIAL PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES coding_agent_sessions(id),
        provider TEXT NOT NULL, measured_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL
    )''')
    conn.exec_driver_sql(
        'CREATE INDEX coding_agent_usage_session ON coding_agent_usage_snapshots (session_id, sequence)')
    conn.exec_driver_sql(
        'CREATE INDEX coding_agent_usage_provider ON coding_agent_usage_snapshots (provider, measured_at DESC)')
    # Core's claim-once ledger for completion notifications. Deliberately no
    # foreign key: core never reads the coding-agent tables directly.
    conn.exec_driver_sql('''CREATE TABLE coding_agent_notifications (
        session_id TEXT PRIMARY KEY, claimed_at TIMESTAMPTZ NOT NULL
    )''')


def downgrade():
    raise RuntimeError('Restore a tested backup; automatic destructive downgrade is unsupported')
