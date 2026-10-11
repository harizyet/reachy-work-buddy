-- Undo migration 029_notepad_processing (Phase 49) without a restore. It created only processing bookkeeping (jobs with note and transcript snapshots, proposals, provenance links, note-to-meeting links).
-- Notes, tasks and reminders are untouched, and tasks or reminders the owner accepted from proposals STAY: they are ordinary records (only the link back to the proposal is
-- dropped). Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-029.sql
-- Afterwards the database is at 028_memory_candidates and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 028_memory_candidates.
DROP TABLE IF EXISTS note_meeting_links;
DROP TABLE IF EXISTS notepad_provenance;
DROP TABLE IF EXISTS notepad_proposals;
DROP TABLE IF EXISTS notepad_jobs;
UPDATE alembic_version SET version_num = '028_memory_candidates' WHERE version_num = '029_notepad_processing';
SELECT version_num FROM alembic_version;
