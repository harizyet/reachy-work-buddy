# Phase 50 — MinerU-backed Document Intelligence

## Status

**Proposed / plan-only.**

Phase 50 introduces first-class document intelligence into Reachy using MinerU as the selected document-processing and document-content backend.

This phase is primarily an engineering and integration phase, not a document-AI research or comparative benchmarking phase.

The implementation will not build a new OCR stack, document parser, layout engine, document database, or document search subsystem unless MinerU is proven incapable of satisfying a required contract during implementation.

MinerU 4.0 already provides:

* local document parsing;
* a local document library;
* stable document/page/block locators;
* parsing caches;
* background parsing;
* OCR;
* multiple document-processing tiers;
* structured Markdown/content output;
* document search and read operations;
* Python SDK access;
* self-hosted HTTP API;
* local model operation;
* CPU and GPU-capable execution paths.

MinerU explicitly positions its document library and locators for agent reading workflows, while remaining separate from higher-level chat/RAG orchestration.

## 1. Architectural decision

Phase 50 adopts the following ownership boundary:

```text
Reachy
=
document identity
authoritative original file (content-addressed, SHA-256)
policy
authorization
sensitivity
project scope
processing orchestration
user interaction
reasoning
cross-source memory
derived Reachy outputs

MinerU
=
derived document library and cache
(a working copy of the source, never the system of record)
document parsing
OCR
layout/document structure
document library
parsed representation
page/block locators
document reading
document-local search
processing cache
```

The key relationship is pointer-like:

```text
ReachyDocument
        │
        │ stable backend reference
        ▼
MinerU document object
```

The original file is stored once in Reachy's own source store, content-addressed by SHA-256 and re-verified on read, as [ADR 0034](adr/0034-source-evidence-and-derived-artifacts.md) requires. MinerU ingests and reads that source and maintains its own derived representation; if its cache format or library changes, nothing authoritative is lost.

Reachy does not duplicate the complete MinerU representation into its own database.

Instead, Reachy stores a stable logical reference to the corresponding MinerU document.

This is conceptually similar to a typed pointer/reference in systems programming, but the reference is persistent and logical rather than an in-memory address.

## 2. Goals

Phase 50 should allow the owner to:

1. upload documents to Reachy;
2. ingest them into a self-hosted MinerU document library;
3. preserve Reachy sensitivity and project-scope controls;
4. ask Reachy questions scoped to one document;
5. retrieve source evidence by MinerU page/block locator;
6. summarize documents;
7. perform deeper document analysis;
8. work with born-digital and scanned PDFs;
9. work with images and supported Office/document formats;
10. process documents locally;
11. choose normal/background or priority processing;
12. escalate a background job when immediate results are required;
13. use CPU resources for slow-burn work;
14. reclaim GPU resources for urgent/high-complexity processing;
15. delete a document and all associated Reachy references/derived outputs;
16. expose processing status and provenance to the owner.

## 3. Non-goals

Phase 50 does not aim to:

* build a custom OCR engine;
* benchmark competing OCR stacks;
* benchmark MinerU against Surya/PaddleOCR/Tesseract;
* build a custom PDF parser;
* build a second document vector database;
* recreate MinerU's document library;
* train a document model;
* select between multiple document-processing frameworks;
* perform academic document-AI benchmarking;
* add another permanently resident GPU model;
* allow document contents to issue trusted commands;
* let MinerU own Reachy's privacy or authorization policy.

Testing still exists, but it is acceptance and regression testing, not comparative research.

## 4. Why MinerU

MinerU 4.0 already covers most of the engineering previously proposed for Phase 50.

Its supported local input types currently include PDF, images, DOC/DOCX, PPT/PPTX, XLS/XLSX, RTF, OpenDocument formats, EPUB, OFD, HTML/MHTML and CSV/TSV. Plain text can be read directly.

MinerU provides four parsing tiers:

```text
Flash
Basic
Standard
Advanced
```

with different trade-offs between native extraction, OCR/model processing and more demanding document layouts.

It also provides a local document library capable of:

```text
file identity
parsing cache
background parsing
search
page/block reading
stable locators
cleanup
result invalidation
```

through its CLI and Python `DoclibClient`.

Therefore the implementation preference is:

