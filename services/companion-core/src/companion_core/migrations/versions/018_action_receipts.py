"""Phase 39 action receipts: structured record of what deterministic handlers did."""
from alembic import op

revision = "018_action_receipts"
down_revision = "017_persona_tone"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("""CREATE TABLE action_receipts (
        id TEXT PRIMARY KEY, action_type TEXT NOT NULL, status TEXT NOT NULL,
        at TIMESTAMPTZ NOT NULL, source_channel TEXT NOT NULL, object_type TEXT NOT NULL,
        object_id TEXT, fields JSONB NOT NULL DEFAULT '{}', failure_reason TEXT,
        notify BOOLEAN NOT NULL DEFAULT FALSE, notified_at TIMESTAMPTZ
    )""")
    conn.exec_driver_sql("CREATE INDEX action_receipts_at ON action_receipts (at DESC)")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
