"""Supervised meeting-minutes email (Phase 55, ADR 0039): additive columns on email_drafts, attachment and event tables, the one-row dedicated sender configuration (the credential itself is in `secrets`), and saved recipient groups."""
from alembic import op

revision = "036_meeting_email"
down_revision = "035_meeting_speaker_identity"

_UP = [
    """ALTER TABLE email_drafts
        ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'text',
        ADD COLUMN IF NOT EXISTS recipients JSONB,
        ADD COLUMN IF NOT EXISTS source JSONB,
        ADD COLUMN IF NOT EXISTS package_hash TEXT,
        ADD COLUMN IF NOT EXISTS approved_hash TEXT,
        ADD COLUMN IF NOT EXISTS message_id TEXT,
        ADD COLUMN IF NOT EXISTS sender TEXT,
        ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS last_error TEXT,
        ADD COLUMN IF NOT EXISTS provider_response TEXT""",
    "CREATE INDEX IF NOT EXISTS email_drafts_due ON email_drafts (status, dispatch_at)",
    """CREATE TABLE IF NOT EXISTS email_draft_attachments (
        draft_id TEXT NOT NULL REFERENCES email_drafts(id) ON DELETE CASCADE,
        name TEXT NOT NULL, content_type TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, data BYTEA NOT NULL,
        PRIMARY KEY (draft_id, name))""",
    """CREATE TABLE IF NOT EXISTS email_draft_events (
        id BIGSERIAL PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES email_drafts(id) ON DELETE CASCADE,
        at TIMESTAMPTZ NOT NULL, event TEXT NOT NULL, detail JSONB NOT NULL DEFAULT '{}'::jsonb)""",
    "CREATE INDEX IF NOT EXISTS email_draft_events_draft ON email_draft_events (draft_id, id)",
    """CREATE TABLE IF NOT EXISTS mail_sender (
        id INTEGER PRIMARY KEY CHECK (id = 1), enabled BOOLEAN NOT NULL DEFAULT false, host TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL DEFAULT 587,
        security TEXT NOT NULL DEFAULT 'starttls' CHECK (security IN ('starttls', 'none')), from_address TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '',
        secret_ref TEXT, verified_at TIMESTAMPTZ, verified_ok BOOLEAN, verified_detail TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ)""",
    """CREATE TABLE IF NOT EXISTS meeting_recipient_groups (
        id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, addresses JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)""",
]

_DOWN = [
    # A meeting package has no meaning without its columns: remove those drafts first so none can survive as a plain draft addressed to its first recipient only.
    "DELETE FROM email_drafts WHERE kind = 'meeting_minutes'",
    "DELETE FROM secrets WHERE provider = 'mail-sender'",
    "DROP TABLE IF EXISTS meeting_recipient_groups",
    "DROP TABLE IF EXISTS mail_sender",
    "DROP TABLE IF EXISTS email_draft_events",
    "DROP TABLE IF EXISTS email_draft_attachments",
    "DROP INDEX IF EXISTS email_drafts_due",
    """ALTER TABLE email_drafts DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS recipients, DROP COLUMN IF EXISTS source, DROP COLUMN IF EXISTS package_hash,
        DROP COLUMN IF EXISTS approved_hash, DROP COLUMN IF EXISTS message_id, DROP COLUMN IF EXISTS sender, DROP COLUMN IF EXISTS attempts,
        DROP COLUMN IF EXISTS claimed_at, DROP COLUMN IF EXISTS last_error, DROP COLUMN IF EXISTS provider_response""",
]


def upgrade():
    conn = op.get_bind()
    for statement in _UP:
        conn.exec_driver_sql(statement)


def downgrade():
    conn = op.get_bind()
    for statement in _DOWN:
        conn.exec_driver_sql(statement)
