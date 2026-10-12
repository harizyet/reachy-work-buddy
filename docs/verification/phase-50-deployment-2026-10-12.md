# Phase 50 deployment to the MS-01: document library, minimal Documents page (2026-10-12)

Owner authorization (2026-10-12): the MS-01 deployment gate for Phase 50A to 50E, 50G, 50H and the minimal 50J, with stop conditions; 50F (federation) not started, Android Documents and a chat picker not built, Proxmox deferred. Code: commit `56cd1e1` (clean checkout, 0 modified files; the only non-Phase-50 change since the deployed `db40560` is the earlier notes folder web fix). **Result: deployed, library ENABLED, every check below passed; no stop condition was hit. Not yet accepted: the owner-authenticated browser pass is the owner's.**

| | Before | After |
|---|---|---|
| Schema revision | `030_note_tags` | `031_documents` (new tables `documents`, `document_outputs`, both empty after the checks; no other table changed, row counts diff-checked equal) |
| core | `60c024410173` | `d53f23512f7f` |
| hub | `ab988bf52803` (includes the Documents page) | `6d98cd606d6e` |
| coding-agent | `197350dbcb4d` | `44b6fa237c0e` |
| migrate | `60c024410173` | `4498cc0870b8` |
| document-worker | none | `fbb760daf100` (`reachy-document-worker:latest`, Python 3.13, MinerU 4.0.12 from the hash-pinned lock, 1.17 GB) |

Untouched: PostgreSQL, PgBouncer, vLLM and its GPU allocation (13,8xx MiB throughout), Caddy, SearXNG, router, transcription, diarization, the robot. Phase 48 and 49 flags unchanged (selective answering absent; the frozen candidate, routing, retrieval and sufficiency files are byte-identical in the new core image and the running one).

## Timeline (UTC, 2026-10-12)

| Time | Step |
|---|---|
| 02:11 | Preflight: 155 GB free, the only scheduled alarm is disabled and in the past, no pending reminders, one complete meeting; Phase 48 counters read (`{}`); baseline test failures reproduced on the deployed commit `db40560` (see below). Rollback tags `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-031` verified equal to the running images. `.env` backed up (`.env.bak-before-phase50`, mode 600); `DOCUMENT_LIBRARY_ENABLED=false`, `DOCUMENT_WORKER_MODELS_DIR` and a generated `DOCUMENT_WORKER_TOKEN` added (never printed). |
| 02:11 | Volume `reachy-homelab_document-source` created with Compose labels, write-checked, archived with the tar procedure (`reachy-document-source-20261012-021153.tar`, empty, 0600) and the procedure proved on scratch volumes with a random canary (sha256 equal after restore; scratch volumes removed). |
| 02:12 to 02:13 | Images built from the clean checkout before anything was stopped; schema head `031_documents` and the frozen Phase 48 file hashes confirmed inside the new core image. Worker started alone (`--profile documents --no-deps`). |
| 02:13 | Worker verified: healthy; `verify-worker.sh` all checks ok except "published on one specific address", which does not apply here because the homelab worker publishes no host port at all (stricter); read-only root, all capabilities dropped, no-new-privileges, user 10001, no GPU request or device, memory 6 GiB / 4 CPUs, models read-only; `VK_LOADER_DRIVERS_DISABLE=*`, `GGML_VK_VISIBLE_DEVICES` and `CUDA_VISIBLE_DEVICES` empty, `HF_HUB_OFFLINE=1`; MinerU telemetry `disabled`; attached only to the internal `reachy-homelab_documents` network (`internal=true`); GPU memory unchanged, vLLM healthy. |
| 02:14:30 to :33 | Core stopped gracefully (`docker stop -t 30`: exit 0, not OOM-killed), then hub and coding-agent. Selective-shadow file copied (`~/reachy-backups/phase48-boundary-050/selective-shadow.cohortE-end.jsonl`, 3,316 bytes, unchanged since the previous boundary). |
| 02:14:42 | Dump with writers stopped: `~/reachy-backups/reachy-before-phase50-20261012-021442.dump`, 312,331 bytes, 0600, sha256 prefix `dbe1820b12714c62`, 49 tables; restored into a throwaway container with no network (revision 030, counts identical to `rowcounts-before-031.txt`), container removed. |
| to 02:19:35 | Waited for PgBouncer's idle connections to drain (0 other connections; PgBouncer not restarted). |
| about 02:19:40 | `migrate` ran (`SEARXNG_SECRET_KEY` exported from its 0600 file, never printed): `031_documents`; tables and indexes verified. |
| 02:19:48 to :54 | `up -d --no-build --no-deps companion-core reachy-hub coding-agent-service` with `DOCUMENT_LIBRARY_ENABLED=false`; core healthy at once. Downtime 324 s, of which about 5 min was the PgBouncer wait. |
| 02:20 | Existing behaviour with the flag off: all existing row counts equal (only the two new tables added), services on the new images, 0 tracebacks, Phase 48/49 flags unchanged, `/document-library/*` 404 in core, legacy `GET /documents` 200 `[]`, `/tasks` `/notes` `/reminders` `/meetings` 200 with their data, an ordinary chat turn and a task question answered correctly, hub healthy. |
| 02:20:24 | Controlled enable: `DOCUMENT_LIBRARY_ENABLED=true`, core recreated alone (graceful stop first; counters and shadow file copied again). Core config says `enabled: true`; core refuses calls without the service token (401); the worker is reachable from core's network and refuses calls without its token (401); the hub's document routes answer 401 to anonymous requests and to the robot-control bearer, and 401 to an upload without a session. |