> Integrate MinerU well rather than rebuild MinerU inside Reachy.

## 5. Binding evidence rule

The architectural invariant remains:

> **Derived interpretation never replaces source evidence.**

[ADR 0034](adr/0034-source-evidence-and-derived-artifacts.md) (accepted 2026-10-11) remains the governing architectural decision for this evidence hierarchy.

### 5.1 Evidence classes

**Authoritative source**

```text
original uploaded document
original page/image content
native source content
source hash
```

**Derived extraction**

```text
MinerU parsed text
OCR output
layout reconstruction
table extraction
reading order
normalized blocks
```

**Derived interpretation**

```text
Reachy summary
Reachy analysis
VLM-derived interpretation
cross-document synthesis
task suggestions
risk extraction
decision extraction
```

OCR remains derived extraction because OCR can make recognition errors.

### 5.2 Required properties

Every derived artifact must:

* retain source provenance;
* identify its derivation type;
* remain tied to a document revision/hash;
* never overwrite authoritative source evidence;
* remain subject to prompt-injection protections;
* never grant authority;
* never lower sensitivity;
* be removable when the document is deleted;
* be re-creatable from source evidence where practical.

## 6. Reachy document object

Reachy's database stores the policy-aware object.

Conceptually:

```text
ReachyDocument
├── document_id
├── title
├── filename
├── source_hash
├── source_store_ref   (Reachy's authoritative original)
├── mime_type
├── sensitivity
├── project_scope
├── status
├── backend
├── backend_ref
├── backend_revision
├── processing_priority
├── created_at
└── updated_at
```

Example:

```text
backend = "mineru"

backend_ref =
"doc:ab12cd3"

backend_revision =
source SHA-256 / MinerU parse generation
```

The exact MinerU identifier/locator format must use MinerU's supported API contract rather than Reachy constructing undocumented identifiers.

MinerU's current library returns document identifiers and stable locators for page/block continuation and later reads.

## 7. Pointer/reference model

Reachy should treat `backend_ref` as an opaque typed reference.

Conceptually:

```text
DocumentBackendRef(
    backend="mineru",
    external_id="...",
    revision="..."
)
```

Higher-level Reachy code must not depend directly on MinerU internals.

Instead expose an interface such as:

```text
DocumentBackend
├── ingest()
├── status()
├── get_metadata()
├── search()
├── read()
├── read_page()
├── read_block()
├── parse()
├── invalidate()
└── delete()
```

The initial implementation is:

```text
MinerUDocumentBackend
```

This abstraction preserves future optionality without making alternative backends part of Phase 50.

## 8. Stage 50A — MinerU service foundation

**Objective**

Deploy MinerU as a self-hosted Reachy infrastructure service.

MinerU supports a self-hosted V1 API:

```text
mineru-kit api-server \
  --host 0.0.0.0 \
  --port 8000 \
  --tier standard
```

and exposes `/v1/*` endpoints for service health, capabilities, uploads, files, parse jobs and usage.

MinerU also supports a local document-library service controlled through:

```text
mineru server start
mineru server status
mineru server stop
```

and programmatic access through `DoclibClient`.

**Deployment rule**

MinerU runs in an isolated document-processing service/container.

It must not run inside `companion-core`.

The document service has its own:

```text
dependencies
model assets
persistent storage
logs
resource limits
health check
network policy
upgrade lifecycle
```

## 9. Stage 50B — Reachy document lifecycle

**Objective**

Introduce first-class documents into Reachy's policy model.

Required operations:

```text
upload
list
detail
status
open/use
delete
reprocess
change permitted metadata
```

Processing states:

```text
UPLOADED
QUEUED
PROCESSING
READY
PARTIAL
FAILED
DELETING
```

The Reachy record and MinerU object must remain linked through `backend_ref`.

## 10. Stage 50C — Document ingestion

**Upload flow**

```text
user upload
    ↓
Reachy validates request
(type by content, configurable limits)
    ↓
Reachy assigns:
    sensitivity
    project scope
    document ID
    source hash
    ↓
original stored once in Reachy's source store
(content-addressed, hash verified)
    ↓
copy sent to local MinerU service
    ↓
MinerU creates/identifies document
    ↓
MinerU returns document reference
    ↓
Reachy stores backend_ref
    ↓
processing begins
```

