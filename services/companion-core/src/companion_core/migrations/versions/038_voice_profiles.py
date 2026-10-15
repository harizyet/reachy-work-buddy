"""Encrypted voice profiles for shared voice identity (Phase 32A.V, ADR 0041): one row per profile, the embedding template held only as AES-GCM ciphertext (the key is outside the database).
At most one owner profile; re-enrolling replaces it in place. Additive and repeatable over a leftover copy (it never drops enrolled profiles); no existing table changes."""
from alembic import op

revision = "038_voice_profiles"
down_revision = "037_processing_provenance"

_UP = [
    """CREATE TABLE IF NOT EXISTS voice_profiles (
        profile_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'owner' CHECK (kind IN ('owner')),
        label TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version >= 1),
        model_version TEXT NOT NULL,
        sample_count INTEGER NOT NULL CHECK (sample_count >= 1),
        client_kind TEXT NOT NULL,
        client_id TEXT NOT NULL,
        device_id TEXT,
        key_id TEXT NOT NULL,
        nonce BYTEA NOT NULL,
        ciphertext BYTEA NOT NULL,
        consented_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS voice_profiles_one_owner ON voice_profiles (owner_id) WHERE kind = 'owner'",
]


def upgrade():
    conn = op.get_bind()
    for statement in _UP:
        conn.exec_driver_sql(statement)


def downgrade():
    # Deletes every enrolled voice profile (they are re-enrolled after an upgrade); nothing else references the table.
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS voice_profiles")
