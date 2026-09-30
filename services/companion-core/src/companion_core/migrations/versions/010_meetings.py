"""Phase 27.1 foundation: durable meeting jobs (docs/phase-27.md).

Raw audio bytes live on disk under MEETING_AUDIO_DIR, not in this table —
same reasoning as owner-recognition's filesystem capture store: large
binary blobs don't belong in Postgres rows. `audio_path`/
`normalized_audio_path` are relative paths under that directory.
"""
from alembic import op

revision = "010_meetings"
down_revision = "009_wake_arm"


def upgrade():
    op.get_bind().exec_driver_sql("""
        CREATE TABLE meetings (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            project_scope TEXT,
            context TEXT,
            participants TEXT[] NOT NULL DEFAULT '{}',
            started_at TIMESTAMPTZ,
            source_filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            audio_path TEXT NOT NULL,
            normalized_audio_path TEXT,
            duration_seconds DOUBLE PRECISION,
            status TEXT NOT NULL,
            error_detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.get_bind().exec_driver_sql("CREATE INDEX meetings_status_created_at ON meetings (status, created_at)")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