## Real-engine lifecycle through the deployed services (core with the real worker, real MinerU and the real local model; the hub's trusted ceiling supplied as the hub does)

* **Upload, processing, read, scoped search, locators, Q&A, summaries, provenance:** a 7-page PDF reached `ready` at Basic in 14 s; reads carry `evidence_type: derived_extraction` and the original's hash; search ranked the answering page first; a foreign locator was refused; Q&A answered correctly (audit log retention; first compliance deadline), citations carried page, source hash and tier, and an unrelated question got the fixed "I couldn't find that" reply; executive (14 s) and technical (22 s) summaries `ready` with `evidence_type: derived_interpretation`, hash, tier, model `reachy-local` and the page groups.
* **Ceilings and classes:** a sensitive document got 403 on read, search, summaries and summarize without the owner ceiling, a fixed reply in chat, a fixed reply even for a spoken turn with the sensitive header, a refusal for the frontier model, and worked with the owner ceiling (reply privacy `sensitive`, citation tier Standard); a public-only channel could not read a work-private document; an unknown ceiling was 400.
* **Duplicate content across classes:** the same PDF as A (work-private, Basic) and B (sensitive, Standard): one original on disk; reprocessing A left B readable; deleting A left B valid and the original in place and the worker forgot A; deleting B removed the original, the records and the worker's state.
* **Tier escalation:** Standard on the 7-page document in 10 s (earlier summaries became "out of date" but readable; a new one was current at Standard; Q&A cited the Standard reading); Advanced on a one-page image in 86 to 96 s (text correct, no further tier offered). DOCX read at Flash in 4 s and searched; PNG OCR searched.
* **Source integrity:** a tampered original was refused on read and on reprocess with the integrity message (409) and could still be deleted, removing the file.
* **Recovery:** worker restart (documents still ready, no re-reading); worker stopped (a read is a clean 503, an upload is stored as `uploaded` with nothing failed) and started (submitted by the sync loop, ready at once); one document's worker state deleted (a read gave 409 and returned the document to the loop, rebuilt from the authoritative original in 2 s).
* **Cleanup:** all test documents deleted; `documents` and `document_outputs` 0 rows; `document-source` holds no files; the worker's library has 0 files, docs and parses and no working copies.
* **GPU and resources:** a 0.4-second sampler during the Standard and Advanced runs saw no GPU compute process other than vLLM's engine; the worker has no NVIDIA device nodes at all. Worker peak about 4.8 GiB of its 6 GiB limit and about 420 percent CPU (4 CPUs) during Advanced, about 1.8 GiB idle. GPU memory stayed at about 13.8 GiB. **One unexplained observation:** an earlier coarse sampler (every few seconds) listed a second compute process, pid 1900724, 106 MiB, in exactly one sample; it had exited before it could be inspected, it belongs to no container (none has an NVIDIA device), and it did not recur in 330 s of 0.4-second sampling across Standard and Advanced runs. It is recorded rather than explained; production vLLM was unaffected.

## Browser smoke test (no owner authentication used)

Headless Chromium against `http://localhost:8080/hub/web/#/documents`, desktop and a 390-pixel mobile viewport: an anonymous visit redirects to the sign-in page, no console or page errors, no horizontal overflow; the served bundle contains the Documents route, nav item and upload strings. The owner-authenticated pass (upload, ask, search, summarise, improve, delete in a browser) is **not done** and is the owner's UAT.

