-- Undo migration 035_meeting_speaker_identity without a restore. It added one nullable column, `meetings.speaker_identity`, and changed no other table.
-- Dropping it loses only the owner's unknown/skipped decisions, contact references and the superseded-identity record; the names themselves live in `meetings.speaker_names`
-- (unchanged, still used by every reader) and stay. No meeting, transcript, recording or summary is touched.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-035.sql
-- Afterwards the database is at 034_meeting_multimodal and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 034_meeting_multimodal.
ALTER TABLE meetings DROP COLUMN IF EXISTS speaker_identity;
UPDATE alembic_version SET version_num = '034_meeting_multimodal' WHERE version_num = '035_meeting_speaker_identity';
SELECT version_num FROM alembic_version;
