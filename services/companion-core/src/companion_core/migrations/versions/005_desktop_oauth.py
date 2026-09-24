"""Tag OAuth flow rows by client type so desktop and web handoffs can't cross-match."""
from alembic import op

revision = "005_desktop_oauth"
down_revision = "004_persona"


def upgrade():
    op.execute("ALTER TABLE google_oauth_states ADD COLUMN client_type TEXT NOT NULL DEFAULT 'web'")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
