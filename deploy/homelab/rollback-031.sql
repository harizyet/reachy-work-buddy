-- Undo migration 031_documents without a restore. It added only the `documents` table (the catalogue of uploaded documents) and `document_outputs` (summaries derived from them). Dropping them loses that catalogue and the summaries (regenerable), not the originals: the files in the
-- document source store on disk are not touched, and no note, task, reminder or meeting is affected. The originals can be re-registered by uploading them again.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-031.sql
-- Afterwards the database is at 030_note_tags and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 030_note_tags.
DROP TABLE IF EXISTS document_outputs;
DROP TABLE IF EXISTS documents;
UPDATE alembic_version SET version_num = '030_note_tags' WHERE version_num = '031_documents';
SELECT version_num FROM alembic_version;
