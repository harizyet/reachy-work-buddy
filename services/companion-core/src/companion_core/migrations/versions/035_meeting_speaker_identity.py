"""Owner-confirmed speaker identities (Phase 54): one additive column holding the owner's decision per diarization label and the diarization fingerprint it was made against. Existing speaker_names stay as they are."""
from alembic import op

revision = "035_meeting_speaker_identity"
down_revision = "034_meeting_multimodal"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS speaker_identity JSONB")


def downgrade():
    # Loses only unknown/skipped decisions, contact references and the superseded record; speaker_names (the names) stay.
    op.get_bind().exec_driver_sql("ALTER TABLE meetings DROP COLUMN IF EXISTS speaker_identity")
