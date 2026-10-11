# ADR 0034: Source evidence and derived artifacts

- Status: **Accepted 2026-10-11** (owner-approved wording). A prerequisite for any [Phase 50](../phase-50.md) implementation; it does not itself approve starting a stage.
- Date: 2026-10-11
- Relates to: [ADR 0001](0001-service-boundaries.md), [ADR 0011](0011-destructive-action-consent.md), [ADR 0018](0018-hybrid-llm-routing.md), [ADR 0031](0031-three-tier-local-model-escalation.md), [Phase 44](../phase-44.md), [Phase 50](../phase-50.md)

## Context

Phase 50 turns uploaded documents into searchable, citable knowledge using native text extraction, OCR and vision models. Each step can be wrong in a different way. If a machine reading replaces or blends with the thing it read, nothing can later be audited, reprocessed after a model upgrade, or deleted completely.

## Decision

Source evidence is immutable and authoritative. Everything a program or model produces from it is a derived artifact.

Evidence classes:

| Class | Contents |
|---|---|
| **Authoritative source** | the original PDF/DOCX/TXT/Markdown file; native embedded text; the original page or image |
| **Derived extraction** | OCR text and confidence; layout extraction; the parsed structural representation |
| **Derived interpretation** | VLM descriptions; visual entities and relationships; summaries; classifications; any LLM analysis |

OCR is derived, not authoritative: it is a machine's guess at the text in an image and can be wrong. The page image is the authority.

Derived artifacts MUST:

1. retain provenance to the source file hash, the page or unit, the processing version, and the tool or model and its version, and state their derivation type (extraction or interpretation);
2. never overwrite or edit source evidence, and never be stored in a field that source evidence occupies;
3. never grant authority, authorize an action, or reduce sensitivity: document content cannot set or lower its own classification, and classification suggestions are proposals the owner applies;
4. be deletable and reprocessable reproducibly: reprocessing recreates every derivative from the retained original, never edits old results in place, and deleting a document removes every derivative, embedding and index entry;
5. remain untrusted data under the existing prompt-injection protections wherever they are later read;
6. be distinguishable from source evidence in retrieval, citations and audit, by an explicit `evidence_type` carried on every chunk and output.

Consequences for the design:

- The original is stored once, content-addressed by SHA-256, and re-verified on read.
- Retrieval revalidation resolves a chunk to its document, page and revision and fails closed when any is missing or changed.
- OCR and visual output are labelled lower-trust than native text when cited.
- Heavy parsing, OCR and vision run in an isolated document worker, not in companion-core.

## Consequences

- More storage and a retained original per document; reprocessing is a full rebuild, not a patch.
- Model upgrades are safe: derivatives are regenerated and the old ones deleted, with the source untouched.
- The ADR does not choose an OCR engine, a vision model or storage location; those are recorded in the Phase 50 plan and its evaluation.