MinerU can parse local documents through both its library workflow and its stateless/service APIs. The Phase 50 integration should prefer the library-backed route where stable document identity and locators are required.

**Sensitivity at upload.** Upload requires an explicit classification wherever the UI supports it; otherwise Reachy's conservative default applies. Sensitivity is never inferred by a model. Extracted document content may suggest a stricter classification but may never lower one automatically.

**Limits.** Upload bytes, pages, page-image resolution and processing time are configurable. Defaults are chosen conservatively at 50A from operational testing on the real hosts; this is not a benchmark exercise.

## 11. Stage 50D — MinerU processing tiers

Phase 50 adopts MinerU's own parsing tiers instead of creating a parallel Reachy OCR/VLM taxonomy.

Current MinerU tiers are:

```text
Flash
Basic
Standard
Advanced
```

MinerU documents these broadly as increasing levels of processing capability, with PDF/images supporting all four tiers and native Office/document formats generally using local Flash parsing.

Reachy maps user intent onto MinerU tiers.

Suggested initial policy:

```text
BACKGROUND document ingest
→ Flash or Basic as appropriate

ordinary scanned document
→ Basic

interactive document analysis
→ Standard

explicit deep/complex visual analysis
→ Standard/Advanced where supported
```

Exact tier-selection rules are implementation policy, not research questions.

## 12. Stage 50E — Document-scoped conversation

**Objective**

Allow Reachy to reason over one specific document.

Introduce:

```text
context_document_id
```

with the longer-term ability to generalize toward:

```text
context_sources[]
```

Flow:

```text
User:
"What are the mandatory security requirements?"

        ↓

Reachy resolves context_document_id

        ↓

Reachy policy check

        ↓

resolve backend_ref

        ↓

MinerU search/read

        ↓

page/block evidence

        ↓

Reachy LLM

        ↓

answer + citations
```

MinerU's document library supports search and later `read` calls using returned document/page/block locators, making it suitable for bounded agent reading rather than injecting an entire document into one context window.

## 13. Stage 50F — Retrieval integration

Documents become a federated knowledge source behind the existing Phase 44 retrieval semantics. MinerU is another physical retrieval backend, not a way around them.

```text
Phase 44 retriever
       │
       ├── Reachy pgvector sources
       │
       └── MinerUDocumentRetriever
                 │
                 ├── Reachy authorization check
                 ├── sensitivity / project-scope check
                 ├── source-hash / revision validation
                 ├── MinerU search / read
                 └── normalize to Reachy Evidence
```

The adapter must perform, before any MinerU text can enter a prompt, the same responsibilities the Phase 44 index performs for its own sources: the trusted access context, retrieval-time revalidation against the Reachy record (the document exists, is not deleting, and its hash and revision match the backend reference), the channel's sensitivity ceiling, and fail-closed behaviour when MinerU is unavailable or returns an unknown locator. Its output is the same `Evidence` shape the context builder already consumes, with `evidence_type` and the MinerU locator as provenance. It is built and tested against the Phase 44 leakage and revalidation cases before it is enabled.

Reachy's existing knowledge sources remain:

```text
memory
notes
tasks
meetings
```

Documents use:

```text
MinerU
```

Conceptually:

```text
Reachy retrieval
      │
      ├── memory   → Reachy DB/pgvector
      ├── notes    → Reachy DB/pgvector
      ├── meetings → Reachy DB/pgvector
      ├── tasks    → Reachy stores
      │
      └── documents → MinerU
```

This avoids unnecessarily copying MinerU's entire parsed document representation into Reachy's pgvector database.

**Retrieval policy**

Document-scoped queries should prefer MinerU directly.

Cross-source questions may federate results.

Example:

```text
"Compare this tender with yesterday's meeting."
```

becomes:

```text
MinerU document evidence
        +
Reachy meeting evidence
        ↓
Reachy synthesis
```

## 14. Stage 50G — Provenance and citations

Reachy responses must retain MinerU evidence locators.

Internal evidence may look like:

```text
document_id
backend_ref
MinerU locator
page
block
source hash
derivation type
```

User-facing citation:

