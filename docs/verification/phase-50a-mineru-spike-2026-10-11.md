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

## Owner decisions, 2026-10-11 (after the Flash spike)

1. MinerU 4.0.12 approved for private self-hosted use; custom licence (Apache-2.0 base plus extra conditions: commercial licence only above 100M MAU or USD 20M monthly revenue; attribution for third-party online services) recorded here. Each model bundle's licence reviewed before adoption (below). Run `mineru telemetry disable` and `mineru telemetry status` in image build and startup verification.
2. Basic and Standard model download approved after recording metadata; Advanced skipped; goal is function and resource requirement, not quality.
3. Reachy's source store (content-addressed, system of record) and MinerU state (derived) live in separate volumes; back up Reachy DB and source store, MinerU state is optional and rebuildable. Both on Proxmox bulk storage as separate datasets (`reachy-source`, `reachy-mineru`).
4. An in-container HTTP adapter is the only Reachy-to-MinerU interface. Invariants: scoped search only (`POST /documents/{backend_ref}/search`, fail closed), filesystem paths stripped, normalised locators, no liveness inference from MinerU, deletion order (mark deleting, block retrieval, forget, orphan cleanup, verify, then remove source blob only when no Reachy document references the hash).
5. `document_id` (Reachy) is the unit of policy and liveness; `source_hash` and `backend_ref` are separate fields.

## Model bundles (recorded before use)

| Bundle | Source | Size | Licence evidence | Verification |
|---|---|---|---|---|
| `MinerU-4_models_onnx` (Basic and Standard) | HF `opendatalab/MinerU-4_models_onnx`, revision `358310b4f64b`, 13 files | 858 MB | Repo card declares no licence; README says original model licences remain applicable. Upstream sources per its `manifest.json`: `PaddlePaddle/PP-DocLayoutV2_onnx`, `PP-OCRv6_small_rec_onnx`, `PP-OCRv6_tiny_det_onnx`, `jinzhenj/PP-FormulaNet_plus-M_onnx` (all apache-2.0 on their cards) and `opendatalab/MinerU-4_models_torch` (apache-2.0) for the seal detector, table models and formula weights | all 13 SHA-256 equal to the manifest; `mineru-kit models verify` ok |
| `MinerU2.5-Pro-2605-1.2B-GGUF` (Standard VLM) | HF `jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`, revision `9185688a0495`, Q8_0 model plus mmproj | 1,240 MB | **Third-party quantisation: repo has no card and no licence.** Base model `opendatalab/MinerU2.5-Pro-2605-1.2B` is apache-2.0. | SHA-256 equal to the HF LFS listing (`3f3523429c88...`, `b6c08ab50352...`); `verify` ok |

Open licence follow-ups: (a) the GGUF repo's own terms are undeclared, so adoption rests on the base model's Apache-2.0 plus the quantiser being a derivative; the owner may prefer to quantise from the official repo ourselves. (b) The ONNX bundle's composite licence rests on component cards. (c) Pin by revision and hash in the image build (hashes above); the files were copied to `~/.local/share/reachy-phase50a/models` (mode 0700, outside the repo, not committed) so the spike need not download again.

## Basic and Standard spike (this host, CPU only, 20 cores, no GPU use; 2-page scanned PDF rendered from text, 150 dpi)

| Tier | Wall time | Parse step | Peak resident memory (summed) | Output |
|---|---|---|---|---|
| Basic | 3.2 s | 1.5 s for 2 pages (about 1.3 page/s) | about 1.6 GB | text, headings and both numeric facts correct, page markers correct |
| Standard | 11 s (first cold run 16.6 s) | 8.3 s for 2 pages (about 0.24 page/s; cold 12 s) | about 1.6 GB sampled (the in-process VLM may be under-counted) | same text, correct |

Figures are one small document on this machine (not Proxmox-class, not a benchmark): enough to show both tiers work on CPU and roughly what they need; limits for production still have to come from a run on the real worker with realistic documents.

### Findings 7 to 9

7. **Doclib local parsing is off by default** (`parse_server.local.mode = disabled`, so Basic and above fail with "Local parse-server is disabled"). The adapter image must set `parse_server.local.mode=managed` and the tier (`managed_tier`); the managed parse server needs a few seconds after `server start` before it accepts jobs (the adapter must poll readiness).
8. **GPU leak risk: the Standard VLM uses Vulkan, not CUDA.** `mineru-llama-cpp` ships `libggml-vulkan.so` and defaults to 99 GPU layers, so `CUDA_VISIBLE_DEVICES=""` did **not** keep it off the GPU: it took about 1.9 GiB of the shared RTX 2000E, pushing the card to 15.7 of 16.4 GiB beside production vLLM (no harm: vLLM stayed healthy and memory returned to 13.8 GiB when the server stopped). `VK_LOADER_DRIVERS_DISABLE='*'` with `GGML_VK_VISIBLE_DEVICES=""` kept it entirely on CPU (no non-vLLM GPU process sampled). Rule: the Proxmox/background container must never see a GPU device and must set these variables; the interactive path that uses the MS-01 GPU needs the ADR 0031 handoff, never concurrent residence with vLLM. ONNX providers were CPU only.
9. **Telemetry setting persisted per `MINERU_HOME`** (`state: disabled` survived restarts). Default is `unset`, so image build and startup must disable it and check `telemetry status`.

## Still open in 50A

Docker image and compose service for the adapter (pinned versions, no GPU, network-restricted, resource limits, telemetry disabled and checked at start); the adapter API and its tests; DOCX and image inputs; realistic large and complex documents on the real Proxmox worker; persistence across restart and the adapter readiness behaviour; Advanced tier (skipped by decision); upload/page/time limit defaults after those runs; backup of the source-store dataset and a restore test.
