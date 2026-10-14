-- Undo migration 034_meeting_multimodal without a restore. It added only `meeting_document_links`, `meeting_multimodal_runs`, `meeting_slide_alignments`, `meeting_slide_reviews` and
-- `meeting_multimodal_items` (no trigger, no function, no change to any existing table). Dropping them loses the attachments, the page estimates, the owner's slide corrections and the
-- combined findings (not any meeting, transcript, recording or document). A task created from a confirmed action stays (it is the owner's record); only its link back to the finding is
-- lost. Everything except the owner's corrections can be regenerated.
-- Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-034.sql
-- Afterwards the database is at 033_calendar_feed and the previous images run against it. The migration job refuses to run while the revision is wrong, so check
-- the final line prints 033_calendar_feed.
DROP TABLE IF EXISTS meeting_multimodal_items;
DROP TABLE IF EXISTS meeting_slide_reviews;
DROP TABLE IF EXISTS meeting_slide_alignments;
DROP TABLE IF EXISTS meeting_multimodal_runs;
DROP TABLE IF EXISTS meeting_document_links;
UPDATE alembic_version SET version_num = '033_calendar_feed' WHERE version_num = '034_meeting_multimodal';
SELECT version_num FROM alembic_version;
