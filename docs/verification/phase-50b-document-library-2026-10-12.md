# Phase 50B: Reachy document ownership (2026-10-12)

Owner decision 2026-10-12: close 50A with the PNG/JPEG test, then build 50B; do not deploy the worker to Proxmox yet (that moves to the first integrated deployment gate after 50C). **Built locally; nothing deployed, no flag set in production, migration 031 not applied anywhere but disposable containers.**

## What exists

* `companion_core/document_library/`: `models.py` (Document, states `uploaded/queued/processing/ready/partial/failed/deleting`, priorities), `source_store.py` (content-addressed, write-once, re-verified), `store.py` and `postgres_store.py`, `service.py`, `routes.py`, `worker_client.py` (Reachy's client for the document worker, 50A contract).
* `031_documents` migration and `deploy/homelab/rollback-031.sql`; `SCHEMA_REVISION` is `031_documents`.
* Shared: `shared/protocols/document_library_api.py`, `shared/models/document_library.py`.
* Wiring in `create_app` behind `DOCUMENT_LIBRARY_ENABLED` (default off); compose passes the flag, `DOCUMENT_SOURCE_DIR`, worker URL and token, and the new volume `document-source`. Reference: [services](../reference/services.md#document-library-phase-50b-50c), [deployment](../deployment.md#document-library-phase-50b).

## Design points

* Policy identity is the Reachy document id. Identical bytes are two documents with their own sensitivity and project and one blob; the blob is removed only when no document references its hash. `backend_ref` is an opaque, shared pointer.
* Sensitivity and project scope come from the owner's request (default `work-private`, the system-wide default for owner records); nothing derived from content sets or lowers them (ADR 0034). State and hash are not editable.
* Type is decided by content and must agree with the extension (pdf, png, jpg, docx; a docx must contain `word/document.xml`); the byte limit is checked while streaming; a rejected upload commits nothing.
* Every content access starts from `require_usable`: the record exists, is not `deleting`, and the original still matches its hash (mismatch is 409 and logged by id only).
* Deletion: `deleting` first (unusable, cannot be revived), then the worker forgets it and must report `verified`, then record, then blob if unshared. A worker that cannot confirm leaves the document `deleting` with a 502, and `finish_deletions()` retries at startup.
* `/documents` (older text-RAG ingest) is untouched; the new routes are `/document-library/...`.

## Verification

* **Mock level / in-process (18 tests, `test_document_library.py`):** source store (hash addressing, write-once, tamper and loss detection, oversize, wrong type, empty, hash-name validation), flag off means nothing exists, upload defaults and owner classification, rejection by content, byte limit, identical-bytes policy separation and blob lifetime, metadata rules, fail-closed on tamper and on `deleting`, 404s, and deletion through the **real document worker app over an ASGI chain** with a fake engine that reproduces the 50A spike behaviours (shared object survives deleting one of two identical documents; unconfirmed deletion retried), plus the client's error reduction (no message or path leaks).
* **Real PostgreSQL (disposable `pgvector/pgvector:pg16` container, removed):** migration 031 structure (no trigger, no foreign key, check constraints, identical hashes allowed), rollback script, re-apply, the real store including the no-revival guarantee; the three earlier opt-in suites were updated for the new head (rollback chain now starts at 031) and pass: 62 passed, 1 skipped.
* Full unit run (`pytest services shared`): 3,015 passed, 140 skipped, 5 failed, all five pre-existing and unrelated (`test_knowledge_index` reconcile, `test_knowledge_retrieval` historical mode, hub `test_robot_voice`, embodiment `test_wake` timing, hub `test_web_client` sample ordering `[]|['int']`; the last reproduced with these changes stashed). Ruff clean.

## Not done (by design)

No hub proxy or UI (50J); no ingestion into the worker, status polling, reprocess, reading or search (50C and later); the worker is not deployed; the real source-store volume, its backup and a restore test happen at the 50C deployment gate; no deployment of core with the volume. The hub does not yet expose these routes, so only the service-token path reaches them.
