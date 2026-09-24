# Phase 26 — meeting transcription and minutes

Status: planned, not implemented. Depends on Phase 23 shipping versioned
database migrations first (this phase adds new tables and cannot rely on
`CREATE TABLE IF NOT EXISTS` alone — see AGENTS.md's schema-change note).
Builds on the existing local faster-whisper STT (`reachy_hub/stt.py`, Phase
8), the pluggable `ChatProvider`/role-routing LLM stack (Phases 19/21), the
tasks store (Phase 11), and memory provenance/sensitivity (Phase 12). Does
not depend on Phase 22b or Phase 25.

[Phase 27](phase-27.md) extends this pipeline with Reachy as an embodied
meeting secretary — owner-present companion capture, then physical secretary
attendance, then bounded delegation; scheduled capture and bounded
participation belong to that phase.

## Required behaviour

The owner can turn a recording of a meeting or conversation into structured
minutes: a **summary**, **key points**, and a list of **action items**
(candidate follow-up tasks), always available as text in the operator UI
and never read aloud through Reachy's speaker by default (see Privacy below).
Two intake paths:

- **Upload** an existing audio recording (e.g. a meeting recorded on a
  phone or a conferencing tool's own recorder) through the operator UI.
- **Record live** through the existing Call Reachy WebRTC path (Phase 15),
  explicitly started and stopped by the owner — never ambient/always-on
  capture. This reuses the call's audio pipeline; it does not add a new
  microphone path.

Processing is asynchronous: transcription and summarization of a
real meeting (tens of minutes to a few hours of audio) will routinely
exceed every existing synchronous request budget in this codebase (Phase 21's
60s provider deadline, 130s hub timeout, 135s browser timeout — all sized
for one conversational turn, not a whole recording). The UI submits a job
and polls status; it does not hold a request open.

## Non-goals

- **No ambient/always-on transcription.** Every recording is owner-started
  and owner-stopped. This phase does not add a continuously listening
  meeting-detection mode; that would be a distinct, much larger privacy
  decision out of scope here.
- **No speaker diarization/identification in v1.** Minutes are produced
  from the plain transcript text; "who said what" is not extracted or
  attributed to individuals. Flag this honestly in the UI (same
  honesty-about-scope discipline as the existing placeholder classifiers)
  rather than guessing speaker labels from silence gaps.
- **No automatic task creation.** Action items are previewed, not written
  to the tasks store, until the owner explicitly confirms — see Action
  items below. This is not ADR 0011's destructive-action gate (creating a
  task isn't destructive) but the same reasoning applies to avoid silently
  polluting the task list with hallucinated or duplicate items.
- **No recording-consent enforcement in software.** Recording a
  conversation with other participants may have legal consent requirements
  that vary by jurisdiction. This phase adds an explicit UI attestation
  step before starting/uploading a recording (see Privacy below) but does
  not and cannot verify real-world consent; document this limitation
  plainly rather than implying the software provides legal compliance.

## Architecture and service boundaries

Preserve ADR 0001: services talk over HTTP only.

The overall `MeetingJob` (upload/record → transcribing → summarizing →
complete/failed) is a work artifact, not a media/transport concern — it
belongs with **companion-core**, matching the existing split of
`companion-core` (reasoning/tools/memory/work artifacts) from `reachy-hub`
(channels/sessions/media transport). Splitting the lifecycle across both
services because STT happens to live in the hub would make the hub a
co-orchestrator of work it doesn't own, and that lifecycle will keep
growing (cancellation, retries, progress, retention, task creation,
re-summarization) — all core/workflow concerns, not transport ones.

- **reachy-hub** owns only intake and transcription: the upload endpoint,
  the live-recording hookup to the existing Call Reachy WebRTC session, and
  an internal transcription-task endpoint pair — `POST` submits audio and
  returns a task id immediately, `GET` polls that task for the transcript
  once ready (STT stays a hub concern per Phase 8's rationale in `stt.py`,
  but hub tracks only the transcription task, not the meeting job).
  Faster-whisper transcription runs in hub's own background worker, not
  inline in either request handler — long-form audio can exceed every
  request timeout budget in this codebase, so neither the submit nor the
  poll call may block on it.
- **companion-core** owns the `MeetingJob`: creates it on
  upload/record-start, drives it by submitting to and polling hub's
  transcription task until a transcript comes back, then performs chunked
  summarization via the existing
  `llm/client.py`/role-routing stack, structured extraction of
  summary/key points/action items, persistence of the new meeting stores,
  action-item-to-task integration (reusing the Phase 11 tasks store and
  `task_intent.py`), and sensitivity classification/delivery routing for
  the result (reusing Phase 12's provenance/sensitivity model and the ADR
  0006 response router). Core never touches raw audio directly; it only
  submits it to hub's transcription task endpoint and polls for text back.
- **clients/operator-ui** adds a Meetings view: upload/start-recording,
  job status (polling core), minutes display, and action-item
  review/confirm.

### Background job processing (new)

Nothing in this codebase currently runs work outside a request/response
cycle. Keep this addition minimal, consistent with "no premature
abstraction": a `meeting_jobs` table (Postgres, no new broker/Redis) owned
by **companion-core**, with a status column
(`uploaded → transcribing → summarizing → complete → failed`), polled by a
single in-process worker loop per core instance — the same shape as the
existing presence-loop/heartbeat background tasks (Phase 3/22), just hosted
in core instead of hub since the job itself is core's. The `transcribing`
stage is core's worker submitting to hub's transcription task endpoint,
then polling it each loop tick until the transcript is ready (the actual
transcription work runs in hub's own background worker — see above);
`summarizing` is core's own chunked-summarization pipeline. The
operator UI polls `GET /meetings/{id}` on core for status, mirroring the
existing Telegram-poll-health display pattern (Phase 20) rather than
inventing a new one. A crashed/restarted core must resume or cleanly fail
in-flight jobs, not leave them stuck `transcribing` or `summarizing`
forever — test this explicitly (see Exit criteria). A crashed/restarted hub
mid-transcription must surface as a clean failure back to core's job, not a
hung call.

### Chunked summarization

A full meeting transcript will routinely exceed a single provider call's
context/output budget. Use a bounded map-reduce: split the transcript into
overlapping windows, summarize each with the configured `ChatProvider`, then
reduce the partial summaries into one structured result (summary, key
points, action items) with a final call. Request structured JSON output;
validate it, retry once on a malformed response, and on repeated failure
fall back to returning the plain-text reduced summary with an explicit
"structured extraction failed" flag — never silently drop action items
because JSON parsing failed. This reuses the existing role-routing engine
(`llm/router.py`) for each call; it does not add a second LLM dispatch path.

### Action items → tasks

Extracted action items are held as unconfirmed `MeetingActionItem` records
attached to the `MeetingMinutes` result — the "Prepare" tier from
`docs/plan.md`'s permission table (generate preview, no external change
yet). The owner reviews the list in the operator UI and confirms
individually or in bulk; only confirmed items are written to the Phase 11
tasks store, tagged with their originating meeting for provenance. Editing
an item's text before confirming is allowed; nothing is created from an
item the owner didn't see.

## Data model

New shared model `shared/models/meeting.py`:

- `MeetingRecording` — id, owner/session, source (`upload`/`call_reachy`),
  status, created/updated timestamps, raw-audio retention policy, error
  detail (sanitized — no provider internals, matching the existing
  usage-log convention of never persisting raw provider errors).
- `MeetingTranscript` — recording id, full transcript text, produced-by
  (hub STT), created timestamp. A dedicated artifact, not chunks written
  into general `MemoryRecord`s: a full meeting transcript is long,
  low-signal for retrieval, and would gradually pollute ordinary memory
  search if treated as regular memory. Governed by Phase 12's
  provenance/sensitivity/expiry model as its own record type.
- `MeetingMinutes` — recording id, transcript id, summary, key points
  (list), sensitivity classification, structured-extraction-failed flag.
- `MeetingActionItem` — minutes id, text, confirmed (bool), task id
  (optional, set once confirmed and written to the Phase 11 tasks store).
  Kept as its own record rather than an inline list so individual
  confirm/edit/reject actions have a stable id to act on.

If a meeting is worth recalling later in general conversation, memory
stores only a concise derived fact or a reference to the
`MeetingMinutes`/`MeetingTranscript` id — never the raw transcript text.

New tables via a Phase 23 migration (not `CREATE TABLE IF NOT EXISTS`),
owned by companion-core: `meeting_jobs`, `meeting_transcripts`,
`meeting_minutes`, `meeting_action_items`. No changes to existing tables.

## Privacy and retention

Meeting content is categorically more sensitive than a single chat turn —
a full recorded conversation, often involving other people who never typed
anything into this system. Apply stricter defaults than ordinary chat:

- Minutes are always delivered as text (Telegram/web chat/operator UI),
  never spoken through Reachy's speaker, in any mode including Desk —
  extending ADR 0006's existing privacy-routing precedent for
  work-sensitive content rather than adding a new routing concept.
- Sending meeting transcripts to a **cloud** LLM role requires a separate,
  explicit, off-by-default setting distinct from the general chat routing
  policy (Phase 21). A meeting transcript is not a single conversational
  turn, and Phase 21's routing policy was designed and reasoned about
  around per-turn messages — don't let a standing "fallback to cloud"
  policy silently ship an entire recorded meeting off-box the first time
  local inference hiccups.
- Raw audio is deleted after successful transcription by default
  (configurable retention window for troubleshooting only); the
  `MeetingTranscript`/`MeetingMinutes` records are the durable artifacts,
  governed by Phase 12's provenance/sensitivity/expiry model as their own
  record type — not folded into general memory (see Data model).
- Before starting/uploading a recording, the UI requires an explicit
  attestation checkbox ("I have consent to record the other participants")
  — a documented limitation, not an enforcement mechanism (see Non-goals).
- Failed/cancelled jobs delete any partial audio/transcript rather than
  leaving orphaned sensitive data behind.

## Implementation sequence

1. Confirm Phase 23's migration framework is in place; add the
   `meeting_jobs`/`meeting_transcripts`/`meeting_minutes`/
   `meeting_action_items` migration in companion-core's schema.
2. Add `shared/models/meeting.py` and `shared/protocols` route constants
   for both the hub STT endpoint and core's job/meetings API.
3. Extend `reachy_hub/stt.py`'s usage for long-form audio (verify actual
   behaviour/timing on real 30-90 minute recordings, not just short clips —
   faster-whisper handles long audio internally, but measure real CPU time
   before assuming it fits the background-job budget) and add hub's
   upload endpoint plus the internal transcription-task submit/poll
   endpoint pair, with hub-side background transcription so neither call
   blocks.
4. Wire live recording from the existing Call Reachy WebRTC session as a
   second intake path feeding the same hub transcription-task endpoints.
5. Add core's `MeetingJob` model, worker loop, and job-status endpoint;
   the worker drives a job from `uploaded` through hub's transcription
   task to `transcribing` → `summarizing`.
6. Add core's chunked summarization/extraction pipeline and the
   `MeetingMinutes`/`MeetingActionItem` stores, with the retry/fallback
   behaviour above.
7. Add action-item review/confirm, writing confirmed items into the
   existing Phase 11 tasks store with meeting provenance.
8. Add the operator UI Meetings view (upload/record, status against core,
   minutes, action-item review) and the cloud-transcript opt-in setting.
9. Apply sensitivity classification and routing to the finished minutes;
   verify they never reach Reachy's speaker.

## Exit criteria

| Check | Required result |
|---|---|
| End-to-end | A real recording (uploaded and, separately, via Call Reachy) produces a summary, key points, and action items, visible in the operator UI |
| Async correctness | A core restart mid-job does not leave the job stuck; a hub restart mid-transcription surfaces as a clean job failure, not a hung call; the UI reflects failure or resumption, not silent stall |
| Long transcript | A transcript exceeding one provider call's context produces a complete, non-truncated summary via the map-reduce path |
| Malformed extraction | A forced malformed-JSON response is retried once, then falls back to the plain-text summary with the failure flag set — action items are never silently dropped |
| Action items | No task is created without explicit owner confirmation; confirmed tasks carry meeting provenance and appear in the existing tasks list/search |
| Privacy routing | Minutes are never spoken through Reachy's speaker in any mode; sending a transcript to a cloud role requires the separate opt-in setting, off by default |
| Retention | Raw audio is deleted after successful transcription by default; a failed/cancelled job leaves no orphaned audio/transcript |
| Regression | Existing Python/Ruff/browser checks and Phase 8/15/19-21 tests still pass; no new dependency pulls unwanted GPU wheels (check per the uv dependency conventions in AGENTS.md) |

Record real timing (upload → transcript, transcript → minutes) for at least
one recording in the 30-60 minute range against the actual deployed stack,
not just short test clips — long-form STT throughput on the deployment
hardware is the main unverified assumption in this plan.
