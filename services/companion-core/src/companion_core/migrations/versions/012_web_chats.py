"""Durable hub-owned web chat records, without changing existing sessions."""
from alembic import op

revision = '012_web_chats'
down_revision = '011_meeting_speech_results'


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql('''CREATE TABLE web_chats (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
    )''')
    conn.exec_driver_sql('CREATE INDEX web_chats_user_updated ON web_chats (user_id, updated_at DESC)')
    conn.exec_driver_sql('''CREATE TABLE web_chat_turns (
        sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL,
        chat_id TEXT NOT NULL REFERENCES web_chats(id), data JSONB NOT NULL
    )''')
    conn.exec_driver_sql('CREATE INDEX web_chat_turns_chat ON web_chat_turns (chat_id, sequence)')


def downgrade():
    raise RuntimeError('Restore a tested backup; automatic destructive downgrade is unsupported')
