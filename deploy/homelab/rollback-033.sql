-- Undo migration 033_calendar_feed without a restore. It added only the calendar_feed table (the feed settings, overrides and last snapshot). This also deletes the encrypted feed URL
-- from the secrets table, so no copy of the URL remains. Local calendar events, the Google account and every other secret are untouched.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-033.sql
-- Afterwards the database is at 032_meeting_analysis and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 032_meeting_analysis.
DELETE FROM secrets WHERE provider = 'ics' AND purpose = 'feed-url';
DROP TABLE IF EXISTS calendar_feed;
UPDATE alembic_version SET version_num = '032_meeting_analysis' WHERE version_num = '033_calendar_feed';
SELECT version_num FROM alembic_version;