## Phase 48 boundary

New segments from this change (the earlier segment, "cohort E", ran 2026-10-11 13:53:26 to 2026-10-12 02:14:30 UTC and ended with capture counters `{}`):

| Segment | From (UTC) | To | Capture counters at the end | Notes |
|---|---|---|---|---|
| F | 02:19:51 | 02:20:24 | `{"attempted":2,"excluded_channel":2}` | the migration cutover with the library off; two ordinary probe turns on channel `probe-050` ("What is two plus two?", "What are my tasks?") |
| G | 02:20:26 | open | `{"attempted":11,"excluded_channel":11}` when last read, after all the checks (all on `probe-050`) | the library on. These 11 probe turns were document-attached or refused; a turn with a document attached passes `attached_meeting=true` to the capture, shadow and selective observers, as a meeting does, so they are skipped by design; the telemetry that confirms it is flushed at the next graceful stop. |

Subtract the 13 `probe-050` turns from any 48B/48F window. Shadow-file copies at the boundaries: `~/reachy-backups/phase48-boundary-050/selective-shadow.cohortE-end.jsonl` and `...cohortF-end.jsonl`. No frozen artifact, router, registry, retrieval, evidence rule or answerer was modified (hash-identical files above); the one call-site change is the `attached_meeting` flag described above, which does nothing when no document is attached.

## Baseline test failures (confirmed not caused by this change)

The four failures in the full run (`test_knowledge_index` reconcile, `test_knowledge_retrieval` historical mode, hub `test_robot_voice` spoken command, hub `test_web_client` sample ordering `[]|['int']`) fail identically when the same four tests are run against the deployed commit `db40560` in a clean worktree; they are the known baseline from the HANDOVER. Full suite on `56cd1e1`: 3,057 passed, 142 skipped, those four failed; web 262 passed; ruff clean.

## Backup and rollback assets (keep until the owner accepts)

| Item | Value |
|---|---|
| Database dump | `~/reachy-backups/reachy-before-phase50-20261012-021442.dump` (above), row counts `~/reachy-backups/rowcounts-before-031.txt` |
| document-source archive | `~/reachy-backups/reachy-document-source-20261012-021153.tar` (empty at that time; use the same `tar` procedure for later backups: `docker run --rm -v reachy-homelab_document-source:/src:ro --entrypoint tar <image> cf - -C /src . > file`) |
| Images | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-031` |
| Environment | `deploy/homelab/.env.bak-before-phase50` (0600, gitignored) |
| Schema rollback | `deploy/homelab/rollback-031.sql` (drops `documents` and `document_outputs`; originals on the volume are untouched). Stop core, hub and coding-agent, run it (final line must print `030_note_tags`), wait for PgBouncer's idle connections, tag the `pre-031` images back and `up -d --no-build --no-deps` the three services. The worker is independent: stop it with `docker compose --profile documents stop document-worker`. |
| Feature switch | `DOCUMENT_LIBRARY_ENABLED=false` in `.env` and `up -d --no-build --no-deps companion-core` turns the library off without touching data. |

## Backup plan going forward

Mandatory and together: PostgreSQL and the volume `reachy-homelab_document-source` (the authoritative originals). Rebuildable, not required: `reachy-homelab_document-worker-data` (MinerU state; the sync loop re-reads documents from the originals). Models need no backup (`deploy/document-worker/models.sha256` pins them).

## Using it

Open `http://<MS-01 address>:8080/hub/web/#/documents` (for example `http://10.180.1.23:8080/hub/web/#/documents` on the LAN or `http://100.107.155.34:8080/hub/web/#/documents` over the tailnet), sign in as the owner, and use the **Documents** tab: [operator guide](../operator-guide.md#documents-phase-50).

## Not verified, or open

* The owner-authenticated browser pass; the hub's session-cookie path to the Documents routes was tested with the in-process chain and anonymous refusals live, not with a real owner login (no owner credentials were used).
* Large or complex documents beyond the 7-page and one-page samples; Q&A quality on real scans; scan-heavy performance on this CPU (Standard about 5 s per page, Advanced about 90 s per page measured on small pages).
* The unexplained 106 MiB GPU blip above.
* 50F federation (not started, flag-free and untouched), Android Documents screen, chat document picker, Proxmox (deferred until the feature is accepted).
