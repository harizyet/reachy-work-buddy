# Phase 53 — Multimodal meeting intelligence

**Status (2026-10-14, after a browser UAT rehearsal on a disposable stack: [record](verification/phase-53-uat-rehearsal-2026-10-14.md)): DEPLOYED to the homelab 2026-10-14 and ENABLED the same day (`MEETING_MULTIMODAL_ENABLED=true`, core recreated; [deployment record](verification/phase-53-deployment-2026-10-14.md): migration 034 applied; core, hub, coding-agent and document-worker recreated); branch `feature/meeting-multimodal` merged to `main` 2026-10-14 (`94e7842`). The owner's acceptance is open.** Core, hub and web are implemented and tested (mock, disposable PostgreSQL, one real-infrastructure trial). Android is not changed. Production needs the owner's approval (migration `034`). Evidence: [verification record](verification/phase-53-multimodal-meetings-2026-10-14.md). Decision record: [ADR 0037](adr/0037-multimodal-meeting-evidence-and-slide-alignment.md). Roadmap row: [plan.md](plan.md#6-implementation-roadmap).

Extends [Phase 27](phase-27.md) (recording, transcript, timestamps), [Phase 31](phase-31.md) (analysis, evidence validation, owner-reviewed actions; unchanged), [Phase 49](phase-49.md) (patterns) and [Phase 50](phase-50.md) (documents, pages, MinerU) under [ADR 0034](adr/0034-source-evidence-and-derived-artifacts.md). Phase 50F federation, Phase 48 selective answering and Phase 44 indexing are not touched or enabled.

## 1. What the owner can do

1. Open a finished meeting, choose **Documents**, attach an existing library document or upload one (PowerPoint, PDF, …) and see its processing status.
2. **Estimate the pages**: Reachy estimates which page was being discussed in each part of the transcript.
3. Read the **Transcript**: beside a part of it, a compact card says "Likely slide 7 — Edge Architecture · Certainty: High" with Details (reason, shared words, alternatives, a thumbnail, "Open the page"). Where nothing fits it says "No confident slide association".
4. **Confirm**, **choose another page**, **mark "not about a slide"**, **remove a suggestion**, or withdraw a decision. Decisions are kept apart from the estimates and survive reruns.
5. **Ask** a question that needs both sources and get labelled parts with separate citations (a page link, a transcript timestamp).
6. **Analyse with documents** for discussion points, decisions, disagreements between a page and what was said, open questions and action candidates. An action becomes a task only when the owner confirms it.
7. Detach a document (the document stays), delete a document or the meeting (derived data goes).

Everything is behind `MEETING_MULTIMODAL_ENABLED` (default off; also needs `DOCUMENT_LIBRARY_ENABLED`). With either off the routes do not exist.

## 2. Implementation-gap assessment

Done before coding, from the code, not the documents (2026-10-14; `main` at `85f24f4`, clean tree, deployed schema `033_calendar_feed`, `MEETING_ANALYSIS_ENABLED` and the library on in the homelab).

| Need | State | Used / gap |
|---|---|---|
| Transcript, speaker labels, timestamps, corrections | `Meeting.transcript_segments` (raw, immutable), `transcript_corrections` overlay, `meeting_analysis.service.snapshot` | reused as is; segment index is the locator |
| Analysis, evidence validation, owner-confirmed actions | Phase 31 `meeting_analysis` (frozen prompt, validator, 7B trial) | its span locator, support checks, instruction filter and confirmation primitives are **imported, not edited**; combined analysis is a separate run, table and prompt |
| Document ingestion, pages, locators | `DocumentService` (`read(page_range)`, `search`, `evidence_for_question`, `authorize`, `require_usable`), page = one PDF page, worker locators `doc:<ref>/tier:<t>/page:<n>` | reused; Phase 53 names pages `doc:<document id>/page:<n>` (Reachy's id, not the backend's) |
| **PPTX and other formats** | At first assessment (from the allowlist) **not accepted**: only pdf, png, jpg, docx. MinerU in the worker image was then probed and shown to parse many more types; the allowlist was widened to the measured set (see [document types](verification/phase-53-document-types-2026-10-14.md)) | **PPTX, PPT and ODP keep one page per slide with headings**; XLSX/XLS/ODS one page per sheet; DOCX/DOC/RTF/ODT/EPUB/HTML/CSV/TSV one page; no page pictures except PDF/images. No custom parser. Plain text and Markdown are not parsed by MinerU and stay refused; PPSX/PPTM/Keynote are refused with "export it as a PDF or PPTX" |
| Slide/page locators | reliable for PDF: one page = one slide, 1-based, `page_count` on the document; headings come out as `# Title` | page titles are the first heading line when short |
| Revision tracking | no revision counter; `source_hash`, `backend_revision`, `tier`, `page_count`, `backend_ref` change on reprocess | `revision_of(document)` = hash of those five |
| Sensitivity / project / authorization | `Document.authorize(access)`, hub-set `X-Reachy-Access-Ceiling`, `within_ceiling`, `scope_permits` | reused on every read; derived output is the stricter class |
| Meeting detail UI | web `MeetingDetail` (tabs, transcript list), Android Meetings | web extended; **Android not changed** |
| Local inference | `notepad_local_provider` (local-only, temperature 0); vLLM `reachy-local` (Qwen2.5-7B-AWQ, 8k window) | reused; no new model, tier or service |
| Visual descriptions | none exist in the pipeline (text, tables and captions only) | the model sees page text; no VLM |
| Knowledge retrieval / revalidation | Phase 44/48 indexing flags (production: on) | **not used**: nothing from Phase 53 is indexed, and no flag is changed |

## 3. Architecture

```
owner (web) ─ hub proxy (owner cookie + CSRF, sets the ceiling) ─▶ core /meetings/{id}/multimodal/...
core: MeetingMultimodalService
  links        meeting_document_links          (ids only; unique per meeting+document)
  runs         meeting_multimodal_runs         (alignment | analysis; hashes of what they read, never text; one active per kind)
  estimates    meeting_slide_alignments        (current estimate per window; replaced as a set by the next run)
  decisions    meeting_slide_reviews           (the owner's; never touched by a run)
  findings     meeting_multimodal_items        (verified quotes; actions pending until confirmed)
reads  meeting store (snapshot) ── document library service (pages) ── local model (choose / list / phrase)
```

Module `companion_core/meeting_multimodal/`: `models`, `alignment` (windows, scoring, certainty), `analysis` (combined findings), `ask` (question answering helpers), `service`, `store` (in-memory twin), `postgres_store`, `routes`. Shared route constants: `shared/protocols/meeting_multimodal_api.py`. Hub: `reachy_hub/meeting_multimodal.py`. Web: `api/meetingMultimodal.ts`, `features/meetings/{DocumentsPanel,SlideSuggestion,useMeetingMultimodal}`. Migration `034_meeting_multimodal` (no foreign keys, no triggers, own tables) and `deploy/homelab/rollback-034.sql`.

Routes (core and hub, same paths; all behind the service token / owner session; the hub adds `X-Reachy-Access-Ceiling: sensitive`): `GET /meeting-multimodal/config`; `GET /meetings/{id}/multimodal`; `POST|DELETE …/attachments[/{id}]`; `POST …/alignment`; `POST …/analysis`; `PUT|DELETE …/windows/{first-last}/review`; `POST …/ask`; `POST /meeting-multimodal/runs/{id}/retry`; `POST /meeting-multimodal/items/{id}/accept|dismiss`. Linking is idempotent; runs are idempotent by input hash; accept is idempotent by derived task id.

## 4. Slide alignment

### 4.1 Method (all of it is code in `alignment.py`)

1. **Windows**: consecutive non-silent segments grouped by size (250–900 characters, 150 s), pauses of 3 s or more once there are enough words, and any pause over 9 s. Speaker changes and text corrections never move a boundary, so a window's key (`first-last` segment index) is stable.
2. **Rank pages** of every linked document by shared content words, weighted by inverse document frequency over all attached pages (title words ×1.5). The page chosen for the previous window gets +20 % and the next page +5 % of the best score: a weak prior only.
3. **Explicit references** ("slide 7", "page seven", "slides 3 and 4") are resolved: they count only when exactly one attached document has such a page, or the discussion names the deck (the longest matching title wins). Otherwise they are reported ("could be page 3 of more than one attached document") and not used.
4. **Ask the local model** only when a candidate has lexical support (two shared words, one distinctive) or a reference resolved. At most four candidates, labelled C1–C4 (never page numbers), plus the text just before and after. It returns a choice or 0 ("none"), alternatives, one short reason and optionally a contradiction with two quotes. Quotes must be found verbatim in the page and in the window; a comment that reads as an instruction is dropped.
5. **Certainty** is assigned by the rules below.

### 4.2 Evidence kinds kept distinct

`method`: explicit reference, semantic, none. `relation`: supports, **contradicts** (two verified quotes the model says conflict, shown as the model's reading), **unresolved** (a page was named but could not be tied to one document). The owner's decision is a separate row with its own authority ("Confirmed by you"). Nothing says a slide was displayed.

### 4.3 Certainty rules

Signals: *E* an explicit reference resolved to the page; *L* lexical support (≥2 shared words, ≥1 distinctive); *M* the model chose the page; *dist* distinctive shared words; *lead* page score ÷ runner-up score; *rival* another page scoring ≥70 % of it; *leader* the page has the highest score.

| Label | Rule |
|---|---|
| **High** | E and (L or M); **or** no E, M, leader, L, dist ≥ 4, no rival, lead ≥ 2 |
| **Medium** | E but neither L nor M; **or** no E, M, leader, L, dist ≥ 2, lead ≥ 1.25 |
| **Low** | any other chosen page (weak, ambiguous, several plausible, or the model chose a page that is not the leader) |
| **Unknown** | nothing chosen: no candidate had lexical support and nothing resolved, or the model declined and nothing was named |

The model cannot raise a label. **Only an owner decision or a current High or Medium estimate is relied on** (as analysis context, as a link in an answer, as "this page was discussed"); a Low estimate is shown as one muted line and is used only after the owner confirms it, and "unknown" is a valid result that is never replaced by a guess. A window whose model answer was unusable is stored as *unchecked* ("not checked", not "nothing fits") and a run with unreadable parts reports a partial result. Alternatives (up to three) are kept for Medium and Low. The reason shown is built from the signals (resolved reference, shared words, "continues the previous page", "other pages also share words"); the model's own comment is stored and shown separately, labelled as the model's. No number is shown or implied to be a probability. Each row above is a unit test (`test_certainty_rules`).

### 4.4 Revisions and staleness

An estimate stores the revision of the window's current text (hash of its segments' corrected text) and of the document (`revision_of`). On every read: window text changed → *source changed*; document revision changed → *document changed*; either → *stale* ("Out of date", rerun). An owner decision stores both revisions too; if either no longer matches it becomes **needs confirmation again**, is still shown, and is ignored by answers and analysis until the owner confirms it.

## 5. Questions across both sources

Retrieval starts at the one meeting and its attached, readable, processed documents: transcript windows best overlapping the question; pages from the existing `evidence_for_question`; pages the question names ("slide 7"); the transcript stretches whose current, trusted estimate points to a retrieved page and the pages estimated for retrieved stretches (an owner decision beats an estimate; stale ones are never used). At most five windows and six pages are sent. With nothing retrieved the reply is fixed and the model is not called. "Which slides were not discussed?" is answered from the estimates alone, with the caveat that it does not prove they were not shown.

The model returns parts of five kinds, and the code checks each against its citations: `document` needs a cited page; `speaker` needs a cited transcript excerpt; `decision` needs a cited excerpt that reads as an agreement with no hedge, otherwise it is **downgraded to inference** (a slide proposal is not a decision); `inference` needs a citation and is labelled as Reachy's inference; `unknown` is for what is not settled or in conflict. Cited labels not supplied are dropped; instruction-like text is dropped. The response carries the citations (page: document id, title, page, locator, source hash, tier; transcript: segments, timestamp, speaker), the association between a cited excerpt and a cited page with its authority ("owner-confirmed" or "Reachy's estimate, not proof of what was shown"), any verified disagreement found during alignment, caveats, the stricter sensitivity and the latency.

## 6. Combined analysis

A separate durable run (own table, prompt `multimodal-analysis-1`, own validator). It reads the transcript windows with the page estimated for each (marked as an estimate). Kinds: discussion point, decision, disagreement, open question, action. A decision, question or action needs a verified transcript quote; a disagreement needs a verified quote from each side; a quote of either kind is located in the source and carries its timestamp, speaker, page, source hash and document revision. Phase 31's support check (`stated`/`uncertain`) is applied to the spoken quote. Instruction-like text, speaker labels, unsupported assignees and invented times are rejected or removed. Unaddressed pages are computed from the estimates, not by the model. Re-analysis never resurrects a dismissed finding or duplicates an accepted one. **Confirming an action** uses the same primitives as Phase 31 (claim, derived task id, the existing `task.created` receipt, close) on this phase's own item table; there is no parallel task system, and nothing is indexed, promoted to memory or sent anywhere.

## 7. Lifecycle and security

| Event | Result |
|---|---|
| Attach twice | one row |
| Detach | that meeting's estimates, decisions and findings for the document go; the document and other attachments stay |
| Document deleted (listener fires on the first step, before the worker confirms) | all its links, estimates, decisions and findings go in every meeting; a confirmed action's task stays and its page quote is stripped; reads treat a deleting document as gone at once |
| Meeting deleted | all its multimodal rows go; documents stay |
| Transcript corrected / document reprocessed | derived rows flagged out of date on read; owner decisions need confirming again; sources untouched |
| Run interrupted | lease expiry lets another worker take it over; completion is one transaction; retry is idempotent |
| Source changes between request and run | run fails with `source_changed`; nothing is written |
| Caller cannot read the meeting or a document | one `404 No such meeting/document`; documents they cannot read are absent from lists, counts and answers; a run made with a higher ceiling is not shown |
| Project differs | linking refused; one unscoped side is allowed (interim single-owner policy) |
| Prompt injection in slides or transcript | text is data; candidates are labelled C1–Cn; labels come from rules; instruction-like quotes, comments and answer parts are rejected; no tool exists to be called |

## 8. Performance and resource policy

No new model, tier, service or index. One run at a time (concurrency 1) on the shared local 7B, like Phase 31. Alignment makes at most one model call per window that has something to choose from (about 1.2k prompt tokens each); analysis makes one call per ≈5 000 characters; a question makes one call. Measured figures from one trial are in the [verification record](verification/phase-53-multimodal-meetings-2026-10-14.md#real-infrastructure-trial).

## 9. Known limits

- Vocabulary overlap, not understanding: speech-to-text misspellings of a name defeat it (the trial's best example), figures-only slides give nothing to match, and talk about a slide in other words stays Unknown or Low.
- Medium and High mean the evidence is strong, not that the slide was shown or that the estimate is right; the first real-meeting reading is one trial.
- A decision check is by wording of the cited excerpt (a window of up to 900 characters), not proof that the participants agreed.
- Only PDF and images have page pictures: a PowerPoint attachment gives titles and text per slide but no thumbnail, and non-presentation types read as one page (a Word file or an HTML page cannot be aligned finer than the whole file). Pages beyond 150 per document are refused for alignment.
- Android shows none of this yet.
- The 7B sometimes writes generic answers and once returned an unusable analysis chunk (counted, others kept).

## 10. Deployment and rollback plan (nothing below is authorised)

**Executed 2026-10-14 through step 5, flag left off; see the [deployment record](verification/phase-53-deployment-2026-10-14.md). Step 6 (enable) is not authorised.** The wider file types also change the **document-worker** (its allowlist and content checks live in its image), so the worker image must be rebuilt and the worker recreated together with core, hub and coding-agent; rollback is the `pre-034` image set including the old worker. Same shape as [Phase 31's deployment](verification/phase-31-deployment-2026-10-12.md).

1. Merge the branch (owner decision); record the commit.
2. Backup: `pg_dump` of the homelab database and a copy of `deploy/homelab/.env`; keep the `document-source` volume in the backup set.
3. Build core, hub and coding-agent images together (`SCHEMA_REVISION` moves to `034_meeting_multimodal`); tag the current images `reachy-rollback/*:pre-034`.
4. Stop the application services, apply migration `034` with the migration job, recreate core, hub and coding-agent. `MEETING_MULTIMODAL_ENABLED` stays **false** (the default). Expect about 5 minutes of downtime and a new Phase 48 segment boundary because core is recreated.
5. Check the schema revision, the empty new tables, that existing meeting, document and analysis endpoints answer, and `GET /meeting-multimodal/config` → `{"enabled": false}`.
6. Enabling is a separate approval: set `MEETING_MULTIMODAL_ENABLED=true` in `.env` and recreate core only. Roll the flag back the same way.

**Rollback:** set the flag false and recreate core (no data change); or, with services stopped, run `deploy/homelab/rollback-034.sql` in one transaction (drops only this phase's five tables; the revision returns to `033_calendar_feed`; no meeting, document, transcript or task is lost; tasks confirmed from findings stay; owner slide corrections and findings are lost), then start the `pre-034` images. Checklist item: confirm the final line prints `033_calendar_feed`.

## 11. Not done

Android screens; page pictures for non-PDF types (the parser does not render them; a LibreOffice conversion would be a new component); thumbnails beyond the existing page image route; any retrieval-index or Brain use of estimates; calibration of the labels; a held-out accuracy measurement; the owner's real-meeting acceptance (below).

**Acceptance owed by the owner:** attach a presentation exported from their own deck to a real recorded meeting, read the estimates, correct some, ask questions with answers that need both sources, review the combined findings, and delete a document to see its derived data go; plus a browser check of the new screens.
