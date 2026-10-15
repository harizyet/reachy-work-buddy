-- Undo migration 038_voice_profiles (shared voice identity, ADR 0041) without a restore. It added the `voice_profiles` table; nothing else references it.
-- Dropping it DELETES every enrolled voice profile (encrypted templates): the owner re-enrols after an upgrade. No meeting, chat or account data is touched.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-038.sql
-- Afterwards the database is at 037_processing_provenance and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 037_processing_provenance.
DROP TABLE IF EXISTS voice_profiles;
UPDATE alembic_version SET version_num = '037_processing_provenance' WHERE version_num = '038_voice_profiles';
SELECT version_num FROM alembic_version;
