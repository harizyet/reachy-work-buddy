-- Undo migration 030_note_tags without a restore. It added only the nullable notes.tag column. Dropping it loses the owner's tags (folders) but no note, title or text.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-030.sql
-- Afterwards the database is at 029_notepad_processing and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 029_notepad_processing.
ALTER TABLE notes DROP COLUMN IF EXISTS tag;
UPDATE alembic_version SET version_num = '029_notepad_processing' WHERE version_num = '030_note_tags';
SELECT version_num FROM alembic_version;