```text
Architecture Report.pdf
Page 17
Figure / section where available
```

MinerU 4.0 explicitly provides stable locators intended for continued reading and citations across page/block boundaries.

Reachy should never fabricate page numbers from chunk position.

## 15. Stage 50H — Summarization and analysis

Summarization is distinct from document search.

**Short/small document**

```text
MinerU document
      ↓
bounded reads
      ↓
Reachy local LLM
      ↓
summary
```

**Long document**

```text
MinerU page/block traversal
      ↓
section/page-group synthesis
      ↓
intermediate summaries
      ↓
final synthesis
```

MinerU's locators and continuation mechanism allow long documents to be read progressively rather than loading the full file into one model context.

Reachy outputs may include:

```text
summary
executive summary
technical review
deep analysis
risk extraction
decision extraction
deadline extraction
comparison
simplification
```

These remain Reachy-derived interpretation, not MinerU source evidence.

## 16. Stage 50I — Heterogeneous processing scheduler

**Objective**

Use the existing homelab efficiently.

Two execution paths are supported.

### 16.1 Background / normal path

Runs on the Proxmox document worker.

```text
upload
   ↓
Reachy job queue
   ↓
Proxmox MinerU worker
   ↓
CPU/RAM processing
   ↓
MinerU library updated
   ↓
Reachy status = READY
```

This path is intended for:

```text
documents uploaded for later
normal indexing
background parsing
slow OCR
large batch jobs
non-urgent document preparation
```

The job may take longer.

That is acceptable because it avoids disrupting interactive Reachy inference.

MinerU supports local CPU-oriented operation; its current default installation includes ONNX small-model inference and local VLM/runtime options, while native/Flash parsing can operate without requiring the main NVIDIA inference path.

### 16.2 Interactive / priority path

Used when the user explicitly requires immediate processing.

```text
user prioritizes document
        ↓
Reachy marks job INTERACTIVE
        ↓
active LLM request finishes
        ↓
MS-01 GPU made available
        ↓
priority MinerU processing
        ↓
required evidence produced
        ↓
Reachy answers user
        ↓
normal LLM service restored
```

GPU resource handoff must follow the measured/rehearsed model-switching requirements already established in [ADR 0031](adr/0031-three-tier-local-model-escalation.md).

Phase 50 does not create a competing GPU-lifecycle policy.

## 17. Processing priorities

Support three logical priorities:

```text
BACKGROUND
NORMAL
INTERACTIVE
```

**BACKGROUND**

Default for passive upload.

```text
worker = Proxmox
latency = unimportant
```

**NORMAL**

User intends to use the document but is not waiting interactively.

```text
worker = Proxmox
queue priority = elevated
```

**INTERACTIVE**

User requires results now.

```text
worker = MS-01 / accelerated path
latency = priority
```

## 18. User escalation

A job may be promoted:

```text
BACKGROUND
    ↓
INTERACTIVE
```

without throwing away completed work.

Example:

```text
Proxmox has already processed pages 1–40
                ↓
owner selects Prioritize
                ↓
priority worker continues from available state
```

After the urgent portion completes:

```text
remaining work
    ↓
returns to BACKGROUND
```

The scheduler must avoid unnecessary duplicate parsing where MinerU already has cached results.

MinerU's library manages parsing caches and existing parse state, which should be reused rather than bypassed.

## 19. Fast evidence-first answering

Interactive use does not always require full-document processing.

Example:

```text
200-page document

User:
"What is the retention requirement?"
```

Target flow:

```text
available native/Flash parse
        ↓
search/narrow likely evidence
        ↓
process/read relevant section
        ↓
answer user
        ↓
remaining document continues in background
```

MinerU's bounded page/block reads and continuation model make this preferable to waiting for the entire document where sufficient evidence is already available.

## 20. MinerU model execution

MinerU model execution should remain local unless Reachy's owner explicitly allows another path.

MinerU supports:

```text
small models:
ONNX
Torch

VLM engines:
llama.cpp
vLLM
LMDeploy
```

and supports local model paths through:

```text
MINERU_MODEL_SOURCE=local
```

when required model assets have already been downloaded.

The chosen runtime on each worker is an engineering deployment decision.

No comparative model study is required by Phase 50.

## 21. Storage architecture

