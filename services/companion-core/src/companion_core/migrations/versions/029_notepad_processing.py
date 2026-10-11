"""Phase 49 (docs/phase-49.md): optional Notepad processing.

* `notepad_jobs` - one row per processing request. It holds the immutable snapshot of the note (text, SHA-256, the note's `updated_at`), so extraction never depends on
  what the note says later. A partial unique index allows at most one queued or processing job per note.
* `notepad_proposals` - source-backed proposals extracted from a snapshot. They are NOT tasks, reminders or memories and nothing else reads them as such. A unique
  (note_id, fingerprint) pair means reprocessing a note can never bring back a sentence already proposed, accepted or dismissed.
* `note_meeting_links` - associates a note with a recorded meeting (explicit, or suggested from time overlap and confirmed or rejected by the owner). One row per
  note and meeting pair; nothing is copied and neither record is changed, so removing a link deletes nothing else.
* `notepad_proposal_notes` - every note that found a proposal, with that note's snapshot hash. A transcript passage (meeting, segment stamp, quote) yields one proposal however many linked notes find it (unique `source_key`); each of those notes stays tied to it here.
* `notepad_provenance` - links a task or reminder created from an accepted proposal back to its note, snapshot hash and proposal. One row per record and one per proposal.

No foreign key into `notes`, `tasks` or `reminders` (they stay untouched; a deleted note leaves its history), no trigger, nothing in the knowledge index. Authoritative
data is not changed, so this revision can be undone without losing any task, reminder or note (see `rollback-029.sql` and `downgrade`; created tasks and reminders stay). It
first removes any earlier copy of its own objects, so it can be applied again after a restore."""
from alembic import op

revision = "029_notepad_processing"
down_revision = "028_memory_candidates"

_DROP_SQL = [
    "DROP TABLE IF EXISTS notepad_proposal_notes",
    "DROP TABLE IF EXISTS note_meeting_links",
    "DROP TABLE IF EXISTS notepad_provenance",
    "DROP TABLE IF EXISTS notepad_proposals",
    "DROP TABLE IF EXISTS notepad_jobs",
]

_TABLE_SQL = [
    """CREATE TABLE notepad_jobs (
        id TEXT PRIMARY KEY,
        note_id TEXT NOT NULL,
        note_title TEXT NOT NULL,
        snapshot_text TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        note_updated_at TIMESTAMPTZ NOT NULL,
        timezone TEXT NOT NULL,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        project_scope TEXT,
        status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'succeeded', 'failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        model TEXT,
        reprocess BOOLEAN NOT NULL DEFAULT FALSE,
        proposal_count INTEGER NOT NULL DEFAULT 0,
        inputs_hash TEXT NOT NULL,
        sources JSONB NOT NULL DEFAULT '[]',
        created_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        lease_until TIMESTAMPTZ
    )""",
    "CREATE UNIQUE INDEX notepad_jobs_one_active_per_note ON notepad_jobs (note_id) WHERE status IN ('queued', 'processing')",
    "CREATE INDEX notepad_jobs_note ON notepad_jobs (note_id, created_at)",
    "CREATE INDEX notepad_jobs_status ON notepad_jobs (status, created_at)",
    """CREATE TABLE notepad_proposals (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('task', 'reminder', 'event', 'reference')),
        text TEXT NOT NULL,
        evidence TEXT NOT NULL CHECK (evidence <> ''),
        span_start INTEGER NOT NULL,
        span_end INTEGER NOT NULL,
        sources JSONB NOT NULL DEFAULT '[]',
        evidence_from TEXT NOT NULL CHECK (evidence_from IN ('note', 'transcript', 'both')),
        source_key TEXT,
        stated_time TEXT,
        due_at TIMESTAMPTZ,
        ambiguity JSONB NOT NULL DEFAULT '[]',
        status TEXT NOT NULL CHECK (status IN ('pending', 'accepting', 'accepted', 'dismissed', 'noted')),
        fingerprint TEXT NOT NULL,
        model TEXT,
        prompt_version TEXT NOT NULL,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        project_scope TEXT,
        final_kind TEXT,
        final_text TEXT,
        final_due_at TIMESTAMPTZ,
        edited BOOLEAN NOT NULL DEFAULT FALSE,
        record_kind TEXT,
        record_id TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        accepting_at TIMESTAMPTZ,
        decided_at TIMESTAMPTZ,
        CONSTRAINT notepad_proposals_accepted_has_record CHECK (status <> 'accepted' OR kind = 'event' OR final_kind = 'event' OR record_id IS NOT NULL)
    )""",
    "CREATE UNIQUE INDEX notepad_proposals_fingerprint ON notepad_proposals (note_id, fingerprint)",
    # One proposal per transcript passage (meeting id, segment stamp, quote), whichever note's job found it.
    "CREATE UNIQUE INDEX notepad_proposals_source_key ON notepad_proposals (source_key) WHERE source_key IS NOT NULL",
    "CREATE INDEX notepad_proposals_status ON notepad_proposals (status, created_at)",
    "CREATE INDEX notepad_proposals_note ON notepad_proposals (note_id, created_at)",
    """CREATE TABLE notepad_proposal_notes (
        proposal_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (proposal_id, note_id)
    )""",
    "CREATE INDEX notepad_proposal_notes_note ON notepad_proposal_notes (note_id)",
    """CREATE TABLE notepad_provenance (
        record_kind TEXT NOT NULL CHECK (record_kind IN ('task', 'reminder')),
        record_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        proposal_id TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (record_kind, record_id),
        UNIQUE (proposal_id)
    )""",
    """CREATE TABLE note_meeting_links (
        id TEXT PRIMARY KEY,
        note_id TEXT NOT NULL,
        meeting_id TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('explicit', 'temporal')),
        state TEXT NOT NULL CHECK (state IN ('suggested', 'confirmed', 'rejected')),
        overlap_seconds INTEGER,
        title_match BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        decided_at TIMESTAMPTZ,
        UNIQUE (note_id, meeting_id),
        CONSTRAINT note_meeting_links_explicit_is_confirmed CHECK (source <> 'explicit' OR state <> 'suggested')
    )""",
    "CREATE INDEX note_meeting_links_meeting ON note_meeting_links (meeting_id)",
]


def upgrade():
    conn = op.get_bind()
    for statement in [*_DROP_SQL, *_TABLE_SQL]:
        conn.exec_driver_sql(statement)


def downgrade():
    conn = op.get_bind()
    for statement in _DROP_SQL:
        conn.exec_driver_sql(statement)
