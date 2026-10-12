# Phase 31 — Meeting intelligence completion

**Status (2026-10-12): ENABLED for the owner-supervised trial ([Step A](verification/phase-31-trial-step-a-deployment-2026-10-12.md), [Step B](verification/phase-31-trial-step-b-activation-2026-10-12.md): core `fa418f2`, `MEETING_ANALYSIS_ENABLED=true`, no analysis started). Earlier: DEPLOYED to the homelab with the feature OFF ([deployment record](verification/phase-31-deployment-2026-10-12.md): migration 032 applied, core/hub/coding-agent recreated, `MEETING_ANALYSIS_ENABLED=false`); enabling it and the owner-supervised trial each need separate authorization. Built and tested locally first (mock, disposable PostgreSQL, real 7B on a real recording). Evidence: [verification record](verification/phase-31-meeting-analysis-2026-10-12.md). The acceptance criterion (a real 30 to 60 minute meeting, owner-reviewed) is open.** Continues [Phase 27](phase-27.md) (pipeline, alignment, summaries and minutes) and reuses [Phase 49](phase-49.md) (extraction, validation, review, idempotency). Roadmap row: [plan.md](plan.md#6-implementation-roadmap).

Owner scope (2026-10-12): engineering first; current 7B model and existing speech services only; no new frameworks, models or comparative benchmarks; no concurrent STT/diarization or performance work until measurements show a need; local changes, disposable databases, stop before production migration or deployment; no change to frozen Phase 48 components.

## 1. Baseline inspection (read-only, 2026-10-12)

The only meeting in the production database is the owner's 758 s phone recording (`complete`, no `started_at`, no speaker names, 2 accepted corrections, summary and minutes by the local tier). Counts only; no transcript text was read into this record.

| Measure | Value | Reading |
|---|---|---|
| Transcript segments / aligned / diarization turns | 78 / 78 / 46 | alignment is index-aligned and complete |
| Recording check | 511 s of exact silence in 3 spans, flagging segments 38, 46, 69 | two thirds of the audio was never captured (old app build); speech is about 247 s, 3,868 characters |
| Aligned speakers | 6 labels: 18, 2, 28, 18, 4, 8 segments | far more labels than a short conversation plausibly has: diarization over-segments; `speaker_1` holds 2 segments spanning 143 s (across a silent gap) |
| Speaker labels | lower-case `speaker_N` | `display_name` only prettifies `SPEAKER_NN`, so the UI and prompts show `speaker_0`. Fixed in this phase (small, safe) |
| Segments with no speaker | 0 | no unattributed text |

Consequences for design. (1) This recording is too short and too gappy to be the acceptance meeting; the 1,419 s `test/StarHub Green.m4a` (4 speakers, 349 segments, run through the live sidecars on 2026-10-05, content never judged) is the available real input for development checks, and the 30–60 minute acceptance still needs an owner recording. (2) Speaker labels are unreliable, so analysis never decides who someone is: an action's owner is the name stated in the quote, or nothing, and the speaker is shown only as the transcript's own label. (3) Gap-flagged segments must not become evidence silently; they are marked.

## 2. Minimal architecture

Meeting analysis is a **sibling of Phase 49's note processing**, not an extension of its tables. Phase 49's jobs, proposals and fingerprints are keyed by `note_id` and a note snapshot hash (deployed schema `029`); changing them would alter a deployed, owner-accepted feature. What is shared is code, not tables.

```
owner "Analyse" ─▶ POST /meeting-analysis/{meeting_id}        (hub proxy: owner cookie+CSRF or bearer)
                    └ snapshot: numbered segments (index, start, end, speaker label, current text) + hash
                       durable run (one active per meeting; identical hash+prompt = existing result)
background runner (reused run_loop) ─▶ chunk by segment (outputs.chunk sizing) ─▶ local 7B, JSON only, no tools
                    └ deterministic validator (extends Phase 49 rules) ─▶ items: decision | open_question | action
owner review (actions): Confirm | Edit & confirm | Dismiss ─▶ confirmed action ─▶ existing task store
                    └ task id derived from the item id (idempotent), existing receipt, provenance = item row
retrieval: MeetingAdapter also yields an action the owner CONFIRMED ─▶ Phase 44 index/outbox ─▶ cited retrieval (nothing unreviewed)
```

**Revision after the first real run (see the [record](verification/phase-31-meeting-analysis-2026-10-12.md#defect-found-by-the-real-recording-and-the-fix)).** Speech-to-text segments are short fragments and a sentence usually spans several, so evidence is not one segment: the validator locates the quote across consecutive segments of the chunk (the model's number is only a hint) and records every covered segment id, the first start, the last end and the first speaker label; an item's identity across re-analysis is its kind and first segment with an overlap rule, not the model's quote.

**Segment identity.** The segment id is the index into the meeting's raw `transcript_segments` (never rewritten, already the Phase 44 locator `meeting#<index>`). The model sees `[#12 3:05] Name: text` and returns `{"segment": 12, "quote": "..."}` per evidence. The validator takes timestamps, speaker label and text **only from the snapshot** for that index; a quote that is not (modulo case and whitespace) inside that segment, or an index that does not exist, drops the evidence, and an item with no valid evidence does not exist. This is stricter than Phase 49, which located a quote anywhere in a text blob.

**Item kinds.** `decision`, `open_question` (generated findings: viewable, dismissible, searchable with evidence; they create nothing) and `action` (a candidate; nothing exists until the owner confirms). Fields: text, up to three evidence refs, optional `assignee` (must appear in the evidence quote, else dropped with an ambiguity note), optional `stated_time` (must appear in the evidence; resolved against the meeting's `started_at` only when that is known, otherwise kept as words), ambiguity notes, sensitivity (the meeting's, raised by the existing classifier), model, prompt version.

**Idempotency and provenance.** Items are unique per (meeting, kind + normalised quote) and `same_finding` (same kind, overlapping segments, shared quote words) stops a re-wording or a different quote extent from bringing back a dismissed or accepted item; undecided items are refreshed from the newer run. Confirming claims the item (`pending → accepting`, compare-and-set, stale takeover), creates the task under a UUID derived from the item id, writes the existing `task.created` receipt under a derived id, then closes the item; every step may run twice. Provenance lives on the item row (`record_kind`, `record_id`, meeting id, segment refs, transcript hash); `GET` by record id answers "where did this task come from". No new provenance table.

**Staleness.** An item is returned with `source_changed` when its own quote is no longer in its own segments as the transcript reads now (a correction touched them).

**Support labels.** Every item has `support`: `stated` or `uncertain`. The quote is always verified to be in the transcript; `stated` additionally needs wording of the right kind with no hedge (an explicit agreement, a promise or request, a real unanswered question, with or without a question mark; answers are looked for in the quote and the next two lines), and the item's own words mostly present in the quote. Speaker labels are removed from the wording. This is a check, not proof: the screen says everything is unverified and model-written, shows `stated` items first and collapses `uncertain` ones under "Weaker suggestions", all still readable, confirmable and dismissable. Rules and evidence: [extraction-quality record](verification/phase-31-extraction-quality-2026-10-12.md), earlier [review](verification/phase-31-meeting-analysis-2026-10-12.md#engineering-review-second-pass-same-day) and [model diagnostic](verification/phase-31-model-diagnostic-2026-10-12.md).

**Retrieval.** `knowledge/sources.py::MeetingAdapter` already indexes every segment (locator = segment index, speaker, start), the summary and the minutes, and Phase 44 already handles authorization, sensitivity ceilings, local-only destination, revalidation and citation rendering. **Trial scope (2026-10-12): only an action the owner has explicitly confirmed is added**, as a `meeting_minutes`-kind entry with locator `analysis:<item id>`, `authority="model_generated"` and text that carries the `[m:ss]` evidence stamps. Decisions, open questions and pending actions are unreviewed (a decision or question has no confirmation step, only dismissal) and are never offered to retrieval, the Brain or any reply; indexing them would need a separate decision and an explicit "keep" step. (The first build indexed non-dismissed decisions and questions too; that was narrowed before the feature was enabled.) No new item kind, no change to `semantic/model.py`, `routing.py` or any frozen Phase 48 file. A database trigger on the items table enqueues the meeting into the existing outbox so changes reindex.

## 3. What Phase 49 provides, and what is new

| Need | Reuse from Phase 49 (import, same service) | Mandatory new work |
|---|---|---|
| Local-only model call with a fixed failure code | `Provider`, `Ask`, `ExtractionFailed`, the `run_loop` runner (duck-typed: `process_next`, `reconcile`, `wake`) | none |
| Tolerant JSON parse, bounded output | `parse_output` approach, `Rejections` | new output schema (segment-addressed evidence) |
| Evidence location | `locate` (exact then whitespace/case-insensitive) | per-segment check against the snapshot |
| Injection defence | `_INSTRUCTION` regex; transcript delimiters; "data, not instructions" prompt | new prompt |
| Time handling | `resolve_time` (never invents a date) | anchor = `Meeting.started_at`, none if absent |
| Ownership discipline | `_FIRST_PERSON`, "the owner is not identified in a transcript" | assignee must be in the quote |
| Idempotent accept | `record_id_for`, task creation by derived id, receipt id derivation, pending/accepting/accepted/dismissed machine | `MeetingAnalysisStore` (in-memory twin + PostgreSQL), service, routes |
| Fingerprint / hashing | `fingerprint`, `normalise`, `content_hash` | kind-aware fingerprint |
| Hub proxy pattern, route constants | `reachy_hub/notepad_processing.py`, `shared/protocols` | `meeting_analysis` proxy and constants |
| Schema discipline | 029's shape: no foreign keys into authoritative tables, own rollback, re-appliable | migration `032_meeting_analysis`, `rollback-032.sql` |
| Retrieval | Phase 44 adapter, outbox, revalidation, citation | analysis entries in `MeetingAdapter`, one outbox trigger |
| UI | Phase 49 review component pattern | a meeting-detail panel (web) |

Not reused, and why: `notepad_jobs`/`notepad_proposals` tables (keyed by note; deployed schema); the temporal note↔meeting links (a different relation); the 44F candidate tables (frozen during Phase 48).

## 4. Flag and rollout

`MEETING_ANALYSIS_ENABLED` (default off, passed through by Compose from `.env`). With it off the tables are never read and the routes do not exist (404). Explicit owner request only; no automatic analysis on completion in this phase. Deployment needs the owner's approval (backup, migration `032`, core + hub + coding-agent together because `SCHEMA_REVISION` moves, and a Phase 48 cohort boundary because core is recreated).

## 5. Verification plan

Unit and in-process tests for the validator (fabricated segment, wrong quote, injected instruction, assignee not in quote, relative time without a start, gap-flagged segment), the store state machine (including crash takeover, double accept, dismissed stays dismissed after re-analysis), the service with a fake model, routes, the hub proxy chain, and the adapter. A migration, rollback and retrieval round trip on a disposable pgvector container. Then a development run of the real 7B over the real 1,419 s recording, reported with counts and the owner's judgement left open. Final acceptance (not claimable from this phase's local work): a real 30–60 minute meeting, owner-reviewed, with the metrics Phase 27 lists.

## 6. Owner-supervised real-meeting trial (next milestone; preparation in the [trial preparation record](verification/phase-31-trial-preparation-2026-10-12.md), activation needs separate approval)

**Frozen for the whole trial:** prompt `meeting-analysis-2`, `meeting_analysis/support.py`, the extraction schema and the 7B model. No tuning, no model swaps, no extra Deep Local runs. Any defect found goes into the report and waits for a decision.

**Known limitations to state in the report, not to hide:**

- `stated` means only that the quote is in the transcript and has wording of the right kind (explicit agreement, a promise or request, a real unanswered question) and covers the finding's own words. It is **not independently verified**: it is a deterministic check by the same pipeline, and on the 24-minute development recording one `stated` action was still mis-worded. Everything is model-written from a speech-to-text transcript.
- **Question-recall regression:** the stricter question rules (prompt v2 plus the validator) cost the 7B its one genuine open question on the development recording (1 listed before, 0 after); only the 14B found it. Open questions the 7B does not list are expected to be missed.
- The 7B often cites a neighbouring sentence for a conclusion (9 of 17 findings unsupported on the development recording). Recall of commitments is partial (6 of 10 reference commitments had a supported finding, 2 strictly).
- Evidence so far: one 24-minute recording, one reader.

**Acceptance report (owner-supervised, a real 30 to 60 minute multi-speaker meeting)** records, from the owner's own reading of the transcript and the Analysis tab:

1. Meeting facts: duration, speakers, analysis time, STT/diarization times if the recording is new.
2. **Missed commitments:** promises or requests in the meeting with no finding, listed with their timestamps; and the same count restricted to the default (`stated`) view.
3. **Missed open questions:** real questions left open with no finding.
4. **Unsupported findings:** findings whose quote does not support them, split by `stated` and `uncertain`, and by kind; also wrong-kind items and duplicates.
5. **Source navigation:** whether "Play from" and the quoted line led to the right moment, whether the segment ids, timestamps and speaker labels matched the recording, and how fast the owner could check a finding.
6. **Practical usefulness:** what the owner would have done without it, what they confirmed as tasks, what they dismissed, time spent reviewing, and whether retrieval later answered a question about the meeting with a correct, cited answer.
7. A recommendation (keep on, keep off, or what must change first), signed off by the owner.

The trial does not enable anything beyond `MEETING_ANALYSIS_ENABLED`; no finding is promoted automatically and no task exists without the owner's confirmation.
