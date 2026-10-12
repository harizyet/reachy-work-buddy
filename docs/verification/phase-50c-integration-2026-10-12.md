# Phase 50C: Reachy to document worker integration (2026-10-12)

Owner decision 2026-10-12: proceed with 50C as plumbing only (no hub or UI work), then stop at the integrated deployment gate for review. **Built and verified locally; nothing deployed, no production flag set.**

## What 50C adds (all in `companion_core/document_library/`, reference: [services](../reference/services.md#document-library-phase-50b-50c))

* Submission of the verified original to the worker at upload, state mapped `uploaded, queued, processing, ready, partial, failed` (`deleting` terminal from outside); the opaque `backend_ref`, `backend_revision` (the source hash), tier, page count and error code are stored.
* A sync loop (`sync_once`, `run_sync_loop`) that submits what the worker has not been given, follows non-terminal documents, re-gives a document to a worker that lost it from the authoritative original, and retries unconfirmed deletions. A worker that is down is transient; a refusal fails the document with a code.
* `POST .../reprocess` (same document, same original, only the rebuilt tier's cached parse dropped), and `read`, `locator`, `search` by Reachy document id with `title`, `source_hash` and `evidence_type: derived_extraction` on every output.
* Policy checked from the Reachy record (sensitivity ceiling, project scope, not `deleting`, original still matching its hash) before every worker call that reads content; the worker is never asked when the check fails.
* A per-document lock for submit, reprocess and delete; the legacy `/documents` routes are labelled legacy text-chunk RAG in code and docs (not merged, not renamed).

## Defects found by the real run, fixed

* **Reprocessing one document broke another with the same bytes.** With the real MinerU, invalidating all parses of a hash (the 50A engine call) removed the parse another Reachy document was using while it still said READY, and its reads failed. Fix: the worker invalidates only the tier being rebuilt, and a read the worker cannot serve with `not_ready` now corrects the stale state (it becomes queued/processing and the loop watches it). Regression test added.

## Verification

* **In-process (31 tests in `test_document_library.py`, 51 with the worker's):** lifecycle to ready, worker down then recovered, refusal then reprocess at another tier, reprocess of the same document, tampered original never sent, worker that lost its state rebuilt from the original, read/search/locator via the Reachy id, not-ready refusal, policy checks before every worker call (including identical bytes with different sensitivity and project scope), deleting documents neither synced nor readable, loop wiring, and the shared-bytes regression. Real PostgreSQL (disposable container, removed): `pending_sync` and the store, 3 passed.
* **Real engine, real HTTP (labelled: not a mock):** core in process (in-memory stores, real source store, real sync loop at 1 s) talking over HTTP to the real worker image running real MinerU (read-only, no capabilities, models read-only): uploads of a scanned PDF (project-scoped), a DOCX, a PNG and a sensitive twin of the scanned PDF all reached `ready` (OCR text and page counts correct); reads, scoped searches with page and locator, locator reads; the sensitive twin refused 403 while the same bytes at a lower class read fine; reprocess to Standard returned to ready and searched correctly; deleting one of two identical documents left the other readable by an access context with a sensitive ceiling; deleting everything left the catalogue empty, no originals on disk, and the worker with zero library rows and no working copies. The worker container and volume were removed.
* Ruff clean. Full suite run recorded in the HANDOVER entry.

## Integrated deployment gate

Not started; needs the owner's review and approval. Checklist (the concerns deliberately deferred from 50A/50B):

1. **Topology:** the document worker on the Proxmox host (CPU only, no GPU device, internal network only); core stays on the homelab host with the new `document-source` volume. Core must reach the worker over a private path (decide: tailnet address, LAN, or a published internal port) with `DOCUMENT_WORKER_URL`/`TOKEN`; the compose `documents` network is internal to one host, so cross-host needs an explicit, restricted route.
2. **Storage paths:** `reachy-source` (authoritative originals, Reachy's `document-source` volume) and `reachy-mineru` (worker `/data`: library, cache, working copies) as separate datasets; the model directory on the worker host (hashes in the [50A record](phase-50a-mineru-spike-2026-10-11.md)).
3. **Backup and restore:** source store and database included in backups; a restore test (delete the volume contents in a throwaway project, restore, verify hashes, re-sync rebuilds MinerU state).
4. **Schema:** migration `031_documents` (backup first, core + hub + coding-agent together, rollback script), flag `DOCUMENT_LIBRARY_ENABLED`.
5. **Operational checks:** CPU/RAM behaviour of Basic/Standard on the Proxmox worker with realistic documents (limits are provisional defaults), telemetry still disabled (`/health` requires it), no GPU exposure, then upload to process to read/search to reprocess to delete end to end, and the Phase 48 cohort boundary note (a core recreate is a boundary for the 48 cohorts).

Not in 50C: hub proxy, web or Android UI (50J), document-scoped conversation (50E), federated retrieval (50F), citations in replies (50G), summaries (50H), scheduler and GPU priority path (50I).

## Gate preparation done locally (2026-10-12, after the owner approved the topology and order)

Owner decisions: allow `sensitive` documents on trusted owner surfaces by channel-derived ceiling, not by route; companion-core, PostgreSQL and `document-source` stay on the MS-01; only the worker goes to Proxmox behind a firewall-restricted, token-authenticated path; originals and database are the mandatory backups, MinerU state is rebuildable; deploy and activate separately, in the owner's 13-step order.

* **Trusted ceiling:** the hub tells core the ceiling in `X-Reachy-Access-Ceiling` (core is reachable only with the service token); absent is `work-private`, unknown is 400; read, locator and search obey it. The hub side (mapping owner web/Android to `sensitive`, Telegram to its existing ceiling, voice and uncertain identity lower) is part of the hub proxy in 50J: nothing in the hub sets it yet, so today only the default applies. Test: `test_the_hub_sets_the_ceiling_per_channel_and_core_enforces_it`.
* **Worker host bundle** `deploy/document-worker/` (compose, `.env.example`, `models.sha256`, `verify-models.sh`, `verify-worker.sh`, README runbook with the firewall rule). Brought up locally from the bundle bound to 127.0.0.1: `verify-worker.sh` all 13 checks ok, and its negative control (an unhardened container) fails the relevant checks.
* **Gate drill** `tools/document_gate_drill.py`, run against that real worker with a throwaway PostgreSQL and source store: **the owner's duplicate-bytes scenario passed** (A work-private/Basic and B sensitive/Standard on one PDF: reprocess A leaves B valid, delete A leaves B valid and the original, delete B removes the original, the records and the worker's state), and **the restore scenario passed** (database and source store restored, worker state destroyed and a fresh worker started, both documents rebuilt READY from the restored originals).
* **Defects the drill found, fixed:** (1) the PostgreSQL store refused the `backend` field the service updates while the in-memory twin accepted it, so the whole upload path failed on a real database (both stores now share one allow-list, and a test runs the service lifecycle on the real store); (2) READY documents were never checked against the worker, so a worker restored from nothing left them stale (the loop now reconciles READY documents every `DOCUMENT_LIBRARY_RECONCILE_SECONDS`, and a read that finds the worker empty returns the document to the loop with a 409 instead of a server error).

## Gate status

* **Blocked at step 1** (prepare Proxmox storage and model cache): this session has no route to the Proxmox host (it is not on the tailnet list, not in `~/.ssh/config`, and the repository does not name it). Needed from the owner: the host's address and how to reach it (SSH user), whether Docker is installed there, and the private address and port the worker should bind.
* Steps 5 to 13 (backup, migration `031_documents`, recreate core/hub/coding-agent, flag off, verify, enable, one controlled real run, cleanup check, new Phase 48 boundary) run on the MS-01 and do not depend on the Proxmox route to start, but the owner's order puts the worker first, so they have not been started.
