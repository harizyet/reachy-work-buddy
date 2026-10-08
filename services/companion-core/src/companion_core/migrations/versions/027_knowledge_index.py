"""Phase 44B (docs/phase-44.md section 5.2 and 6): the derived knowledge index and its transactional outbox.

`knowledge_items` is rebuildable from the stores and is never the source of truth. `knowledge_outbox` is filled by triggers on the
source tables, in the same transaction as the change, so a rolled-back change leaves no event and a committed one cannot lose its event.
Deleting or forgetting a record also deletes its index rows in the same transaction, so exclusion never waits for the worker.
Nothing here searches; migration adds no new behaviour until KNOWLEDGE_INDEXING_ENABLED turns the worker on, and the existing records
are queued for a first build.

Only derived data is created, so this revision can be undone without losing anything authoritative (see `rollback-027.sql` and
`downgrade`), and it can be applied again after a restore: it first removes any earlier copy of its own objects."""
from alembic import op

revision = "027_knowledge_index"
down_revision = "026_source_sensitivity"

_CLASSIFICATION = "('public', 'work-private', 'sensitive')"

_DROP_SQL = [
    # Triggers go with their functions (CASCADE); the derived tables are dropped, never the source tables.
    "DROP FUNCTION IF EXISTS knowledge_memories_trg() CASCADE",
    "DROP FUNCTION IF EXISTS knowledge_chunks_trg() CASCADE",
    "DROP FUNCTION IF EXISTS knowledge_meetings_trg() CASCADE",
    "DROP FUNCTION IF EXISTS knowledge_notes_trg() CASCADE",
    "DROP FUNCTION IF EXISTS knowledge_tasks_trg() CASCADE",
    "DROP FUNCTION IF EXISTS knowledge_reminders_trg() CASCADE",
    "DROP FUNCTION IF EXISTS knowledge_enqueue(TEXT, TEXT)",
    "DROP TABLE IF EXISTS knowledge_outbox",
    "DROP TABLE IF EXISTS knowledge_items",
]

_TABLE_SQL = [
    f"""CREATE TABLE knowledge_items (
        ref_key TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        locator TEXT,
        kind TEXT NOT NULL,
        source_version TEXT NOT NULL,
        match_text TEXT NOT NULL,
        tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english'::regconfig, match_text)) STORED,
        embedding VECTOR(384),
        embedding_model TEXT NOT NULL,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN {_CLASSIFICATION}),
        project_scope TEXT,
        local_only BOOLEAN NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,
        observed_at TIMESTAMPTZ,
        valid_from TIMESTAMPTZ,
        valid_until TIMESTAMPTZ,
        indexed_at TIMESTAMPTZ NOT NULL
    )""",
    "CREATE INDEX knowledge_items_source ON knowledge_items (source_type, source_id)",
    "CREATE INDEX knowledge_items_tsv ON knowledge_items USING GIN (tsv)",
    "CREATE INDEX knowledge_items_embedding ON knowledge_items USING hnsw (embedding vector_cosine_ops)",
    """CREATE TABLE knowledge_outbox (
        id BIGSERIAL PRIMARY KEY,
        source_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        gen INTEGER NOT NULL DEFAULT 1,
        enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        locked_until TIMESTAMPTZ,
        last_error TEXT,
        failed_at TIMESTAMPTZ,
        UNIQUE (source_type, source_id)
    )""",
    "CREATE INDEX knowledge_outbox_ready ON knowledge_outbox (next_attempt_at) WHERE failed_at IS NULL",
    # One row per source. A change while the row is being worked bumps gen, so the worker cannot complete over it.
    """CREATE FUNCTION knowledge_enqueue(st TEXT, sid TEXT) RETURNS void LANGUAGE sql AS $$
        INSERT INTO knowledge_outbox (source_type, source_id) VALUES (st, sid)
        ON CONFLICT (source_type, source_id) DO UPDATE
        SET gen = knowledge_outbox.gen + 1, next_attempt_at = now(), attempts = 0, failed_at = NULL, last_error = NULL
    $$""",
    # memories: forgetting or deleting removes the index rows in the same transaction.
    """CREATE FUNCTION knowledge_memories_trg() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            DELETE FROM knowledge_items WHERE source_type = 'memory' AND source_id = OLD.id;
            PERFORM knowledge_enqueue('memory', OLD.id);
            RETURN OLD;
        END IF;
        IF NEW.forgotten_at IS NOT NULL THEN
            DELETE FROM knowledge_items WHERE source_type = 'memory' AND source_id = NEW.id;
        END IF;
        PERFORM knowledge_enqueue('memory', NEW.id);
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER knowledge_memories AFTER INSERT OR DELETE OR UPDATE OF
        content, type, source, project_scope, confidence, sensitivity, created_at, expires_at, forgotten_at
        ON memories FOR EACH ROW EXECUTE FUNCTION knowledge_memories_trg()""",
    # documents: the unit is the document; deleting a chunk removes its index row at once.
    """CREATE FUNCTION knowledge_chunks_trg() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            DELETE FROM knowledge_items WHERE ref_key = 'document:' || OLD.document_id || '#' || OLD.chunk_index;
            PERFORM knowledge_enqueue('document', OLD.document_id);
            RETURN OLD;
        END IF;
        PERFORM knowledge_enqueue('document', NEW.document_id);
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER knowledge_chunks AFTER INSERT OR DELETE OR UPDATE OF
        document_title, section, content, sensitivity, project_scope, chunk_index
        ON document_chunks FOR EACH ROW EXECUTE FUNCTION knowledge_chunks_trg()""",
    # meetings: deleting, cancelling or failing a meeting removes its rows at once.
    """CREATE FUNCTION knowledge_meetings_trg() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            DELETE FROM knowledge_items WHERE source_type = 'meeting' AND source_id = OLD.id;
            PERFORM knowledge_enqueue('meeting', OLD.id);
            RETURN OLD;
        END IF;
        IF NEW.status IN ('cancelled', 'failed') THEN
            DELETE FROM knowledge_items WHERE source_type = 'meeting' AND source_id = NEW.id;
        END IF;
        PERFORM knowledge_enqueue('meeting', NEW.id);
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER knowledge_meetings AFTER INSERT OR DELETE OR UPDATE OF
        title, status, transcript_segments, diarization_segments, aligned_segments, transcript_corrections, speaker_names,
        summary, minutes, sensitivity, project_scope, started_at
        ON meetings FOR EACH ROW EXECUTE FUNCTION knowledge_meetings_trg()""",
]