The exact physical storage location must be decided at 50A start.

Reachy's source store is authoritative for the original; MinerU's storage is derived and rebuildable from it.

Logical ownership:

```text
Reachy authoritative store
├── original file
├── SHA-256
└── (hash re-verified on read)

Reachy DB
├── ReachyDocument
├── sensitivity
├── project_scope
├── backend_ref
├── source hash
├── processing state
├── Reachy summaries
└── Reachy analyses


MinerU persistent storage
├── working copy of the source (derived)
├── document identity
├── parse cache
├── parsed representation
├── OCR/layout/model results
├── page/block locators
└── document search/index state
```

Questions to settle at implementation start:

```text
physical location of Reachy's source store and its backup
physical MinerU data path
backup coverage
filesystem/storage pool
retention policy
page-image persistence
whether page renderings are retained or regenerated
```

These are operational decisions, not research tasks.

## 22. Deletion

Deletion must remove both layers.

Flow:

```text
Delete document
      ↓
Reachy authorization check
      ↓
delete/invalidate MinerU document
      ↓
delete the original from Reachy's source store
      ↓
remove Reachy backend_ref
      ↓
remove Reachy-derived summaries/analysis
      ↓
remove document knowledge references
      ↓
verify retrieval no longer returns document
```

Delete should cover:

```text
Reachy original file (source store)
MinerU source copy / library object
MinerU parse/cache data
Reachy document record
Reachy summaries
Reachy analyses
cross-source references where appropriate
queued jobs
cached responses where appropriate
```

Deletion correctness is a mandatory acceptance gate.

## 23. Reprocessing

Reprocessing should not create a second unrelated Reachy document.

Conceptually:

```text
same Reachy document_id
same authoritative source (Reachy's stored original, hash re-verified)
        ↓
MinerU parse invalidation/reparse
        ↓
new backend processing revision
        ↓
old derived Reachy outputs marked stale
```

MinerU exposes result invalidation through its document-library tooling/SDK, which should be used rather than manually mutating MinerU's internal storage.

## 24. Sensitivity and authorization

MinerU must never become Reachy's authorization authority.

Before any MinerU search/read:

```text
Reachy authenticates user
        ↓
Reachy checks channel/privacy ceiling
        ↓
Reachy checks document sensitivity
        ↓
Reachy checks project scope
        ↓
only then resolve MinerU backend_ref
```

MinerU content is treated as untrusted data.

Document text, OCR output and model-derived content cannot:

```text
authorize tools
alter owner identity
lower sensitivity
change policy
trigger privileged commands
override system instructions
```

Existing Reachy prompt-injection protections continue to apply.

## 25. Cloud policy

Phase 50 is local-first.

MinerU documents are not automatically uploaded to its official service; remote parsing requires explicit remote configuration.

Reachy's deployment should therefore use:

```text
local MinerU service
local model assets
local document storage
```

unless the owner deliberately chooses otherwise.

No Phase 50 component should silently change from local to cloud execution.

## 26. Worker isolation and supply-chain requirements

MinerU runs in a dedicated worker/container boundary.

Before deployment:

```text
pin version
review licence
record image/source
record dependencies
review container size
review model licences
record model hashes where practical
restrict network exposure
define upgrade procedure
```

`companion-core` must not absorb MinerU's dependency stack.

## 27. Stage 50J — Web Documents experience

Add a top-level Documents tab.

```text
Brain
Meetings
Notes
Tasks
Documents
```

**Main library**

```text
Documents

[ Upload ]

Architecture Review.pdf
Ready
Work Private

Tender Response.docx
Background processing
Confidential
```

**Detail page**

```text
Architecture Review.pdf

46 pages
Ready

Processing:
MinerU Standard

Priority:
Normal

[ Ask Reachy ]
[ Summarize ]
[ Deep Analysis ]
[ Prioritize ]
[ Reprocess ]
[ Delete ]
```

## 28. Processing transparency

Do not merely show:

```text
Processed
```

Expose meaningful state such as:

```text
Queued
Parsing
OCR/processing
Ready
Partially ready
Failed
```

Where MinerU exposes meaningful tier/parse state, Reachy may surface it in simplified form.

The owner should be able to distinguish:

