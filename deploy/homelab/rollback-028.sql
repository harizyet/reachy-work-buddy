-- Undo migration 028_memory_candidates (Phase 44F) without a restore. It created only candidate bookkeeping (proposals, suppression digests, counters) and one
-- partial unique index on memories(source) for 'candidate:%' sources. Memories the owner accepted from candidates STAY: they are ordinary memories whose
-- source string merely names the candidate. Run with the application services stopped, as one transaction:
--   docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < rollback-028.sql
-- Afterwards the database is at 027_knowledge_index and the previous images run against it. The migration job refuses to run while the revision is wrong,
-- so check the final line prints 027_knowledge_index.
DROP INDEX IF EXISTS memories_candidate_source_uq;
DROP TABLE IF EXISTS memory_candidate_counters;
DROP TABLE IF EXISTS memory_candidate_suppressions;
DROP TABLE IF EXISTS memory_candidates;
UPDATE alembic_version SET version_num = '027_knowledge_index' WHERE version_num = '028_memory_candidates';
SELECT version_num FROM alembic_version;
