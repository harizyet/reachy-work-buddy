# Phase 50A: MinerU local deployment spike (2026-10-11)

Owner instruction: "start implementation of phase 50" (2026-10-11). This is the first 50A step only: a **disposable, host-side API spike** on the homelab machine to verify the MinerU contracts [docs/phase-50.md](../phase-50.md) assumes. **No Reachy code, migration, dependency, image, compose service or flag was added; nothing was deployed; the GPU, production containers and robot were not touched.** MinerU was installed in a throwaway venv and database under the session scratchpad and `/tmp/m50a`; the server was stopped and `/tmp/m50a` deleted afterwards (no process left).

## What was run

`mineru==4.0.12` (PyPI, uploaded 2026-10-11, Python 3.12, core install only: no torch, no model download, CPU). A 3-page born-digital PDF (one sentence per page) through the doclib server, CLI and `DoclibClient`.

## Verified

| Assumption | Result |
|---|---|
| Doc identity | A MinerU document is the **content SHA-256** of the file (`sha256`, plus a 7-hex `short_id`). It equals Reachy's own source hash exactly, so `backend_ref` can be `short_id`/`sha256` and revalidation can compare hashes. |
| Locators | Stable and tier-scoped: `doc:d59e103/tier:flash/page:2/block:2`; `get_doc_content` returns `content_ranges` (start/end locators), `truncated`, and a `next_request` cursor for continuation. Page numbers come from the source (`<!-- page 2 of 3 -->`), not chunk position. |
| Bounded reads | `get_doc_content(doc, tier, page_range, after, limit)` and `read_content(locator, context, limit)` work. |
| Flash tier | Works fully offline on a born-digital PDF in about a second. |
| Reparse | `invalidate(doc_ref)` drops the parses (`invalidated_count`); the next `ensure_parse` is `pending`, not a cache hit. |
| Delete | `forget_path(path, dry_run=False)` removes the file record; search stops returning the document at once. The document row and parsed data are removed only by `cleanup_orphan_docs`. |
| Telemetry | `mineru telemetry disable` persists; default state is `unset`. Must be disabled in the image. |
| Cloud | Remote parsing is opt-in (`--remote`, `parse_server.remote.*`); not used. |

## Findings that change the plan (each needs a decision or design rule)

1. **MinerU's library is path-based and shares identical bytes.** Two files with the same bytes are one MinerU document with two `files`; `invalidate` hit both (`invalidated_count: 2`). Two Reachy documents with identical content but different sensitivity or project scope would share one backend object. Reachy must key policy and revalidation by *Reachy* `document_id`, treat `backend_ref` as shared, and delete in order: `forget_path` for each Reachy file, then `cleanup_orphan_docs`, then verify. Proposed rule: one MinerU path per Reachy document id; reprocess/invalidate of a shared sha affects every Reachy document with that hash and must not mark another's outputs stale incorrectly.
2. **Search is global and returns file paths.** `search(query)` has no document filter and its results carry `files[].path` (the filesystem path of the working copy) and snippets that join several pages without per-page locators. Document-scoped Q&A (G5) and the Phase 44 adapter (50F) must therefore either filter by `short_id`, or (preferred) search only through a per-request allowed set and use `get_doc_content`/`read_content` for locator-bearing evidence. Paths must never reach a prompt or API response.
3. **`get_doc` still answers after `forget_path`** until orphan cleanup. Liveness for retrieval must come from Reachy's record (ADR 0034 revalidation), never from MinerU answering.
4. **Transport is a Unix socket under `MINERU_HOME`**, not a network port; the socket path limit (108 bytes) made the first server start fail under a deep directory (`AF_UNIX path too long`). The doclib has an optional TCP transport (`doclib.tcp`, off by default) and a separate stateless `mineru-kit api-server` (`/v1/*`, binds 127.0.0.1:8000, `--api-key`, `--allow-local-source`, `--concurrency 1`). Isolation choice for 50A: a **thin adapter inside the MinerU container** (small FastAPI app over `DoclibClient`, internal network only, service token) so Reachy services never mount MinerU's socket or data. The adapter, not MinerU, exposes only the operations Reachy needs.
5. **Licence is custom:** `LicenseRef-MinerU-Open-Source-License`. The plan's pre-deployment licence review (section 26) is **open and needs the owner**. Model licences (MinerU-4 ONNX, MinerU2.5-Pro-1.2B GGUF) are likewise unreviewed.
6. **Models are not present.** Basic needs `MinerU-4_models_onnx`; Standard also `MinerU2.5-Pro-2605-1.2B-GGUF`. Default source is `auto` (network). Production use needs `MINERU_MODEL_SOURCE=local` with assets pre-downloaded and hash-recorded.

## Not yet verified (still 50A)

Basic/Standard/Advanced tiers and scanned-PDF/OCR behaviour (need model downloads: network egress and disk, owner approval), DOCX and image inputs, resource use and limits on the real hosts, the Proxmox CPU worker and MS-01 GPU path (50I), `mineru-kit api-server` under a container, persistence across restart, large documents. Defaults for upload/page/time limits are therefore **not** set.

## Open decisions for the owner

* Accept or reject the MinerU licence (and model licences) for self-hosted private use.
* Approve downloading the model assets (size to be measured first) for the Basic/Standard tier spike.
* Physical storage and backup of Reachy's source store and MinerU's data (plan section 21).
* Confirm the in-container adapter as the integration surface (finding 4).
