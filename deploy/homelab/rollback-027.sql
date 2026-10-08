-- Undo migration 027_knowledge_index (Phase 44B) without a restore. It created only derived data (the knowledge index, its outbox and
-- the triggers that fill the outbox), so dropping it loses nothing authoritative; the index is rebuilt from the stores if 027 is
-- applied again. Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-027.sql
-- Afterwards the database is at 026_source_sensitivity and the previous images run against it. The migration job refuses to run
-- while the revision is wrong, so check the final line prints 026_source_sensitivity.
DROP FUNCTION IF EXISTS knowledge_memories_trg() CASCADE;
DROP FUNCTION IF EXISTS knowledge_chunks_trg() CASCADE;
DROP FUNCTION IF EXISTS knowledge_meetings_trg() CASCADE;
DROP FUNCTION IF EXISTS knowledge_notes_trg() CASCADE;
DROP FUNCTION IF EXISTS knowledge_tasks_trg() CASCADE;
DROP FUNCTION IF EXISTS knowledge_reminders_trg() CASCADE;
DROP FUNCTION IF EXISTS knowledge_enqueue(TEXT, TEXT);
DROP TABLE IF EXISTS knowledge_outbox;
DROP TABLE IF EXISTS knowledge_items;
UPDATE alembic_version SET version_num = '026_source_sensitivity' WHERE version_num = '027_knowledge_index';
SELECT version_num FROM alembic_version;
