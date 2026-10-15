-- Undo migration 036_meeting_email without a restore. It added columns to `email_drafts`, the tables `email_draft_attachments`, `email_draft_events`, `mail_sender` and
-- `meeting_recipient_groups`, and stores the dedicated sender's credential as a row in `secrets` (provider `mail-sender`).
-- THIS SCRIPT DELETES: every meeting-minutes draft (queued ones included, so none can be sent as a plain draft to its first recipient only), all attachments and event history,
-- the sender configuration, the saved recipient groups and the sender's stored credential. Plain conversational drafts, received mail and every meeting are untouched.
-- A message already SENT stays sent; only our record of it is lost. Take the dump first and keep it.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-036.sql
-- Afterwards the database is at 035_meeting_speaker_identity and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 035_meeting_speaker_identity.
DELETE FROM email_drafts WHERE kind = 'meeting_minutes';
DELETE FROM secrets WHERE provider = 'mail-sender';
DROP TABLE IF EXISTS meeting_recipient_groups;
DROP TABLE IF EXISTS mail_sender;
DROP TABLE IF EXISTS email_draft_events;
DROP TABLE IF EXISTS email_draft_attachments;
DROP INDEX IF EXISTS email_drafts_due;
ALTER TABLE email_drafts DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS recipients, DROP COLUMN IF EXISTS source, DROP COLUMN IF EXISTS package_hash,
    DROP COLUMN IF EXISTS approved_hash, DROP COLUMN IF EXISTS message_id, DROP COLUMN IF EXISTS sender, DROP COLUMN IF EXISTS attempts,
    DROP COLUMN IF EXISTS claimed_at, DROP COLUMN IF EXISTS last_error, DROP COLUMN IF EXISTS provider_response;
UPDATE alembic_version SET version_num = '035_meeting_speaker_identity' WHERE version_num = '036_meeting_email';
SELECT version_num FROM alembic_version;
