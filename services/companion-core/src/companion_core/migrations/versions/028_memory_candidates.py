"""Phase 44F (docs/phase-44.md section 3.1, docs/phase-44f-implementation-proposal.md): memory candidates.

A candidate is a proposal that does nothing until the owner accepts it; it is not memory. These tables are read only by the review code and the
retention job: no trigger, no foreign key into `memories` or the knowledge index, nothing in recall, retrieval, context bundles or prompts.

* `memory_candidates` - the text exists only while a candidate is `pending` or `accepting` (a CHECK constraint makes it structurally impossible to keep
  candidate text after a rejection, suppression or acceptance). Digests are keyed (HMAC with a key from the service keyring), never plain hashes.
* `memory_candidate_suppressions` - keyed digests only, no text.
* `memory_candidate_counters` - hourly counts by kind (rate limits and retention statistics), no text.
* one partial unique index on `memories(source)` for `candidate:<id>` sources: a candidate can become at most one memory even if accept is retried,
  double-clicked or interrupted by a crash. The index only constrains rows that already use that source form (none exist before 44F).

Authoritative data is untouched, so this revision can be undone without losing any memory (see `rollback-028.sql` and `downgrade`; accepted memories stay),
and it can be applied again after a restore: it first removes any earlier copy of its own objects."""
from alembic import op

revision = "028_memory_candidates"
down_revision = "027_knowledge_index"

_DROP_SQL = [
    "DROP INDEX IF EXISTS memories_candidate_source_uq",
    "DROP TABLE IF EXISTS memory_candidate_counters",
    "DROP TABLE IF EXISTS memory_candidate_suppressions",
    "DROP TABLE IF EXISTS memory_candidates",
]

_TABLE_SQL = [
    """CREATE TABLE memory_candidates (
        id TEXT PRIMARY KEY,
        text TEXT CHECK (text IS NULL OR char_length(text) <= 400),
        rule_id TEXT NOT NULL,
        rule_version INTEGER NOT NULL,
        conversation_id TEXT,
        session_id TEXT,
        turn_index INTEGER,
        channel TEXT NOT NULL,
        proposed_type TEXT NOT NULL CHECK (proposed_type IN ('profile', 'working', 'episodic')),
        proposed_scope TEXT,
        sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public', 'work-private', 'sensitive')),
        status TEXT NOT NULL CHECK (status IN ('pending', 'accepting', 'accepted', 'edited-accepted', 'rejected', 'expired', 'suppressed')),
        digest TEXT NOT NULL,
        digest_key_id TEXT NOT NULL,
        memory_id TEXT,
        edited BOOLEAN NOT NULL DEFAULT FALSE,
        expires_memory_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        accepting_at TIMESTAMPTZ,
        decided_at TIMESTAMPTZ,
        CONSTRAINT memory_candidates_text_only_while_open CHECK ((status IN ('pending', 'accepting')) = (text IS NOT NULL)),
        CONSTRAINT memory_candidates_accepted_has_memory CHECK (status NOT IN ('accepted', 'edited-accepted') OR memory_id IS NOT NULL)
    )""",
    "CREATE INDEX memory_candidates_status ON memory_candidates (status, expires_at)",
    "CREATE INDEX memory_candidates_digest ON memory_candidates (digest_key_id, digest)",
    "CREATE INDEX memory_candidates_conversation ON memory_candidates (conversation_id)",
    """CREATE TABLE memory_candidate_suppressions (
        digest_key_id TEXT NOT NULL,
        digest TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (digest_key_id, digest)
    )""",
    """CREATE TABLE memory_candidate_counters (
        hour TIMESTAMPTZ NOT NULL,
        kind TEXT NOT NULL,
        n INTEGER NOT NULL CHECK (n >= 0),
        PRIMARY KEY (hour, kind)
    )""",
    "CREATE UNIQUE INDEX memories_candidate_source_uq ON memories (source) WHERE left(source, 10) = 'candidate:'",
]


def upgrade():
    conn = op.get_bind()
    for statement in [*_DROP_SQL, *_TABLE_SQL]:
        conn.exec_driver_sql(statement)


def downgrade():
    conn = op.get_bind()
    for statement in _DROP_SQL:
        conn.exec_driver_sql(statement)
