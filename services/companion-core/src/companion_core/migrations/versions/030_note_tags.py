"""Note tags: an optional folder path on each note (shared/models/note_tag.py), e.g. "Projects/Project StarWars/Finance". NULL means directly in All Notes.

One nullable column and nothing else: no trigger change (the knowledge index does not carry the tag; the existing trigger watches title, body and classification), no index, existing
notes stay untagged. Undo with `rollback-030.sql` (it drops only the column, so the tags are lost but no note, title or text is). Safe to apply again after a restore."""
from alembic import op

revision = "030_note_tags"
down_revision = "029_notepad_processing"


def upgrade():
    op.get_bind().exec_driver_sql("ALTER TABLE notes ADD COLUMN IF NOT EXISTS tag TEXT")


def downgrade():
    op.get_bind().exec_driver_sql("ALTER TABLE notes DROP COLUMN IF EXISTS tag")
