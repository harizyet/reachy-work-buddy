"""Owner Google grant and short-lived OAuth handoffs; credentials are references."""
from alembic import op

revision = "003_accounts"
down_revision = "002_secrets"


def upgrade():
    op.execute("""
        CREATE TABLE google_accounts (
            owner TEXT PRIMARY KEY CHECK (owner = 'owner'),
            data JSONB NOT NULL DEFAULT '{}')
    """)
    op.execute("INSERT INTO google_accounts(owner) VALUES ('owner')")
    op.execute("""
        CREATE TABLE google_oauth_states (
            state_hash TEXT PRIMARY KEY, owner TEXT NOT NULL,
            binding_hash TEXT UNIQUE NOT NULL, capability TEXT NOT NULL,
            generation TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
            verifier_ref TEXT NOT NULL, code_ref TEXT, error TEXT,
            returned BOOLEAN NOT NULL DEFAULT false)
    """)
    op.execute("""
        CREATE TABLE google_reminder_delivery (
            event_id TEXT PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL)
    """)


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
