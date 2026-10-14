-- Undo migration 037_processing_provenance without a restore. It added `meetings.processing_events` (the record of where each processing step ran) and `mail_sender.owner_name`.
-- Dropping them loses only that provenance record and the name used in outbound meeting email; no meeting, transcript, recording, summary or draft is touched. Meeting-minutes drafts prepared
-- while this migration was applied carry their disclosure text in their own stored source and are NOT removed, but the previous images do not know how to render it: cancel or discard any
-- unsent meeting-minutes draft before rolling back, and do not roll back while one is queued.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-037.sql
-- Afterwards the database is at 036_meeting_email and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 036_meeting_email.
ALTER TABLE mail_sender DROP COLUMN IF EXISTS owner_name;
ALTER TABLE meetings DROP COLUMN IF EXISTS processing_events;
UPDATE alembic_version SET version_num = '036_meeting_email' WHERE version_num = '037_processing_provenance';
SELECT version_num FROM alembic_version;
