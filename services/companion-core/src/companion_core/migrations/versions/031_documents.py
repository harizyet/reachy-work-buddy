"""Phase 50B (docs/phase-50.md): the Reachy document record.

* `document_outputs` - derived interpretations (Phase 50H summaries): text and section summaries with the original's hash, the extraction tier, the model and prompt version, the inherited class, a stale flag, and an error code. Derived, never authoritative; deleted with the document.
* `documents` - one row per uploaded document: its title and filename, content type, the SHA-256 and size of the original (which lives in the content-addressed source store on disk, not in the
  database), the owner's sensitivity and project scope, the lifecycle state, and the opaque reference to the document backend (`backend`, `backend_ref`, `backend_revision`, `tier`).

Several rows may share one `source_hash` (identical bytes uploaded twice are two documents with separate policy and one blob), so the hash is indexed, not unique. No foreign key, no trigger, nothing in the
knowledge index. Authoritative data elsewhere is not changed, so this revision can be undone without losing any note, task, reminder or meeting (see `rollback-031.sql` and `downgrade`; the originals
on disk are not touched by either). It first removes any earlier copy of its own table, so it can be applied again after a restore."""
from alembic import op

revision = "031_documents"
down_revision = "030_note_tags"

_DROP_SQL = ["DROP TABLE IF EXISTS document_outputs", "DROP TABLE IF EXISTS documents"]

_TABLE_SQL = [
    """CREATE TABLE documents (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        source_hash TEXT NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
        size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        project_scope TEXT,
        state TEXT NOT NULL CHECK (state IN ('uploaded', 'queued', 'processing', 'ready', 'partial', 'failed', 'deleting')),
        backend TEXT NOT NULL DEFAULT 'mineru',
        backend_ref TEXT,
        backend_revision TEXT,
        tier TEXT,
        processing_priority TEXT NOT NULL CHECK (processing_priority IN ('background', 'normal', 'interactive')),
        page_count INTEGER,
        error_code TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    "CREATE INDEX documents_source_hash ON documents (source_hash)",
    "CREATE INDEX documents_state ON documents (state, created_at)",
    """CREATE TABLE document_outputs (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('summary')),
        style TEXT NOT NULL CHECK (style IN ('ordinary', 'executive', 'technical')),
        source_hash TEXT NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
        tier TEXT NOT NULL,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        status TEXT NOT NULL CHECK (status IN ('running', 'ready', 'failed')),
        text TEXT NOT NULL DEFAULT '',
        sections JSONB NOT NULL DEFAULT '[]',
        pages_covered TEXT,
        page_count INTEGER,
        truncated BOOLEAN NOT NULL DEFAULT FALSE,
        model TEXT,
        prompt_version TEXT NOT NULL,
        stale BOOLEAN NOT NULL DEFAULT FALSE,
        error_code TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    # At most one current (not stale) running or ready output per document, kind and style, so two requests cannot start the same summary twice.
    "CREATE UNIQUE INDEX document_outputs_one_current ON document_outputs (document_id, kind, style) WHERE NOT stale AND status IN ('running', 'ready')",
    "CREATE INDEX document_outputs_document ON document_outputs (document_id, created_at)",
]


def upgrade():
    conn = op.get_bind()
    for statement in [*_DROP_SQL, *_TABLE_SQL]:
        conn.exec_driver_sql(statement)


def downgrade():
    conn = op.get_bind()
    for statement in _DROP_SQL:
        conn.exec_driver_sql(statement)
