"""Key terms for meeting transcript corrections: a global glossary and per-meeting terms (Phase 41, ADR 0030)."""
from alembic import op

revision = "020_meeting_terms"
down_revision = "019_meeting_annotations"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN key_terms JSONB NOT NULL DEFAULT '[]'")
    conn.exec_driver_sql("""CREATE TABLE meeting_terms (
        term TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    conn.exec_driver_sql("CREATE UNIQUE INDEX meeting_terms_term ON meeting_terms (lower(term))")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
