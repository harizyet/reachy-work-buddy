# Phase 44 proposal: a reproducible offline model cache for the embedding model (for review, 2026-10-10)

Status: **proposal only; nothing in production changes.** Prompted by the [2026-10-09 indexing trial](verification/phase-44b-indexing-workload-trial-2026-10-09.md): the model load contacted the Hugging Face hub (an "unauthenticated requests" warning) although the weights were cached, and the load costs about 13 s and 516 MB on the first index operation after each restart.

## 1. What runs today (verified 2026-10-10)

- `companion_core/rag/embeddings.py` calls `SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")`: a hub **name with no revision**, loaded lazily on the first embedding.
- Core sets `HF_HOME=/data/model-cache`, a named volume (`reachy-homelab_model-cache`), so the weights survive restarts. The cached snapshot is revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (written 2026-10-08); `model.safetensors` has the content hash `53aa5117…`. Nothing in the code or deployment records or enforces that revision.
- Consequences: each load asks the hub whether `main` moved (network use, a warning, and a delay or failure if the hub is unreachable); a moved `main` or a corrupted file would change the vectors silently; a fresh volume or a new host downloads whatever is current; the index labels its rows `sentence-transformers/all-MiniLM-L6-v2`, which does not say which weights produced them.

## 2. Goals

Reproducible (the same bytes on every host), offline (no network at run time), revision-pinned, integrity-verified at acquisition and at use, fail-closed (never silently download or run unverified weights), reversible, and cheap to audit.

## 3. Design

1. **Pin the revision.** One constant for the model name and the 40-character commit (`1110a243…`), used everywhere the model is loaded, and recorded in a manifest.
2. **A manifest in the repository** (`deploy/models/all-MiniLM-L6-v2.manifest.json`): model id, revision, licence (Apache-2.0, to be confirmed against the model card at pinning time), source URL, and for every file its path, size and **SHA-256** (the repository's own check, not the hub's SHA-1 names). It is the single source of truth and is reviewed like code.
3. **A fetch-and-verify tool** (`tools/fetch_model.py`, an operator or build step, the only place that touches the network): downloads exactly the pinned revision into a target directory with `huggingface_hub`, hashes every file against the manifest, refuses on any mismatch or extra file, and writes a `VERIFIED` marker containing the manifest hash. Prefer a plain file layout (no symlinked blob store) so the directory is trivially hashable and copyable.
4. **Delivery** (choose one; recommended: **C**):
   - **A. Bake into the image** at build: reproducible and self-contained, about 90 MB larger images, build needs the network.
   - **B. Populate the existing `model-cache` volume** with a one-off container and set offline flags: no image change, but the volume is mutable and shared.
   - **C. A verified directory mounted read-only** (for example `/models/all-MiniLM-L6-v2`, populated by the same one-off step) and loaded **by path**, with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` set. A path load never consults the hub: no revision lookup, no warning, no network, and a read-only mount stops runtime drift.
5. **Verify at use, fail closed.** Before the first embedding after each start, hash the files (about 90 MB, a fraction of a second) against the manifest baked into the image or mounted beside the weights, then run a **golden-vector check**: encode three fixed sentences and compare with stored vectors (tolerance 1e-5) to catch wrong weights that happen to have the right names. On any failure the embedder raises a clear error, the indexing worker records a failure for that item (it already isolates failures per item and backs off), and nothing downloads. Retrieval stays off regardless.
6. **Label the weights, not just the name.** The index's `embedding_model` should identify the revision (for example `sentence-transformers/all-MiniLM-L6-v2@1110a243`). Because the worker's reconciliation re-queues rows whose label differs, simply changing the label would re-embed every row. [Section 3a](#3a-verification-of-vector-equivalence-done-2026-10-10-read-only) shows the re-embedded vectors are equivalent, so the revision should be recorded without a relabel (a metadata field or an alias the reconciler accepts); any label migration is a separate, planned and approved step. Until then the label stays as it is.
7. **Rollback and rotation.** Directories are named by revision and kept side by side; the active one is chosen by one environment value; switching back is a restart. Updating the model is a deliberate change of the pinned revision and manifest in a reviewed commit, followed by the label migration above.

## 3a. Verification of vector equivalence (done 2026-10-10, read-only)

Question: does the pinned revision (`1110a243…`, the revision already cached) with the production embedding call produce the vectors already stored in the index? Method: the 81 stored `match_text` values and vectors were exported read-only to a temporary file (deleted afterwards, never printed), then re-embedded in a throwaway container from the production image with **no network**, the model-cache volume mounted read-only, `HF_HUB_OFFLINE=1`, loading the model **by pinned revision with `local_files_only`**.

| Embedding call | Max absolute difference from the stored vectors | Minimum cosine similarity |
|---|---|---|
| Production call (batch encode, normalised, 2 threads) | 1.2e-7 | 0.9999999999998 |
| One text at a time | 1.5e-7 | 0.9999999999997 |
| Batch size 8 | 1.2e-7 | 0.9999999999998 |
| One thread | 1.2e-7 | 0.9999999999998 |

Conclusions: (1) the pinned revision loads offline from the existing cache in 0.2 s and is **the same model** that produced the index; (2) the vectors agree to float32 rounding noise (about 1e-7), not bit for bit, because batch composition and thread count change the order of floating-point additions; so a bitwise comparison is the wrong test and a tolerance (1e-5 on the largest component, cosine above 0.99999) is the right golden-vector check; (3) therefore **no re-embedding is needed for correctness** if the weights are pinned to this revision. The only reason the worker would re-embed is its label comparison. A revision-bearing label would trigger a full re-embed of numerically equivalent rows, so the preferred way to record the revision is a separate metadata field (or a label alias that the reconciler treats as equal to the current label), not a relabel. **Nothing in production was relabelled or re-embedded**, and no production row, flag or volume was modified; the cache volume was mounted read-only.

## 4. Test plan (all on disposable infrastructure; no production change)

(1) Build the verified directory in a temporary location and check the manifest against it. (2) Load by path in a container with **no network** (`--network none`): vectors equal the golden vectors; measure cold load time against today's. (3) Corrupt one byte of a file, drop a file, add an extra file, change the revision in the manifest: each fails closed with a specific error and no download attempt (assert no socket use). (4) Confirm the indexing worker degrades per item (failure counted, backoff) and the service stays healthy. (5) Check that a read-only mount cannot be written by the service. (6) Rehearse the label migration on a restored copy: row count preserved, vectors regenerated, retrieval unaffected.

## 5. Scope and other models

This covers only the MiniLM embedder used by the knowledge index and document search. The same pattern would later apply to the reranker (B1c, not used), the hub's speech models and the diarization and transcription sidecars, each with its own manifest; none is part of this proposal.

## 6. Decisions requested

(a) Delivery option A, B or C (C recommended). (b) How to record the revision without a re-embed (a separate metadata field or a reconciler-recognised alias; section 3a shows the existing vectors are equivalent, so a relabel that re-embeds is unnecessary). (c) Whether the golden-vector check is wanted at every start or only at acquisition. (d) Owner approval before any change to a compose file, image, volume or flag.
