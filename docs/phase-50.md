# Phase 50 — Multimodal Document Intelligence

## Status

**Proposed / plan-only.**

No Phase 50 implementation is approved merely by the existence of this document.

Phase 50 adds first-class document ingestion, retrieval, summarization and multimodal document understanding to Reachy while preserving the existing privacy, provenance, trust and local-first architecture.

The core architectural invariant is:

> **Derived interpretation never replaces source evidence.**

Phase 50 must preserve the original document and distinguish authoritative source material from OCR output, model-generated visual interpretations, summaries and analyses.

## Owner decisions — 2026-10-11

Binding for this phase:

1. Document processing is local-first.
2. Background and normal processing preferentially use a CPU document worker on Proxmox.
3. Interactive/priority processing may reclaim the MS-01 GPU after a measured, rehearsed vLLM handoff (see [15.1](#151-gpu-priority-processing)).
4. OCR and parsing run in an isolated document-worker container, never in companion-core.
5. The OCR backend stays pluggable. PaddleOCR, MinerU and Surya are candidates, not selections.
6. A VLM is on-demand, not permanently resident; no model is selected before the 50E evaluation.
7. The original source remains authoritative; OCR and model outputs are derived evidence.
8. The evaluation corpus contains only synthetic or explicitly owner-approved material.

Earlier the same day the owner also decided: explicit sensitivity at upload with a conservative private default; configurable limits whose defaults come from the 50J measurements; the evaluation corpus is frozen from 50B; Android document management is deferred; and no production retrieval change before the Phase 48/49 acceptance work ([section 23](#23-interaction-with-phase-48--49)). Approval to start any implementation stage is still a separate decision, and [ADR 0034](adr/0034-source-evidence-and-derived-artifacts.md) is accepted (2026-10-11).

## 1. Motivation

Reachy already has much of the knowledge backend required for document retrieval:

* Postgres persistence
* pgvector
* local embeddings
* document chunks
* semantic retrieval
* Phase 44 knowledge indexing
* project scope
* sensitivity
* source revalidation
* evidence/context construction
* local 7B inference
* deeper 14B inference
* hosted fallback infrastructure
* prompt-injection boundaries for retrieved data

The current document abstraction, however, is primarily text-oriented.

The missing user-facing capability is:

> Upload a real document and allow Reachy to read, retrieve, summarize and analyse it.

Real documents cannot be assumed to contain clean embedded text.

A PDF may consist of:

* embedded digital text,
* scanned pages,
* screenshots,
* diagrams,
* charts,
* image-based tables,
* mixed text and image pages,
* or combinations of all of these.

Therefore Phase 50 must not be implemented as:

```text
PDF
 ↓
extract text
 ↓
RAG
```

The target is instead:

```text
Document
   ↓
source inspection
   ↓
native extraction
   ├─────────────┐
   ↓             │
OCR when needed  │
   ↓             │
visual analysis when needed
   ↓             │
normalized evidence
   ↓
existing Reachy knowledge stack
   ↓
retrieval / summarization / analysis
```

Modern document-processing systems are converging on this hybrid approach: native extraction where possible, OCR for image-based text, layout reconstruction, and selective multimodal processing for visually meaningful content. MinerU, PaddleOCR and Surya all provide self-hosted components covering parts or most of this pipeline.

## 2. Goals

Phase 50 should allow Reachy to:

1. ingest PDF, DOCX, TXT and Markdown documents;
2. retain the original uploaded file;
3. extract native document text and structure;
4. detect pages where native extraction is inadequate;
5. perform OCR locally where required;
6. identify meaningful visual content;
7. invoke multimodal understanding selectively;
8. retain page/section provenance;
9. index resulting evidence into the existing Reachy knowledge system;
10. support document-scoped Q&A;
11. summarize documents;
12. perform deeper document analysis;
13. cite relevant pages, sections or visual evidence;
14. expose document-processing coverage to the owner;
15. support deterministic reprocessing and deletion;
16. process documents without requiring cloud services;
17. support both background and latency-sensitive processing;
18. use heterogeneous homelab compute efficiently.

## 3. Non-goals

Phase 50 does not initially aim to:

* train a new OCR model;
* train a new embedding model;
* invent a new RAG architecture;
* implement arbitrary image-generation or image-editing capabilities;
* guarantee perfect understanding of every diagram or chart;
* turn OCR output into authoritative evidence;
* automatically execute actions extracted from documents;
* allow document contents to alter authorization or sensitivity policy;
* require Android document management in the first release;
* replace the existing knowledge/retrieval architecture.

## 4. Current state

Current Reachy documents are effectively stored as text/chunk records.

The current implementation lacks:

```text
document record
original file lifecycle
page-level provenance
document revisions
delete lifecycle
PDF parsing
DOCX structure parsing
OCR
visual document understanding
document-scoped chat context
document-processing jobs
document-processing status
document UI
```

Phase 44 knowledge indexing and the existing sensitivity/project-scope model remain the foundation downstream.

Phase 50 should reuse the asynchronous/job-processing patterns already established elsewhere rather than introduce a second unrelated task framework.

## 5. Binding evidence rule

### 5.1 Evidence hierarchy

Evidence must be divided into three classes.

**Authoritative source evidence**

```text
original uploaded file
native embedded text
original PDF page rendering
original embedded image
original DOCX/XML content
```

**Derived extraction**

```text
OCR text
layout reconstruction
reading order
table extraction
normalized structural representation
```

**Derived interpretation**

```text
VLM descriptions
diagram relationships
chart interpretations
summaries
executive summaries
technical analyses
model-generated classifications
```

OCR is derived extraction, not authoritative source evidence.

An OCR engine estimates the textual contents of an image and may make recognition errors. The original page remains authoritative.

### 5.2 Required properties

Every derived artifact MUST:

* preserve a link to its source;
* preserve document revision/hash;
* state its derivation type;
* never overwrite authoritative evidence;
* never grant authority;
* never lower sensitivity;
* be independently deletable;
* be reproducibly regenerable;
* be distinguishable from source evidence during audit;
* remain subject to prompt-injection protections.

The ADR below records this rule and is accepted.

ADR (accepted 2026-10-11): [ADR-0034 — Authoritative Source vs Derived Document Evidence](adr/0034-source-evidence-and-derived-artifacts.md)

## 6. High-level architecture

```text
                         ┌────────────────────┐
                         │ Original Document  │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         Document inspection
                                   │
                ┌──────────────────┼───────────────────┐
                │                  │                   │
                ▼                  ▼                   ▼
          Native extraction   OCR required       Visual content
                │                  │                   │
                │                  ▼                   ▼
                │             OCR backend        VLM analysis
                │                  │                   │
                └──────────────────┴───────────────────┘
                                   │
                                   ▼
                          NormalizedDocument
                                   │
                                   ▼
                        Reachy DocumentStore
                                   │
                                   ▼
                       embeddings / pgvector
                                   │
                                   ▼
                      Phase 44 knowledge index
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
                    scoped Q&A        document analysis
```

## 7. Stage 50A — Document lifecycle foundation

**Objective**

Create a proper first-class document object and lifecycle.

**Document model**

Proposed conceptual representation:

```text
Document
├── document_id
├── filename
├── title
├── mime_type
├── file_hash
├── source_revision
├── sensitivity
├── project_scope
├── page_count
├── size_bytes
├── processing_status
├── processing_version
├── created_at
└── updated_at
```

The original file must be stored separately from derived text/index data.

**Supported initial formats**

```text
PDF
DOCX
TXT
Markdown
```

**Lifecycle**

Required operations:

```text
upload
list
detail
processing status
download/view original
delete
reprocess
rename/update metadata
change permitted classification metadata
```

**Processing states**

```text
UPLOADED
INSPECTING
EXTRACTING
OCR
VISUAL_ANALYSIS
INDEXING
READY
PARTIAL
FAILED
DELETING
```

Failure of one page should not necessarily fail an entire 200-page document.

A document may reach:

```text
PARTIAL
```

if useful content was indexed but some pages or modalities failed.

## 8. Stage 50B — Native extraction and provenance

**Objective**

Build the authoritative native-text path before OCR or VLM processing.

For PDFs, maintain page-level information:

```text
DocumentPage
├── document_id
├── page_number
├── native_text
├── has_native_text
├── native_text_quality
├── image_count
├── image_coverage
├── likely_scan
├── likely_visual_content
├── page_hash
└── extraction_metadata
```

For DOCX, preserve structure where available:

```text
heading
paragraph
list
table
section
```

Generated chunks should include:

```text
document_id
source_revision
page_start
page_end
section
chunk_index
evidence_type = native_text
sensitivity
project_scope
```

Phase 50B must also identify pages that require additional processing.

Example:

```text
Page 1 → native text sufficient
Page 2 → native text sufficient
Page 3 → likely scan
Page 4 → large diagram + text
Page 5 → native text sufficient
```

## 9. Stage 50C — Pluggable OCR

**Objective**

Recover text from scanned/image-based content without requiring a VLM.

OCR must be an abstraction rather than a hard-coded dependency.

```text
OCRBackend
   │
   ├── PaddleOCR
   ├── MinerU
   ├── optional alternative
   └── benchmark baseline
```

Current candidates:

* PaddleOCR
* MinerU
* Surya
* Tesseract or equivalent baseline

PaddleOCR supports local inference and CPU deployment, which makes it appropriate for the Proxmox background worker. MinerU can also run in a pure-CPU pipeline mode, while its higher-quality local tiers can use GPU inference.

Surya provides OCR plus layout analysis, reading order and table recognition, but its model-weight licensing must be reviewed before any usage outside the permitted license conditions.

**OCR trigger**

Do not OCR every PDF page.

Candidate triggers:

```text
native character count below threshold
native text absent
page dominated by raster image
native text extraction malformed
user explicitly requests OCR
reprocessing policy requests stronger extraction
```

Store:

```text
PageOCR
├── document_id
├── page_number
├── backend
├── backend_version
├── OCR_text
├── confidence
├── positional metadata
└── created_at
```

Never overwrite native text with OCR output.

## 10. Stage 50D — Visual-content detection

**Objective**

Determine when OCR is insufficient and genuine visual understanding may be useful.

Proposed page classifications:

```text
TEXT_ONLY
SCAN_TEXT
TEXT_PLUS_VISUAL
VISUAL_DOMINANT
EMPTY
UNKNOWN
```

Signals may include:

```text
native-text quantity
OCR quantity
raster/image coverage
embedded image count
vector-object coverage
caption patterns
page layout
OCR/native extraction disagreement
```

Examples requiring potential VLM processing:

```text
architecture diagrams
flowcharts
charts
screenshots
dashboard captures
infographics
complex visual tables
annotated figures
```

The classifier does not need to be ML-based initially.

A deterministic heuristic implementation is acceptable for the first release.

## 11. Stage 50E — Multimodal visual understanding

**Objective**

Understand information encoded through visual relationships rather than merely characters.

OCR can recover:

```text
RAN
UPF-A
UPF-B
Firewall
```

but may not reliably recover:

```text
RAN → UPF-A
RAN → UPF-B
UPF-A → Firewall
```

The VLM path therefore receives:

```text
original page image
+
native text
+
OCR text
+
page metadata
```

and produces structured derived interpretation.

Example:

```text
VisualPageAnalysis
├── document_id
├── page_number
├── model
├── model_version
├── visual_elements
│   ├── type
│   ├── caption
│   ├── summary
│   ├── entities
│   ├── relationships
│   └── visible_labels
├── confidence metadata
└── source_revision
```

Do not use unrestricted prose alone if structured extraction can be produced.

Example:

```text
type: architecture_diagram

entities:
- RAN
- UPF-A
- UPF-B
- Firewall

relationships:
- RAN -> UPF-A
- RAN -> UPF-B
- UPF-A -> Firewall
- UPF-B -> Firewall
```

**VLM deployment**

Do not introduce a third permanently resident GPU model.

The VLM should operate as an on-demand workload.

A model is not selected in the planning stage.

Candidate models are evaluated later on:

```text
diagram understanding
chart understanding
OCR augmentation
VRAM
latency
loading time
accuracy
licence
structured output quality
```

## 12. Stage 50F — Normalized multimodal representation

**Objective**

Present one stable representation to downstream Reachy components.

```text
NormalizedDocument
├── metadata
├── source_revision
└── pages
    ├── Page 1
    │   ├── authoritative source refs
    │   ├── native text
    │   ├── OCR
    │   ├── layout
    │   └── visual interpretation
    │
    └── Page N
```

Knowledge chunks may then use:

```text
KnowledgeChunk
├── document_id
├── source_revision
├── page_start
├── page_end
├── section
├── content
├── evidence_type
│   ├── native_text
│   ├── OCR
│   ├── layout
│   ├── table
│   ├── visual_description
│   └── visual_relationship
├── sensitivity
├── project_scope
└── embedding
```

Phase 44 should continue to consume knowledge units rather than becoming PDF-aware.

## 13. Stage 50G — Document-scoped conversation

**Objective**

Allow the owner to ask questions about a particular document rather than relying on global retrieval.

Introduce:

```text
context_document_id
```

with a future migration toward:

```text
context_sources[]
```

Example:

```text
Upload Architecture.pdf
        ↓
Open document
        ↓
Ask Reachy
        ↓
"What connects the RAN layer to analytics?"
```

Retrieval should constrain:

```text
document_id = requested document
```

while searching across its available modalities.

A later query can deliberately broaden context:

```text
document + meeting
document + second document
document + notes
```

but global knowledge should not automatically contaminate document-scoped Q&A.

## 14. Stage 50H — Summarization and analysis

Document summarization must be separate from ordinary RAG Q&A.

**Small documents**

```text
NormalizedDocument
       ↓
local model
       ↓
summary
```

**Large documents**

```text
sections / page groups
       ↓
intermediate summaries
       ↓
document-level synthesis
       ↓
final summary
```

Meaningful visual evidence should be included in synthesis.

Otherwise a report may be summarized successfully while omitting important information shown only in diagrams or charts.

**Output object**

```text
DocumentOutput
├── document_id
├── source_revision
├── type
│   ├── summary
│   ├── executive_summary
│   ├── technical_review
│   ├── deep_analysis
│   └── custom_analysis
├── content
├── citations
├── model
├── model_tier
└── generated_at
```

Supported user workflows should eventually include:

```text
Summarize this document.
Give me an executive summary.
What are the main risks?
What decisions are required?
What deadlines are present?
What does it say about security?
Compare section A with section B.
Find contradictions.
Explain this section.
Give me a technical review.
Compare this document with another document.
Compare this with my meeting notes.
```

## 15. Stage 50I — Heterogeneous processing scheduler

**Objective**

Exploit both:

* the MS-01 RTX 2000E Ada GPU,
* and the Proxmox CPU/RAM resources.

Document workloads should be represented as portable jobs rather than being tied to one machine.

**Priority classes**

*BACKGROUND*

Use when:

* document uploaded for later use;
* user does not require immediate response;
* batch processing is acceptable.

Default worker:

```text
Proxmox CPU
```

Expected tasks:

```text
native parsing
OCR
layout processing
embedding preparation
full-document background processing
```

*NORMAL*

Use for ordinary document requests where some delay is acceptable.

Default:

```text
Proxmox CPU
higher queue priority
```

*INTERACTIVE / URGENT*

Use when the owner requires an answer immediately.

Execution:

```text
MS-01 GPU
```

The GPU becomes a latency-acceleration resource.

**Scheduler model**

```text
                    DocumentJob
                         │
                         ▼
                 priority / needs
                  ┌──────┴───────┐
                  │              │
             BACKGROUND        URGENT
                  │              │
                  ▼              ▼
          Proxmox CPU        MS-01 GPU
```

Proposed job fields:

```text
DocumentJob
├── job_id
├── document_id
├── priority
├── job_type
├── requires_ocr
├── requires_vision
├── page_scope
├── estimated_pages
├── sensitivity
├── project_scope
├── created_at
├── started_at
├── status
└── worker_id
```

Workers advertise capabilities rather than jobs specifying hosts.

Example:

```text
Worker: proxmox-doc-01
CPU = yes
OCR = yes
Vision = no
Background = yes

Worker: ms01-doc-gpu
GPU = yes
OCR = yes
Vision = yes
Interactive = yes
```

### 15.1 GPU priority processing

The MS-01 currently uses its GPU for Reachy's local LLM service.

Urgent document processing may temporarily reclaim this GPU.

Where compatible with the deployed vLLM version/configuration, vLLM Sleep Mode can release most GPU memory without destroying the serving container. The feature supports CUDA and provides sleep/wake control, allowing another GPU workload to use the released memory.

Potential flow:

```text
urgent document request
        ↓
allow active LLM request to finish
        ↓
place vLLM into GPU-sleep / release state
        ↓
start GPU OCR/VLM processing
        ↓
process priority pages
        ↓
persist results
        ↓
release document model
        ↓
wake / restore vLLM
        ↓
normal Reachy service resumes
```

If sleep mode proves unsuitable operationally, the fallback remains explicit unload/reload orchestration.

This should be benchmarked rather than assumed. The swap procedure, its timing and its failure cases (the 7B must come back) need the same measured rehearsal [ADR 0031](adr/0031-three-tier-local-model-escalation.md) required, and may need an amendment to it.

### 15.2 Partial urgent processing

An urgent request should not automatically require processing an entire large document.

Example:

```text
200-page PDF uploaded

User:
"What does this say about data retention?"
```

Possible fast path:

```text
quick native extraction
       ↓
initial lexical/semantic narrowing
       ↓
identify candidate pages
       ↓
priority OCR/vision on those pages
       ↓
answer user
       ↓
remainder continues on Proxmox
```

The document therefore supports incremental processing.

Page state might include:

```text
UNPROCESSED
NATIVE_DONE
OCR_DONE
VISUAL_DONE
INDEXED
```

A background task can continue after an interactive answer has already been produced.

### 15.3 Job escalation

The owner must be able to escalate a running job:

```text
BACKGROUND
    ↓
INTERACTIVE
```

Already completed work must be reused.

Escalation must not restart the document from page 1 unless necessary.

Example:

```text
Pages 1–35 already OCR'd on Proxmox
                    ↓
user escalates
                    ↓
MS-01 continues from remaining/relevant pages
```

The inverse should also be possible:

```text
INTERACTIVE portion completed
        ↓
remaining pages
        ↓
BACKGROUND Proxmox worker
```

## 16. Storage and retention

Keep:

```text
original/
derived/
```

logically separate.

Suggested hierarchy:

```text
Document
├── original
│   ├── file
│   ├── SHA-256
│   └── metadata
│
└── derived
    ├── native extraction
    ├── OCR
    ├── layout
    ├── visual analysis
    ├── chunks
    ├── embeddings
    └── document outputs
```

Reprocessing creates new derived artifacts against a source revision.

The original should not be rewritten.

The physical location of originals and page images (volume or database), their backup coverage, and whether page images are kept or regenerated are decided at 50A start.

**Delete**

Delete must cascade across:

```text
original file
page records
OCR output
visual interpretations
chunks
embeddings
knowledge-index rows
summaries
analysis outputs
processing jobs
cached derivatives
```

After deletion, the deleted document must no longer be retrievable through semantic search.

Deletion behaviour must have regression tests.

## 17. Sensitivity and trust

Documents, OCR results and visual-model outputs are untrusted data.

They cannot:

* authorize an action;
* change owner identity;
* lower privacy classification;
* override Reachy policy;
* issue tool commands;
* alter routing policy;
* directly create authoritative tasks/reminders without review.

At upload, sensitivity must either:

1. be explicitly selected by the owner; or
2. inherit a conservative default.

Automatic document classification may later recommend:

```text
"This appears to contain sensitive material."
```

but must never automatically lower a classification.

Cloud processing follows the existing Reachy privacy policy.

No document should silently leave the local environment.

## 18. File and resource limits

Do not permanently select arbitrary production limits during planning.

Limits should initially be configurable:

```text
maximum upload bytes
maximum pages
maximum page image resolution
maximum OCR runtime
maximum VLM pages
maximum concurrent jobs
maximum derived-storage size
```

Phase 50J will establish reasonable defaults from real measurements.

## 19. Candidate document-processing stack

**Primary candidate: MinerU**

MinerU should be benchmarked as a potential complete document-processing layer rather than automatically rebuilding every parser ourselves.

Current MinerU supports local document parsing through CLI, WebUI and API-style services. Its local stack supports basic CPU-oriented processing and higher-quality GPU tiers; current documentation lists 8 GB+ VRAM for its standard NVIDIA GPU setup.

It can therefore potentially cover parts of:

```text
50B native extraction
50C OCR
50D layout analysis
50E visual/document interpretation
50F normalized output
```

**PaddleOCR**

PaddleOCR remains a strong candidate for the dedicated CPU OCR path on Proxmox.

The key appeal is:

```text
self-hosted
CPU capable
lightweight
no GPU residency requirement
```

**Surya**

Surya should be evaluated as an alternative OCR/layout pipeline.

Its current capabilities include OCR, layout analysis, reading order and table recognition.

However, model licensing must be explicitly reviewed before adoption.

**Decision rule**

Do not choose based on GitHub popularity alone.

Choose from empirical results on Reachy's evaluation corpus.

Whatever is chosen runs in an isolated document-worker container or job, never inside companion-core; image size, licence and supply-chain review apply.

## 20. Stage 50J — Evaluation and benchmarking

Evaluation starts during 50B and grows through subsequent stages.

Do not wait until implementation is complete.

**Evaluation corpus**

Create a frozen corpus containing:

```text
born-digital PDF
clean scan
poor scan
mixed native/scanned PDF
DOCX
multi-column report
screenshot-heavy document
architecture diagram
flowchart
chart
table
long document
```

Some documents should intentionally contain answers only in specific modalities.

Examples:

```text
Q1 → native text only
Q2 → scanned text only
Q3 → screenshot text only
Q4 → diagram relationship only
Q5 → chart interpretation
Q6 → text + visual evidence
Q7 → deliberately unanswerable
```

The corpus uses synthetic or owner-approved documents only; nothing private is committed.

### 20.1 Evaluation layers

**Extraction coverage**

Measure:

```text
page extraction coverage
OCR recovery
OCR error rate where ground truth exists
layout preservation
reading-order correctness
visual-page detection recall
```

**Retrieval**

Measure:

```text
Recall@K
correct-page retrieval
correct-section retrieval
correct-modality retrieval
evidence coverage
```

**Groundedness**

Measure:

```text
citation correctness
answer entailment
unsupported claims
hallucination rate
abstention correctness
```

**Summarization**

Measure:

```text
important-detail coverage
faithfulness
citation support
visual-content inclusion
long-document degradation
```

**Compute**

Measure separately for:

```text
Proxmox CPU
MS-01 GPU
```

Metrics:

```text
pages/minute
time-to-first-usable-page
full-document processing time
CPU utilisation
RAM utilisation
GPU VRAM
GPU utilisation
model switching time
vLLM disruption
job escalation latency
energy where practical
```

**Practical value**

Evaluation must answer:

> Does this pipeline make Reachy materially better at answering realistic questions from documents?

A system that passes technical extraction tests but rarely retrieves useful evidence should not be promoted.

### 20.2 OCR benchmark

At minimum benchmark:

```text
PaddleOCR
MinerU pipeline
Surya if licensing permits
baseline OCR engine
```

Against:

```text
clean print
poor scan
small text
screenshots
multi-column layouts
tables
mixed language if relevant
```

Do not benchmark OCR solely using speed.

The relevant trade-off is:

```text
accuracy
layout preservation
resource cost
integration complexity
reliability
licensing
```

### 20.3 VLM benchmark

VLM selection occurs only after the extraction pipeline exists.

Evaluate candidate local VLMs against a frozen set of:

```text
architecture diagrams
charts
flowcharts
dashboard screenshots
complex tables
text + diagram combinations
```

Measure:

```text
relationship accuracy
factual grounding
structured-output validity
VRAM
model load time
page latency
failure rate
```

The selected VLM must fit the MS-01 on-demand workload model.

There is no requirement for it to remain permanently resident.

## 21. Stage 50K — Web Documents experience

Add a top-level Documents surface.

Example:

```text
Brain
Meetings
Notes
Tasks
Documents
```

**Library**

```text
Documents

[ Upload ]

Architecture Review.pdf
46 pages
Ready
Work Private

Tender Response.docx
72 pages
Processing
Confidential
```

**Detail view**

```text
Architecture Review.pdf

46 pages
38 native pages
5 OCR pages
3 visual-analysis pages

Processing coverage: Complete

[ Ask Reachy ]
[ Summarize ]
[ Deep Analysis ]
[ Prioritize ]
[ Reprocess ]
[ Delete ]
```

**Processing transparency**

Never merely display:

```text
Processed
```

when processing was partial.

Prefer:

```text
46 / 46 pages processed

Native text: 38
OCR: 5
Visual analysis: 3

Coverage: Complete
```

or:

```text
42 / 46 pages processed

4 pages require additional processing

Coverage: Partial
```

This is a trust requirement rather than cosmetic UI.

### 21.1 User-facing priority controls

Default uploaded documents to background processing unless the interaction clearly requires immediate results.

Potential UI:

```text
Processing priority

○ Background
● Normal
○ Priority
```

Reachy may suggest escalation:

> This document is still being processed in the background. Prioritize it now?

Explicit owner escalation overrides normal routing.

Priority may also be inferred from intent:

```text
"Process this later."
→ BACKGROUND

"Summarize this when ready."
→ NORMAL/BACKGROUND

"Tell me what this says right now."
→ INTERACTIVE
```

Automatic GPU displacement should remain subject to policy so a low-value task cannot continually interrupt normal Reachy inference.

## 22. Android scope

Android document management is not required for the initial Phase 50 promotion.

Initial mobile scope may be limited to:

```text
ask questions about already-ingested documents
view existing summaries
view citations
```

Full Android functionality can follow after Web lifecycle behaviour is stable:

```text
upload
document viewer
reprocess
delete
priority management
```

## 23. Interaction with Phase 48 / 49

Phase 50 touches knowledge retrieval and therefore must not invalidate ongoing acceptance measurements.

Planning and isolated Phase 50 engineering may proceed.

Production retrieval changes must not contaminate frozen Phase 48/49 evaluations.

If necessary:

```text
Phase 50 indexing enabled = false
```

until relevant existing acceptance work completes.

This allows implementation progress without making prior benchmark results incomparable.

## 24. First useful release candidate

The first useful release does not require full multimodal support.

A sensible first release consists of:

```text
50A — lifecycle
50B — native extraction/provenance
50F — normalized document representation
50G — document-scoped Q&A
basic 50K UI
```

This yields:

```text
native-text PDF/DOCX/TXT/MD
        ↓
document scoped retrieval
        ↓
page/section citations
        ↓
Reachy Q&A
```

OCR and visual processing can then extend coverage without redesigning the downstream system.

## 25. Proposed implementation order

```text
ADR-0034
   ↓
50A — document lifecycle
   ↓
50B — native extraction/provenance
   ↓
start frozen evaluation corpus
   ↓
50C — pluggable OCR
   ↓
50D — visual-content detection
   ↓
50E — multimodal analysis
   ↓
50F — normalized representation
   ↓
50G — scoped retrieval
   ↓
50H — summarization/analysis
   ↓
50I — heterogeneous scheduler
   ↓
50J — final benchmark/promotion evaluation
   ↓
50K — complete Documents UX
```

The order may overlap where dependencies permit.

## 26. Promotion gates

**G1 — Source integrity**

Pass if:

* original file is retained;
* source hash is verified;
* derived artifacts cannot overwrite source evidence.

**G2 — Native extraction**

Pass if supported digital documents can reliably produce page/section-grounded text.

**G3 — OCR**

Pass if scanned-text evidence can be recovered to an acceptable quality.

**G4 — Visual understanding**

Pass if evidence present only through meaningful visual relationships can be recovered above the defined benchmark threshold.

**G5 — Retrieval**

Pass if frozen retrieval tests meet their predefined evidence-recall threshold.

**G6 — Grounding**

Pass if answers cite correct document/page/section evidence at the defined threshold.

**G7 — Abstention**

Pass if Reachy reliably refuses or qualifies answers when the document lacks sufficient evidence.

**G8 — Lifecycle**

Pass if deletion/reprocessing deterministically removes or replaces stale chunks, embeddings and outputs.

**G9 — Privacy and authorization**

Pass if document content cannot alter authority, reduce sensitivity or bypass channel/tool policy.

**G10 — UX transparency**

Pass if the owner can determine:

```text
what was processed
which modality was used
whether processing is complete
whether derived interpretation was involved
```

## 27. Promotion outcomes

Phase 50 uses:

```text
PROMOTE
NARROW
DO NOT PROMOTE
```

Examples:

**PROMOTE**

All core modalities meet acceptable quality and trust thresholds.

**NARROW**

Example:

```text
native text + OCR reliable
visual reasoning unreliable
```

Then Reachy may advertise:

> PDF/DOCX text and scanned-document support

without claiming full diagram understanding.

**DO NOT PROMOTE**

Use if retrieval, grounding, deletion, authorization or provenance fail materially.

Passing safety tests alone is insufficient if practical document coverage remains poor.

## 28. Expected deployment architecture

```text
                        ┌─────────────────┐
                        │ Reachy Web/App  │
                        └────────┬────────┘
                                 │
                                 ▼
                         Reachy Core / API
                                 │
                         document job queue
                                 │
              ┌──────────────────┴──────────────────┐
              │                                     │
              ▼                                     ▼
       Proxmox document worker                MS-01 GPU worker
       CPU / RAM                              RTX 2000E Ada
              │                                     │
       native parsing                              OCR optional
       PaddleOCR / MinerU CPU                     VLM analysis
       layout work                                 priority work
       background queue                            interactive queue
              │                                     │
              └──────────────────┬──────────────────┘
                                 ▼
                       NormalizedDocument
                                 │
                                 ▼
                       DocumentStore / DB
                                 │
                                 ▼
                      embeddings / pgvector
                                 │
                                 ▼
                    Phase 44 knowledge index
                                 │
                 ┌───────────────┴────────────────┐
                 ▼                                ▼
              Ask Reachy                   Summarize / Analyse
```

## 29. Architectural conclusions

Phase 50 should not be viewed as another RAG build.

The existing Reachy knowledge system remains the retrieval foundation.

The new engineering concerns are:

```text
file lifecycle
document structure
page provenance
OCR
visual understanding
processing scheduling
heterogeneous compute
document outputs
user-facing document workflows
```

The primary design principle is:

> Convert heterogeneous documents into well-provenanced evidence without losing the distinction between what the document actually contains and what a model inferred from it.

The compute principle is:

> Use cheap CPU capacity for throughput and reserve GPU disruption for latency-sensitive workloads.

The scheduling model therefore becomes:

```text
BACKGROUND / NORMAL
        ↓
Proxmox CPU slow-burn processing

INTERACTIVE / PRIORITY
        ↓
MS-01 GPU acceleration
        ↓
restore normal LLM service afterward
```

This architecture also leaves Reachy extensible beyond PDFs.

The same evidence pipeline could later ingest:

```text
presentation slides
scanned notes
whiteboards
screenshots
camera captures
technical diagrams
image attachments
```

without redesigning the knowledge subsystem.