```text
document uploaded
document usable
document fully processed
document partially processed
processing failed
```

## 29. User-facing priority control

Suggested control:

```text
Processing priority

○ Background
● Normal
○ Priority
```

Conversational equivalents:

```text
"Process this later."
→ BACKGROUND

"Summarize this when it's ready."
→ NORMAL

"I need this now."
→ INTERACTIVE
```

Reachy may offer:

> This document is still being processed in the background. Prioritize it now?

Explicit owner choice overrides automatic routing.

## 30. Cross-source reasoning

Once a document is available through MinerU, Reachy may deliberately combine it with its own memories.

Example:

```text
"Compare this architecture document
with yesterday's design meeting."
```

Flow:

```text
MinerU document evidence
        +
Reachy meeting evidence
        ↓
Reachy synthesis
```

Source boundaries must remain explicit.

The final answer should preserve which claim came from:

```text
document
meeting
note
memory
task
```

## 31. Reachy document memory

Documents become reference-backed memories.

Conceptually:

```text
Reachy memory graph/index

Document node
├── title
├── sensitivity
├── project
├── metadata
└── backend_ref ──────────────► MinerU document
```

Reachy does not need to persist a second full copy of:

```text
pages
OCR
layout
blocks
MinerU parse representation
MinerU search index
```

unless a specific Reachy feature requires derived caching.

This is the central simplification introduced by the MinerU decision.

## 32. Android scope

Android is not required to own document lifecycle in the first release.

Initial Android capability may include:

```text
ask questions about existing documents
view summaries
view citations
view processing status
```

Later:

```text
upload
delete
reprocess
prioritize
document viewer
```

Web remains the initial full management surface.

## 33. Interaction with Phase 48 / Phase 49

Phase 50 must not invalidate existing acceptance work.

Planning and isolated implementation may proceed.

Document retrieval should remain gated until enabling it does not contaminate any frozen Phase 48/49 evaluation still in progress.

The existing knowledge system remains unchanged for:

```text
memories
notes
meetings
tasks
```

until document federation is explicitly enabled.

## 34. Engineering verification

Phase 50 removes comparative benchmarking, but not verification.

Required tests are implementation acceptance tests.

### 34.1 Ingestion

Verify:

```text
PDF upload
DOCX upload
TXT/Markdown upload where applicable
scanned PDF
image-heavy PDF
large document
```

### 34.2 Reference integrity

Verify:

```text
Reachy document
→ correct MinerU document

MinerU locator
→ correct page/block

source hash
→ correct original document in Reachy's source store
```

### 34.3 Retrieval

Verify representative known-answer questions return the correct source evidence.

This is a functional acceptance test, not a benchmark campaign.

### 34.4 Grounding

Verify citations reference real MinerU page/block evidence.

### 34.5 Abstention

Verify Reachy does not invent an answer when evidence cannot be found.

### 34.6 Lifecycle

Verify:

```text
upload
process
read
reprocess
delete
```

and confirm deleted documents disappear from retrieval.

### 34.7 Security

Verify document content cannot bypass:

```text
sensitivity
channel ceiling
owner authorization
tool authorization
prompt-injection protections
```

### 34.8 Scheduler

Verify:

```text
background → Proxmox
priority → MS-01
escalation preserves work
LLM service restores correctly
```

## 35. Promotion gates

**G1 — MinerU service**

Self-hosted MinerU operates reliably as an isolated service.

**G2 — Document identity**

Reachy maintains a correct stable reference to each MinerU document.

**G3 — Ingestion**

Supported documents can be ingested and processed.

**G4 — Evidence access**

Reachy can search/read the correct MinerU source evidence.

**G5 — Scoped Q&A**

Document-scoped questions remain scoped to the requested document.

**G6 — Provenance**

Answers can trace evidence to the original document/page/block.

**G7 — Lifecycle**

Delete and reprocess behave deterministically.

**G8 — Privacy/security**

MinerU cannot bypass Reachy authorization, sensitivity or trust boundaries.

**G9 — Scheduling**

Background and priority paths work without corrupting document state.

**G10 — UX**

Owner can upload, inspect, query, summarize, prioritize, reprocess and delete documents through Reachy.

## 36. Promotion outcomes

Use:

