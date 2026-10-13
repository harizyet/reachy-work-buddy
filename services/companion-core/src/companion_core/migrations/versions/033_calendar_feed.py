"""Calendar feed (ADR 0035): the owner's read-only ICS feed.

One table, one row (`id = 'owner'`):

* `secret_ref` - a reference into the encrypted `secrets` table. The feed URL is a bearer secret and is never stored here.
* `config` - refresh interval, reminder lead time, horizon and the classification rules.
* `overrides` - the owner's classification of an occurrence or series, by event key.
* `snapshot` - the facts of the last good download (titles, times, attendee addresses; never a description), replaced whole on each success.
* `status` - last attempt and success times, a fixed error code, and the host (not the path) of the URL.

Nothing else changes: `calendar_events` and `secrets` are untouched. Undo with `rollback-033.sql`, which also deletes the feed URL's secret row. The CREATE is guarded, so applying it
again after a restore is safe."""
from alembic import op

revision = "033_calendar_feed"
down_revision = "032_meeting_analysis"

_SQL = [
    """CREATE TABLE IF NOT EXISTS calendar_feed (
        id TEXT PRIMARY KEY CHECK (id = 'owner'),
        secret_ref TEXT,
        config JSONB NOT NULL DEFAULT '{}',
        overrides JSONB NOT NULL DEFAULT '{}',
        snapshot JSONB,
        status JSONB NOT NULL DEFAULT '{}'
    )""",
    "INSERT INTO calendar_feed (id) VALUES ('owner') ON CONFLICT (id) DO NOTHING",
]


def upgrade():
    bind = op.get_bind()
    for statement in _SQL:
        bind.exec_driver_sql(statement)


def downgrade():
    bind = op.get_bind()
    bind.exec_driver_sql("DELETE FROM secrets WHERE provider = 'ics' AND purpose = 'feed-url'")
    bind.exec_driver_sql("DROP TABLE IF EXISTS calendar_feed")
