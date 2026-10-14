"""Phase 53 (docs/phase-53.md, ADR 0037): multimodal meeting intelligence.

* `meeting_document_links` - a document attached to a meeting. A pair of existing ids, nothing more: no copy of either source. Unique per (meeting, document), so attaching twice is one row.
* `meeting_multimodal_runs` - one row per alignment or combined-analysis request. It holds hashes of what it will read (the transcript and the documents' revisions), never their text. A
  partial unique index allows at most one queued or processing run per meeting and kind.
* `meeting_slide_alignments` - the CURRENT estimate for each transcript window: which page (if any) it was about, the certainty, the alternatives, the reason and the revisions of both
  sources it was derived from. Replaced as a set by the next alignment run. A model estimate, not a fact about what was displayed.
* `meeting_slide_reviews` - the owner's own decision for a window, kept apart so a rerun can never overwrite it.
* `meeting_multimodal_items` - combined findings (discussion points, decisions, disagreements, open questions, action candidates) with verified transcript and/or document quotes. They are
  NOT tasks or memories; a task is made only when the owner confirms an action (found again by `record_id`).

No foreign key into `meetings`, `documents` or `tasks`, so this revision can be undone without losing any meeting, document, recording or task (see `rollback-034.sql`; tasks already
created stay). Nothing here is indexed for retrieval, so there is no knowledge-outbox trigger. The upgrade first removes any earlier copy of its own objects, so it can be applied again
after a restore."""
from alembic import op

revision = "034_meeting_multimodal"
down_revision = "033_calendar_feed"

_DROP_SQL = [
    "DROP TABLE IF EXISTS meeting_multimodal_items",
    "DROP TABLE IF EXISTS meeting_slide_reviews",
    "DROP TABLE IF EXISTS meeting_slide_alignments",
    "DROP TABLE IF EXISTS meeting_multimodal_runs",
    "DROP TABLE IF EXISTS meeting_document_links",
]

_SQL = [
    """CREATE TABLE meeting_document_links (
        meeting_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        link_status TEXT NOT NULL DEFAULT 'linked' CHECK (link_status IN ('linked')),
        linked_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (meeting_id, document_id)
    )""",
    "CREATE INDEX meeting_document_links_document ON meeting_document_links (document_id)",
    """CREATE TABLE meeting_multimodal_runs (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('alignment', 'analysis')),
        status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'succeeded', 'failed')),
        ceiling TEXT NOT NULL CHECK (ceiling IN ('public', 'work-private', 'sensitive')),
        transcript_hash TEXT NOT NULL,
        doc_revisions JSONB NOT NULL DEFAULT '{}',
        inputs_hash TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        model TEXT,
        force BOOLEAN NOT NULL DEFAULT FALSE,
        stats JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        lease_until TIMESTAMPTZ
    )""",
    "CREATE UNIQUE INDEX meeting_multimodal_runs_one_active ON meeting_multimodal_runs (meeting_id, kind) WHERE status IN ('queued', 'processing')",
    "CREATE INDEX meeting_multimodal_runs_meeting ON meeting_multimodal_runs (meeting_id, kind, created_at)",
    "CREATE INDEX meeting_multimodal_runs_status ON meeting_multimodal_runs (status, created_at)",
    """CREATE TABLE meeting_slide_alignments (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        meeting_id TEXT NOT NULL,
        window_key TEXT NOT NULL,
        segment_ids JSONB NOT NULL,
        start_s DOUBLE PRECISION NOT NULL,
        end_s DOUBLE PRECISION NOT NULL,
        document_id TEXT,
        page INTEGER,
        locator TEXT,
        slide_title TEXT,
        alternatives JSONB NOT NULL DEFAULT '[]',
        certainty TEXT NOT NULL CHECK (certainty IN ('high', 'medium', 'low', 'unknown')),
        method TEXT NOT NULL CHECK (method IN ('explicit_reference', 'semantic', 'none')),
        relation TEXT NOT NULL CHECK (relation IN ('supports', 'contradicts', 'unresolved')),
        reason TEXT NOT NULL DEFAULT '',
        model_note TEXT,
        shared_terms JSONB NOT NULL DEFAULT '[]',
        explicit_refs JSONB NOT NULL DEFAULT '[]',
        contradictions JSONB NOT NULL DEFAULT '[]',
        unchecked BOOLEAN NOT NULL DEFAULT FALSE,
        transcript_revision TEXT NOT NULL,
        document_revision TEXT NOT NULL DEFAULT '',
        analysis_version TEXT NOT NULL,
        model TEXT,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        project_scope TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        CHECK ((document_id IS NULL) = (page IS NULL))
    )""",
    "CREATE UNIQUE INDEX meeting_slide_alignments_window ON meeting_slide_alignments (meeting_id, window_key)",
    "CREATE INDEX meeting_slide_alignments_document ON meeting_slide_alignments (document_id) WHERE document_id IS NOT NULL",
    """CREATE TABLE meeting_slide_reviews (
        meeting_id TEXT NOT NULL,
        window_key TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('confirmed', 'replaced', 'no_slide', 'removed')),
        document_id TEXT,
        page INTEGER,
        rejected_document_id TEXT,
        rejected_page INTEGER,
        transcript_revision TEXT NOT NULL,
        document_revision TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (meeting_id, window_key)
    )""",
    """CREATE TABLE meeting_multimodal_items (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        meeting_id TEXT NOT NULL,
        transcript_hash TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('discussion', 'decision', 'disagreement', 'open_question', 'action')),
        text TEXT NOT NULL CHECK (text <> ''),
        evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0),
        assignee TEXT,
        stated_time TEXT,
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
    "CREATE UNIQUE INDEX meeting_multimodal_items_fingerprint ON meeting_multimodal_items (meeting_id, fingerprint)",
    "CREATE UNIQUE INDEX meeting_multimodal_items_record ON meeting_multimodal_items (record_id) WHERE record_id IS NOT NULL",
    "CREATE INDEX meeting_multimodal_items_meeting ON meeting_multimodal_items (meeting_id, created_at)",
    "CREATE INDEX meeting_multimodal_items_status ON meeting_multimodal_items (status)",
]


def upgrade():
    bind = op.get_bind()
    for statement in (*_DROP_SQL, *_SQL):
        bind.exec_driver_sql(statement)


def downgrade():
    bind = op.get_bind()
    for statement in _DROP_SQL:
        bind.exec_driver_sql(statement)
