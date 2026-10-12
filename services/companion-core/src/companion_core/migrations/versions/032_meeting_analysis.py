"""Phase 31 (docs/phase-31.md): owner-requested meeting analysis.

* `meeting_analysis_runs` - one row per analysis request. It holds the immutable snapshot of the transcript (numbered segments as JSON, with their SHA-256), so extraction never
  depends on what a correction says later. A partial unique index allows at most one queued or processing run per meeting.
* `meeting_analysis_items` - decisions, open questions and action candidates extracted from a snapshot, each with its verified evidence (segment index, timestamps, speaker label,
  quote). They are NOT tasks or memories. A unique (meeting_id, fingerprint) pair means re-analysing can never bring back an item already extracted, confirmed or dismissed. A task
  created from a confirmed action is found by `record_id` (this row is its provenance).

No foreign key into `meetings` or `tasks` (they stay untouched), so this revision can be undone without losing any meeting, transcript or task (see `rollback-032.sql` and
`downgrade`; created tasks stay). One trigger tells the knowledge index (Phase 44) that a meeting's retrievable text changed when an item is written; it only enqueues the existing
outbox row. It first removes any earlier copy of its own objects, so it can be applied again after a restore."""
from alembic import op

revision = "032_meeting_analysis"
down_revision = "031_documents"

_DROP_SQL = [
    "DROP TABLE IF EXISTS meeting_analysis_items",
    "DROP TABLE IF EXISTS meeting_analysis_runs",
    "DROP FUNCTION IF EXISTS meeting_analysis_knowledge_trg() CASCADE",
]

_SQL = [
    """CREATE TABLE meeting_analysis_runs (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        meeting_title TEXT NOT NULL,
        transcript_hash TEXT NOT NULL,
        segments JSONB NOT NULL,
        meeting_started_at TIMESTAMPTZ,
        timezone TEXT NOT NULL,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        project_scope TEXT,
        status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'succeeded', 'failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        model TEXT,
        reprocess BOOLEAN NOT NULL DEFAULT FALSE,
        item_count INTEGER NOT NULL DEFAULT 0,
        rejected JSONB NOT NULL DEFAULT '{}',
        inputs_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        lease_until TIMESTAMPTZ
    )""",
    "CREATE UNIQUE INDEX meeting_analysis_runs_one_active ON meeting_analysis_runs (meeting_id) WHERE status IN ('queued', 'processing')",
    "CREATE INDEX meeting_analysis_runs_meeting ON meeting_analysis_runs (meeting_id, created_at)",
    "CREATE INDEX meeting_analysis_runs_status ON meeting_analysis_runs (status, created_at)",
    """CREATE TABLE meeting_analysis_items (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        meeting_id TEXT NOT NULL,
        transcript_hash TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('decision', 'open_question', 'action')),
        text TEXT NOT NULL CHECK (text <> ''),
        evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0),
        assignee TEXT,
        stated_time TEXT,
        due_at TIMESTAMPTZ,
        ambiguity JSONB NOT NULL DEFAULT '[]',
        support TEXT NOT NULL DEFAULT 'uncertain' CHECK (support IN ('stated', 'uncertain')),
        status TEXT NOT NULL CHECK (status IN ('pending', 'accepting', 'accepted', 'dismissed', 'noted')),
        fingerprint TEXT NOT NULL,
        model TEXT,
        prompt_version TEXT NOT NULL,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        project_scope TEXT,
        final_text TEXT,
        edited BOOLEAN NOT NULL DEFAULT FALSE,
        record_kind TEXT,
        record_id TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        accepting_at TIMESTAMPTZ,
        decided_at TIMESTAMPTZ
    )""",
    "CREATE UNIQUE INDEX meeting_analysis_items_fingerprint ON meeting_analysis_items (meeting_id, fingerprint)",
    "CREATE UNIQUE INDEX meeting_analysis_items_record ON meeting_analysis_items (record_id) WHERE record_id IS NOT NULL",
    "CREATE INDEX meeting_analysis_items_meeting ON meeting_analysis_items (meeting_id, created_at)",
    "CREATE INDEX meeting_analysis_items_status ON meeting_analysis_items (status)",
    # The knowledge index shows decisions, open questions and accepted actions: any write to an item re-queues its meeting (the existing outbox function; nothing else is touched).
    """CREATE FUNCTION meeting_analysis_knowledge_trg() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            PERFORM knowledge_enqueue('meeting', OLD.meeting_id);
            RETURN OLD;
        END IF;
        PERFORM knowledge_enqueue('meeting', NEW.meeting_id);
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER meeting_analysis_knowledge AFTER INSERT OR DELETE OR UPDATE OF text, status, final_text, evidence, sensitivity, project_scope
        ON meeting_analysis_items FOR EACH ROW EXECUTE FUNCTION meeting_analysis_knowledge_trg()""",
]


def upgrade():
    bind = op.get_bind()
    for statement in (*_DROP_SQL, *_SQL):
        bind.exec_driver_sql(statement)


def downgrade():
    bind = op.get_bind()
    for statement in _DROP_SQL:
        bind.exec_driver_sql(statement)