def _simple(table: str, source_type: str, columns: str) -> list[str]:
    function = f"knowledge_{table}_trg"
    return [
        f"""CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                DELETE FROM knowledge_items WHERE source_type = '{source_type}' AND source_id = OLD.id;
                PERFORM knowledge_enqueue('{source_type}', OLD.id);
                RETURN OLD;
            END IF;
            PERFORM knowledge_enqueue('{source_type}', NEW.id);
            RETURN NEW;
        END $$""",
        f"""CREATE TRIGGER knowledge_{table} AFTER INSERT OR DELETE OR UPDATE OF {columns}
        ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()""",
    ]


_TABLE_SQL += _simple("notes", "note", "title, body, sensitivity, project_scope")
_TABLE_SQL += _simple("tasks", "task", "text, status, sensitivity, project_scope")
_TABLE_SQL += _simple("reminders", "reminder", "text, due_at, status, sensitivity")

# Existing records are queued once so the first indexing pass builds the whole index.
_BACKFILL = [
    "INSERT INTO knowledge_outbox (source_type, source_id) SELECT 'memory', id FROM memories ON CONFLICT DO NOTHING",
    "INSERT INTO knowledge_outbox (source_type, source_id) SELECT DISTINCT 'document', document_id FROM document_chunks ON CONFLICT DO NOTHING",
    "INSERT INTO knowledge_outbox (source_type, source_id) SELECT 'meeting', id FROM meetings ON CONFLICT DO NOTHING",
    "INSERT INTO knowledge_outbox (source_type, source_id) SELECT 'note', id FROM notes ON CONFLICT DO NOTHING",
    "INSERT INTO knowledge_outbox (source_type, source_id) SELECT 'task', id FROM tasks ON CONFLICT DO NOTHING",
    "INSERT INTO knowledge_outbox (source_type, source_id) SELECT 'reminder', id FROM reminders ON CONFLICT DO NOTHING",
]


def upgrade():
    conn = op.get_bind()
    for statement in [*_DROP_SQL, *_TABLE_SQL, *_BACKFILL]:
        conn.exec_driver_sql(statement)


def downgrade():
    conn = op.get_bind()
    for statement in _DROP_SQL:
        conn.exec_driver_sql(statement)
