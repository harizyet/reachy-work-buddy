CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    location TEXT
);

CREATE INDEX IF NOT EXISTS calendar_events_start_at_idx ON calendar_events (start_at);

CREATE TABLE IF NOT EXISTS confirmation_requests (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    description TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    confirmed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS email_received (
    id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS email_drafts (
    id TEXT PRIMARY KEY,
    "to" TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    in_reply_to TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    approved_at TIMESTAMPTZ,
    dispatch_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    document_title TEXT NOT NULL,
    section TEXT,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    embedding VECTOR(384) NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    project_scope TEXT,
    confidence DOUBLE PRECISION NOT NULL,
    sensitivity TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    last_accessed TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    forgotten_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    mode TEXT NOT NULL,
    privacy TEXT NOT NULL,
    base_channel TEXT NOT NULL,
    delivery_channel TEXT NOT NULL,
    overridden BOOLEAN NOT NULL,
    action TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS audit_log_user_id_created_at_idx
ON audit_log (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS telegram_chats (
    user_id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_queue (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    privacy TEXT NOT NULL,
    urgency TEXT NOT NULL,
    source_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS notification_queue_user_id_idx ON notification_queue (user_id);

CREATE TABLE IF NOT EXISTS robots (
    robot_id TEXT PRIMARY KEY,
    base_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    conversation_id TEXT NOT NULL,
    active_channel TEXT NOT NULL,
    interaction_mode TEXT NOT NULL,
    privacy_context TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    last_active_at TIMESTAMPTZ NOT NULL,
    dnd BOOLEAN NOT NULL DEFAULT false,
    last_interruption_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY CHECK (id = 'owner'), username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS llm_config (
 id TEXT PRIMARY KEY DEFAULT 'default', config JSONB NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS llm_usage_log (
 id TEXT PRIMARY KEY, at TIMESTAMPTZ NOT NULL, role TEXT NOT NULL,
 model TEXT NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER,
 latency_ms DOUBLE PRECISION NOT NULL, success BOOLEAN NOT NULL,
 error_message TEXT, escalation_reason TEXT);

CREATE INDEX IF NOT EXISTS llm_usage_at_idx ON llm_usage_log (at DESC);
