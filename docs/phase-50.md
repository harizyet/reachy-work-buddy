# Phase 50 — Multimodal Document Intelligence

**Status: PROPOSED (2026-10-11). Plan only: no code, migration, dependency, model or flag exists for it. Nothing in this page describes implemented behaviour.** Each stage ends with a dated verification record and an owner decision before the next begins.

Type: new capability. Dependencies: the document store ([Phase 13](plan.md#6-implementation-roadmap)), the Phase 44 knowledge index and retrieval ([phase-44](phase-44.md)), model tiers ([Phase 42](phase-42.md), [ADR 0031](adr/0031-three-tier-local-model-escalation.md)), owner authentication and the sensitivity labels from migration 026.

The design below was supplied by the owner on 2026-10-11; the supplied text is not kept in the repository, so this page is the record. The stage letters 50A to 50K are kept.

## 1. Objective

Make documents (PDF, DOCX, TXT, Markdown) first-class Reachy objects: stored whole, processed page by page, searchable with provenance, answerable from one document at a time, summarizable, and visible in the web UI with an honest account of how much of each document was actually read and how.

Reachy should become a multimodal knowledge-ingestion system in which PDF and DOCX are two source formats, not a "PDF RAG feature". Screenshots, whiteboards, decks, scanned notes, meeting images and camera-derived documents are later sources for the same pipeline and are out of scope here.

## 2. Binding design rule

> **Never replace original evidence with model-derived interpretation.**

Two classes of data stay permanently distinct, in storage, in retrieval metadata and in citations:

| Class | Contents | Rule |
|---|---|---|
| **Authoritative source** | the original file; native text; OCR output; the original page image | Written once per processing version, never rewritten by a model. OCR is stored beside native text, never over it. |
| **Derived evidence** | visual descriptions; extracted entities and relationships; chunk embeddings; summaries; any LLM analysis | Rebuildable from the authoritative class. Labelled with model, prompt version and processing version. Deleted and regenerated on reprocess, deletion or model upgrade. |

Everything else follows from this: provenance, deletion, reprocessing, audit, model upgrades and hallucination investigation each operate on the derived class without touching the source.

Binding limits inherited from the project (see [AGENTS.md](../AGENTS.md)):

- Document text, OCR output and VLM output are **untrusted data**. They cannot authorize an action, set a date, change a gate or write memory ([ADR 0001](adr/0001-service-boundaries.md), [ADR 0011](adr/0011-destructive-action-consent.md), [ADR 0018](adr/0018-hybrid-llm-routing.md)). A document containing instructions is tested as an injection case.
- Cloud inference only under the existing owner/privacy policy; no document page, page image or derived text goes to a cloud provider without it. Documents above the private ceiling stay local.
- Services talk over HTTP; shared models go in `shared/models`, route constants in `shared/protocols`. Heavy tools (OCR engine, PDF renderer, VLM client) run in a sidecar or the processing worker, not in the request path, and never as sibling-service imports.
- Browser paths are relative; conversation and document text render literally (no HTML, no Markdown execution); no document text or keys in localStorage.

## 3. Facts about the current checkout (confirm at 50A start)

| Fact | Consequence |
|---|---|
| Documents are `DocumentChunk` rows in `document_chunks` (`id`, `document_id`, `document_title`, `section`, `content`, `source`, `chunk_index`, 384-dim MiniLM vector, no ANN index) behind the `DocumentStore` protocol in `companion_core/rag/store.py` ([phase-44 section 2](phase-44.md)) | There is no document record, no original file, no page, no status. 50A adds the record; the chunk model gains page and evidence fields rather than being replaced. |
| `POST /documents` ingests text; `GET /documents`, `GET /documents/search` list and search; **no delete exists**; the only conversational path is the `search docs for …` prefix matcher in `rag_intent.py` | Delete, reprocess and a scoped query path are new. The prefix matcher stays as is unless the owner decides otherwise. |
| Migration 026 added sensitivity and nullable `project_scope` to documents; the Phase 44B index adapters read documents, with retrieval-time revalidation under the owner's access context | Document sensitivity already has a place to live. The new document record must feed the same adapter and revalidation, not a parallel index. |
| Nothing ingests PDFs and nothing in the stack renders pages, runs OCR or serves a vision model | OCR engine, PDF library and VLM are all new dependencies. Each needs the dependency/index routing in [development](development.md), an image-size and licence check, and (for the VLM) a decision on where it runs; see open questions. |
| The default model is the local Qwen2.5-7B; a task-scoped 14B is swapped in by the model manager ([ADR 0031](adr/0031-three-tier-local-model-escalation.md)) | 7B/14B routing in 50H and 50I reuses that manager. A vision-capable model is a **third** residency problem on the same GPU and is not covered by 0031. |
| Phase 47 recorded memory and document screens as blocked on backend work | 50K depends on the document API from 50A to 50H; no screen precedes its routes. |
| Meeting upload already has a durable job store, worker and restart recovery ([Phase 27](phase-27.md)); notes processing uses the same pattern ([Phase 49](phase-49.md)) | Reuse that job pattern (compare-and-set claim, crash takeover, idempotent commit) for document processing instead of inventing one. |

## 4. Stages

### 50A — Document lifecycle

Goal: documents become records, deterministically manageable, before any cleverness.

- Upload (PDF, DOCX, TXT, Markdown) with validation: size ceiling, type by content not extension, page ceiling, decompression and archive-bomb limits (DOCX is a zip), no embedded-script execution, no external fetches while parsing.
- The original file is stored separately from derived data, content-addressed by hash; the hash is verified on read.
- `Document`: `document_id`, `filename`, `title`, `mime_type`, `file_hash`, `sensitivity`, `project_scope`, `page_count`, `processing_status`, `processing_version`, `created_at`, `updated_at`.
- Explicit states: `uploaded → inspecting → extracting → enriching → indexing → ready`, or `partial` / `failed`. The UI shows these, not just "uploaded".
- Routes: upload, list, detail, delete, reprocess. Delete cascades to pages, chunks, embeddings, index entries, derived outputs and the stored original, and is verified (see G8). Delete is a destructive action and goes through the ADR 0011 consent path.
- A decision record (ADR 0034, proposed) fixing the authoritative/derived split in section 2, written at 50A start.

Acceptance: upload/list/detail/delete/reprocess behave deterministically on a real database; deletion leaves no row, vector or file referring to the document (checked by table-by-table count before and after); a killed worker resumes or fails the document cleanly.

### 50B — Page-native extraction and provenance

The authoritative evidence layer. **No OCR and no model in this stage.**

- `DocumentPage`: `document_id`, `page_number`, `native_text`, `text_quality`, `image_count`, `has_native_text`, `likely_scan`, `likely_visual_content`, `page_hash`, `extraction_metadata`. DOCX yields structural units (heading, paragraph, list, table) with the same provenance fields.
- Chunks keep `document_id`, `page_start`, `page_end`, `section`, `chunk_index`, `source_type = native_text`, and feed the existing store and Phase 44 adapter.
- Each page is assessed, not interpreted: `TEXT`, `SCAN_CANDIDATE` (no usable native text), `VISUAL_CANDIDATE` (text plus a large figure). This gives a measurable document-coverage model.
- Start the evaluation corpus here (50J).

Acceptance: native-text PDFs and DOCX are extracted with page numbers that match the source; a page with no text is flagged rather than silently empty; reprocessing the same bytes gives identical pages and hashes.

### 50C — OCR fallback

- Triggered per page, not per document, when native text is insufficient (character count below a threshold, very low text-to-image ratio, or detected scan). Never "OCR every page".
- Stack to evaluate first: OCRmyPDF with Tesseract, run locally in a sidecar. Choice is confirmed or replaced on the evaluation corpus, not assumed.
- `PageEvidence` keeps `native_text` and `ocr_text` side by side with `ocr_engine`, `ocr_confidence`, version and provenance. `native_text` is never overwritten. Chunks derived from OCR carry `source_type = ocr`.
- OCR text is lower-trust evidence: citations say so, and low-confidence pages are flagged in the coverage summary.

Acceptance (G3): a scanned-text PDF reaches retrieval behaviour comparable to the equivalent digital PDF on the frozen corpus; the comparison and its threshold are fixed before the run.

### 50D — Visual-content detection

Classify each page: `TEXT_ONLY`, `SCAN_TEXT`, `TEXT_PLUS_VISUAL`, `VISUAL_DOMINANT`, `EMPTY`. Deterministic signals first: native text quantity, image coverage, raster/vector object counts, native/OCR disagreement. No learned classifier unless the deterministic one fails on the corpus. Ordinary paragraph pages never reach the VLM. Candidates are charts, diagrams, screenshots, flowcharts, infographics and image-only tables.

Acceptance: visual-page detection recall and the false-candidate rate on the corpus, with targets fixed beforehand (they set the VLM cost).

### 50E — Multimodal page understanding

For a candidate page the inputs are native text, OCR text and the page image, and the output is a **structured** `VisualPageAnalysis`, not a free description:

```json
{"page": 17, "visual_elements": [{"type": "architecture_diagram", "caption": "...", "summary": "...", "entities": [], "relationships": [], "visible_labels": []}]}
```

- Output is schema-validated; anything that fails validation is stored as failed, not repaired by guessing.
- Every entity, relationship and label is checked against the page: a label not found in native text, OCR text or the image's detected text is marked `unverified`. Relationships are derived evidence and are labelled as the model's reading of the figure.
- Derived evidence only (section 2). It never overwrites native or OCR text.
- Needs a vision-capable local model; its residency, memory and swap cost are an open question (section 8). No cloud fallback without the existing policy and an owner decision.

### 50F — Normalized representation

`NormalizedDocument` is the single abstraction the rest of Reachy consumes: per page, native text, OCR evidence, visual evidence. Knowledge chunks carry modality provenance (`evidence_type`: `native_text`, `ocr`, `visual_description`, `visual_relationship`), `source_revision`, `sensitivity`, page range and section. The Phase 44 index sees chunks plus provenance and does not need to understand PDFs. Revalidation at retrieval resolves the chunk back to its document and page and fails closed if either is gone or its revision changed.

### 50G — Document-scoped Q&A

- Retrieval constrained to one document (`context_document_id`), built so it can become `context_sources[]` later without a breaking change. The scope is applied before ranking and re-checked at revalidation.
- Retrieval spans native, OCR and visual-semantic chunks, so an answer can rest on "page 17, Figure 3" although no paragraph states it.
- Citations are page-level and keep `evidence_type` internally; the UI shows it on request.
- Answers follow the project's grounding rules: unsupported questions abstain with a fixed reply, not ordinary chat. Document text is quoted, never executed. The deterministic-routing rule in [ADR 0033](adr/0033-llm-assisted-read-routing.md) holds: the model may not widen scope to other documents or records.

### 50H — Summaries and analysis

Separate from Q&A. Small documents: one pass on the 7B. Large: page/section synthesis, then document synthesis. Where visual evidence exists, the important `VisualPageAnalysis` items are included in synthesis so a crucial diagram is not omitted. `DocumentOutput`: `document_id`, `revision`, `type` (`summary`, `executive_summary`, `technical_analysis`, `deep_analysis`), `content`, `citations`, `model`, `generated_at`. Outputs are derived, tied to a document revision, and deleted with it; a stale output (revision changed) is marked stale, not served as current.

### 50I — Fast and deep routing

Ingestion is cheap: parser, OCR where needed, deterministic page classification, embeddings. Analysis is on demand: simple Q&A on the 7B, complex synthesis on the 14B, selected pages on the VLM. Two visual modes: **standard** (pages that clearly contain meaningful visual content) and **deep** (every potentially relevant visual page, on request). The VLM does not run on every page at ingestion. Cloud only under the existing owner/privacy policy. Latency and memory per mode are measured, not assumed.

### 50J — Evaluation harness

Start at 50B; every stage adds frozen cases. Corpus: born-digital PDF, scanned PDF, mixed PDF, DOCX, diagram-heavy PDF, chart-heavy PDF, screenshots, tables, a long report. Questions are written so the answer lives in a deliberately different modality (native paragraph; scanned text only; screenshot only; diagram arrows; chart; native plus diagram together; no answer at all). Four layers are scored separately, never as one end-to-end number:

- **Extraction:** native coverage, OCR recovery, visual-page detection recall.
- **Retrieval:** Recall@K, correct-page, correct-modality.
- **Grounding:** citation correctness, answer entailment, unsupported-claim rate, abstention correctness.
- **Cost:** 7B versus 14B quality, visual and document processing latency, resource use.

Method rules carried over from Phase 44: the corpus and cases are frozen and hashed before scoring; targets are fixed before the run; a consumed holdout is not re-scored or tuned on; single-author labels are reported as such, with no independence claim. The corpus uses synthetic or owner-approved documents only and is not committed if it contains private material.

### 50K — Documents web experience

A Documents area in `clients/web` (own route, beside Brain, Meetings, Notes and Tasks): upload; list with page count, status and sensitivity; detail with a coverage line stated as fact, e.g. "46/46 pages processed — 38 native text, 5 OCR, 3 visually interpreted"; Ask, Summarize, Deep analysis, Reprocess and Delete; summary, visual content and processing details. No "Reachy has read this document" claim without the counts. Document text renders literally. Android parity is a separate owner decision. Per the Phase 47 convention, the owner tests the UI once at the end of the build; no deploy without approval.

## 5. Promotion gates

Promotion depends on measured gates, not on feature completion. Each modality is judged separately and ends as **PROMOTE**, **NARROW** (the supported scope is cut back to what passed) or **DO NOT PROMOTE**.

| Gate | Requirement |
|---|---|
| G1 Integrity | original file and source hashes preserved and verified on read |
| G2 Extraction | text documents extracted reliably, page numbers correct |
| G3 OCR | scanned evidence recoverable at the pre-fixed threshold |
| G4 Vision | visual-only evidence recoverable at the pre-fixed threshold |
| G5 Retrieval | pre-fixed Recall@K target met |
| G6 Grounding | citations point to the correct source and page |
| G7 Abstention | unsupported questions are not answered |
| G8 Lifecycle | delete and reprocess remove all stale knowledge, verified table by table |
| G9 Privacy | sensitivity enforced at upload, index, retrieval, summary, citation and cloud routing; zero leakage on adversarial cases |
| G10 UX | processing coverage visible to the owner and accurate |

## 6. Dependencies and order

```text
50A ─► 50B ─► 50C ─► 50D ─► 50E ─► 50F ─► 50G ─► 50H ─► 50I ─► 50K
         └──────────── 50J (starts at 50B, grows with every stage) ─────────┘
```

50C and 50E can each be stopped with the earlier stages still delivering value: 50A to 50B with 50F and 50G gives native-text document Q&A without OCR or a VLM. That is the natural first release candidate and the first point at which a NARROW outcome is meaningful.

## 7. Non-goals

- Camera, whiteboard, screenshot-as-source and deck ingestion (the architecture should not block them; they are not built here).
- Editing, annotating or re-exporting documents; document sharing outside the owner.
- Multi-document or cross-corpus reasoning beyond what Phase 44 retrieval already does (`context_sources[]` is a shape to leave room for, not a feature).
- Any model-derived text standing in for source text, anywhere.
- Changes to the frozen Phase 44/48 capture, routing and answering code, or to its flags.
- Cloud processing of documents by default.

## 8. Open questions for the owner

1. **Where does the vision model run, and which?** Nothing in the stack serves a VLM. It competes with the 7B and 14B for the same GPU; ADR 0031 does not cover a third resident model. This decides whether 50E and the "standard" visual mode are feasible on the homelab at all, and may need an ADR amendment.
2. **New dependencies:** approve evaluating a PDF library, OCRmyPDF/Tesseract and a DOCX parser, each with image-size, licence and supply-chain review ([Phase 33](plan.md#forward-roadmap-phases-30) applies to ingestion).
3. **Storage:** where the original files and page images live (database large objects, a volume, or the existing data volume), their backup coverage, and retention. Page images are derived but large; keep or regenerate?
4. **Limits:** maximum file size, page count and per-document processing time.
5. **Sensitivity at upload:** a required owner choice, or a default? (The Phase 44 rule is that sensitivity is never inferred by a model.)
6. **Evaluation corpus:** synthetic only, or may some owner documents be used and kept out of the repository?
7. **Scope of 50K on Android:** web only for now?
8. **Phase number and ordering:** Phase 50 is the next free number (no `phase-50*` document or ADR existed on 2026-10-11). Does it run ahead of the open Phase 48 acceptance and Phase 49 owner checks, or after them?

## 9. Definition of done

Gates G1 to G10 each have a recorded verdict (PROMOTE, NARROW or DO NOT PROMOTE) on the frozen corpus; the supported scope is stated in [project state](project-state.md) as exactly what passed; delete and reprocess are proven to remove every derived artifact; and the owner has used the Documents screen on a real document of their own. Engineering completion is not deployment: migrations, flags and activation are separate owner decisions.
