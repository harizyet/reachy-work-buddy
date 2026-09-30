"""Phase 27.2/27.3 (docs/phase-27.md, ADR 0025): raw speech-sidecar output.

`transcript_segments`/`diarization_segments` hold the STT/diarization
sidecars' own segment lists (start/end/text or start/end/speaker) as
JSONB, keyed to the meeting they came from. This is not yet the canonical
27.4/27.5 `TranscriptSegment` alignment model — it's the two independent
raw results a future alignment step reads, kept distinct so a diarization
failure and a transcription failure remain distinguishable per-column
rather than collapsed into one ambiguous stage.
"""
from alembic import op

revision = "011_meeting_speech_results"
down_revision = "010_meetings"


def upgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN transcript_segments JSONB")
    conn.exec_driver_sql("ALTER TABLE meetings ADD COLUMN diarization_segments JSONB")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
