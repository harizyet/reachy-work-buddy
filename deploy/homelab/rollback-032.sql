-- Undo migration 032_meeting_analysis without a restore. It added only `meeting_analysis_runs`, `meeting_analysis_items` and one trigger function that enqueues the knowledge outbox.
-- Dropping them loses the generated analysis (decisions, open questions, action candidates and their review state), not any meeting, transcript or recording. A task created from a
-- confirmed action stays (it is the owner's record); only its link back to the meeting item is lost. The analysis can be regenerated.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-032.sql
-- Afterwards the database is at 031_documents and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 031_documents.
DROP TABLE IF EXISTS meeting_analysis_items;
DROP TABLE IF EXISTS meeting_analysis_runs;
DROP FUNCTION IF EXISTS meeting_analysis_knowledge_trg() CASCADE;
UPDATE alembic_version SET version_num = '031_documents' WHERE version_num = '032_meeting_analysis';
SELECT version_num FROM alembic_version;