```text
PROMOTE
NARROW
DO NOT PROMOTE
```

**PROMOTE**

Core engineering contracts are satisfied.

**NARROW**

Example:

```text
normal PDFs reliable
complex visual document processing incomplete
```

Advertise only the proven subset.

**DO NOT PROMOTE**

Use if any critical issue remains in:

```text
authorization
source identity
provenance
deletion
retrieval integrity
processing isolation
```

## 37. Implementation sequence

```text
ADR-0034 alignment
      ↓
50A — MinerU service
      ↓
50B — Reachy document model
      ↓
50C — ingestion/reference creation
      ↓
50D — MinerU processing tiers
      ↓
50E — document-scoped conversation
      ↓
50F — federated retrieval
      ↓
50G — provenance/citations
      ↓
50H — summaries/analysis
      ↓
50I — heterogeneous scheduler
      ↓
50J — Documents Web UI
      ↓
engineering acceptance
      ↓
promotion decision
```

## 38. Expected deployment

```text
                         Reachy Web
                             │
                             ▼
                         Reachy Core
                             │
                    policy / authorization
                             │
                             ▼
                    Reachy DocumentStore
                             │
                       backend_ref
                             │
                             ▼
                      MinerU Service
                 ┌───────────┴───────────┐
                 │                       │
                 ▼                       ▼
        MinerU document library      parse workers
        original documents           OCR/layout/VLM
        locators/search/cache             │
                 │                       │
                 └───────────┬───────────┘
                             │
                   structured evidence
                             │
                             ▼
                         Reachy LLM
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
          Ask Reachy                  Summarize/Analyse
```

Compute routing:

```text
BACKGROUND / NORMAL
        ↓
Proxmox MinerU worker
CPU / RAM
slow-burn processing


INTERACTIVE / PRIORITY
        ↓
MS-01 accelerated worker
GPU reclaimed as required
        ↓
restore Reachy LLM service
```

## 39. Owner decisions — 2026-10-11

The following decisions are considered settled for Phase 50:

* MinerU is the selected document-processing backend.
* Phase 50 is an engineering integration phase, not a comparative OCR/document-model research phase.
* Reachy's document records hold stable references to MinerU-managed document objects rather than duplicating MinerU's entire document representation.
* Reachy remains the authority for sensitivity, project scope, authorization and privacy.
* MinerU remains responsible for document parsing, OCR, document structure, local document-library operations and page/block reading.
* Reachy's content-addressed source store is the system of record for the original file; MinerU holds a derived working copy and cache, never the authority.
* Original evidence remains authoritative.
* OCR and parsed/model output remain derived evidence.
* MinerU runs self-hosted and isolated from `companion-core`.
* Background and normal work should preferentially use the Proxmox CPU worker.
* Interactive/priority work may reclaim the MS-01 GPU under the existing measured GPU-switching requirements.
* A document job may be escalated from background to priority without discarding already completed processing.
* MinerU's own parsing cache/state should be reused rather than recreating work unnecessarily.
* Document retrieval becomes a federated Reachy knowledge source rather than requiring all document content to be copied into Reachy's pgvector store.
* The MinerU retrieval adapter enforces Phase 44 access, sensitivity and revalidation semantics before any MinerU evidence reaches a prompt.
* Upload takes an explicit sensitivity (conservative default otherwise); content may suggest a stricter class but never lowers one.
* Cloud document processing is not used unless explicitly permitted by the owner.
* Testing focuses on engineering acceptance, regression, security and correctness rather than comparing competing document-processing products.

## 40. Final architectural principle

Phase 50 should remain deliberately simple:

> Reachy owns the relationship with the user. MinerU owns the relationship with the document.

Reachy knows:

```text
who may access it
why it matters
what project it belongs to
how sensitive it is
how it relates to meetings/notes/tasks
what the user is asking
```

MinerU knows:

```text
how to parse it
how to OCR it
where its pages and blocks are
how to read it
how to search it
how to cache its processed representation
```

The connection between them is a persistent typed reference:

```text
ReachyDocument
      │
      └──── backend_ref ────► MinerU Document
```

That separation should minimize Phase 50 custom engineering while preserving Reachy's existing privacy, trust, provenance and memory architecture.
