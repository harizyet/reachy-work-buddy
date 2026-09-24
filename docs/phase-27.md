# Phase 27 — Embodied meeting secretary

Status: planned, not implemented. The product goal is Reachy acting as a
physically or hybrid-present secretary: physically in the room for meetings,
recording only when explicitly enabled, producing minutes, catching questions
and action items directed at the owner, and routing anything private to the
owner instead of speaking it aloud. A generic cloud/virtual meeting bot makes
Reachy mostly irrelevant to the workflow and drifts this project toward
Fireflies/Fathom/OpenClaw territory instead of embodied assistance; that path
is kept only as a deferred possibility (see
[Deferred: virtual/cloud attendance](#deferred-virtualcloud-attendance)),
never a Phase 27 prerequisite.

Build on [Phase 26](phase-26.md) for transcription, minutes and reviewed
action items, and Phase 23 for migrations, encrypted credentials and
read-only calendar access. Every stage in this phase requires Phase 22b
hardware acceptance; there is no virtual-only path that skips the robot.

This keeps Phases 24–26 easy to reason about as one line each:

- **Phase 25** — who may interact with, or be heard by, Reachy.
- **Phase 26** — how Reachy turns a captured meeting into a useful record.
- **Phase 27** — how Reachy acts as a bounded physical secretary in meetings.

## Delivery stages

| Stage | Owner outcome | Release boundary |
|---|---|---|
| 27a — Meeting companion | Owner is physically present in the meeting with Reachy; the owner explicitly enables recording for that meeting; Reachy produces minutes, flags questions/action items, and routes anything private to the owner instead of speaking it aloud | Owner-present the whole time, so Phase 25's existing presence gate already covers it; no ADR amendment needed; recording is off by default and per-meeting explicit |
| 27a.2 — Continuity during temporary absence | The owner explicitly marks a short step-out during an already-authorized 27a meeting; Reachy keeps capturing meeting audio within that bounded window under a capped `TEMPORARY_MEETING_ABSENCE` lease and, on return, privately delivers a categorized delta of what changed — not a transcript dump | Requires a narrow Phase 25 ADR amendment: the lease is capped in duration, meeting-STT-pipeline audio only, grants no conversation/tool authority and no general room speech, and it auto-expires; opened and closed only by explicit owner action, never silently inferred from presence sensing |
| 27b — Physical secretary | The owner is temporarily or fully absent from a physical meeting; Reachy attends in the room under explicit preauthorization, with a visible recording indicator and bounded capture; questions directed at the owner are forwarded privately, never answered | Owner-absent capture requires an accepted ADR amendment to Phase 25's presence gate, a local host who accepts placement/stop responsibility, and supervised hardware acceptance |
| 27c — Bounded delegation | Reachy can ask pre-approved questions, deliver exact pre-approved statements, or relay the owner's own explicitly authored reply verbatim, attributed to the owner | Deterministic content only: no LLM-generated commitments, no paraphrasing, no answering on the owner's behalf; each delivery is bound to exact approved text, meeting and expiry |

Completion of 27a is not completion of Phase 27. Each stage has separate
evidence and can remain disabled while earlier stages are usable. 27a.2
extends 27a's existing capture/minutes pipeline rather than replacing it, but
it is not authorization-free: Phase 25's planned rule is that room audio
input requires fresh, live owner-presence evidence, and loses that
authorization the moment the owner leaves. Continuing to capture while the
owner steps out is technically owner-absent capture, even if the recording
began while they were present. 27a.2 therefore needs its own narrow
[Phase 25](phase-25.md) exception — see below — not a claim that no exception
is needed.

The difference between 27a.2 and 27b is how much authority that exception
carries, and who the owner still is to the meeting. In 27a.2 the owner
remains an attendee who expects to resume participation within minutes: the
exception is a short, capped, meeting-STT-only lease with no tool authority
and no general room speech, layered on top of an already-running 27a
recording. In 27b the owner is absent for most or all of the meeting, and
Reachy is standing in for them under the full owner-absent grant, a local
host's placement/stop responsibility, and stronger operational controls
(indicator enforcement, lobby/duration bounds, provider-style recovery).
27a.2 is a narrower, capped exception; 27b is the full one. Neither
implicitly grants the other.

## 27a — Meeting companion (owner present)

1. Before a meeting, the owner explicitly enables recording for that specific
   occurrence — no ambient or default-on capture. Camera stays off for this
   phase; only audio is captured. Show a visible recording indicator for the
   duration.
2. Reachy captures audio like an in-room Call Reachy session and hands it to
   the existing Phase 26 pipeline: transcript, structured summary, key points
   and action-item candidates. Reuse the Phase 26 job; do not build a second
   minutes engine.
3. While capturing, detect questions and requests that are directed at the
   owner (explicit name/address, or contextual "can you follow up on...").
   Anything that would reveal private information (calendar details, inbox
   content, prior private conversation) is never spoken aloud in the room —
   it is queued for private delivery to the owner (Telegram or another bound
   private channel) exactly like Phase 18's briefing routing and
   [ADR 0006](adr/0006-response-routing.md).
4. Minutes, decisions, unresolved questions and action candidates are
   delivered privately after the meeting. Action items become tasks only
   after the owner's explicit confirmation through Phase 26's existing path.
5. Since the owner is present the entire time, this stage needs no change to
   Phase 25's presence gate: ordinary room-audio rules already apply, and
   recording is an explicit owner action layered on top of them.

## 27a.2 — Continuity during temporary absence

During an owner-authorized 27a meeting, the owner may explicitly mark
themselves temporarily away. Reachy continues capturing meeting audio for
that bounded absence window under a **`TEMPORARY_MEETING_ABSENCE` lease**,
records decisions, action candidates and owner-directed questions, and
privately delivers an evidence-linked delta summary when the owner returns.
Reachy does not answer on the owner's behalf or accept commitments during
the absence — the same rule as every other stage.

Because Phase 25's presence-based rule would otherwise lock room audio the
moment the owner is no longer in view, opening this window requires a narrow,
explicitly accepted amendment to Phase 25, scoped much tighter than 27b's:

- requires an already-running 27a recording; it cannot originate its own
  capture authority
- opened only by explicit owner action, never auto-started from presence
  loss alone
- same meeting only, and only for the remainder of that meeting's authorized
  recording window
- feeds only the meeting STT/minutes pipeline — no conversational agent
  authority, no tool calls, no private-data retrieval, no general room
  speech synthesis beyond the fixed acknowledgment line
- capped duration with automatic expiry: default maximum 15 minutes,
  absolute maximum 30 minutes, configurable only down from these defaults
- the local recording indicator remains active throughout, unchanged from
  ordinary 27a capture

1. **Opening the lease is an explicit owner action**, spoken ("Reachy, I'm
   stepping out for five minutes, keep me updated") or through the operator
   UI's meeting view (a "Step away" control). This creates an `AbsenceWindow`
   bound to the running meeting and starts the capped lease clock; it does
   not touch conversational/tool authority, which stays locked exactly as
   Phase 25 otherwise requires.
2. While the lease is open, capture continues, bounded to the meeting
   pipeline. Incrementally classify new segments into a fixed set of
   categories — `DECISION`, `ACTION_ITEM`, `OWNER_QUESTION`, `DEADLINE`,
   `TOPIC_CHANGE`, `INFORMATIONAL` — rather than asking the LLM to summarize
   the whole meeting after the fact. The category set is deterministic; the
   LLM's job is summarizing within a category, not inventing one.
3. Owner-directed questions detected during the window use the same
   detection and private-forwarding path as the rest of 27a/27b. If
   unanswered by the time the owner returns, they are surfaced immediately
   as part of the delta, not just left in the eventual full minutes.
4. **Closing the window is also an explicit owner action** — returning and
   saying so, or an "I'm back" control — which sets `returned_at` and the
   ending transcript segment. Phase 25 presence sensing, once available, may
   suggest that the owner appears to have returned or stepped away ("You
   appear to have stepped away. Start catch-up mode?"), but it only ever
   proposes; it never silently opens or closes the window itself.
5. On close, generate the catch-up **only from the interval bounded by the
   window's start and end segments** — never by asking an LLM to find the
   right period inside the full transcript. Deliver it privately (matching
   this phase's existing private-routing rule), prioritized owner question →
   decision affecting the owner → new commitment/deadline → assigned action
   → other decisions → other context, as a short list ("3 important updates
   while you were away"), with an evidence link and source segment IDs per
   item, and actions such as "view details," "show unanswered questions" and
   "show decisions." Reachy does not automatically read the delta aloud in
   the room; if room context makes a short spoken acknowledgment
   appropriate, it is limited to a fixed line such as "I caught a few
   updates while you were away — I've sent them privately," never the
   content itself.
6. **Reaching the lease's maximum duration without an explicit return is not
   a silent extension.** At expiry the `AbsenceWindow` closes as `expired`,
   the `TEMPORARY_MEETING_ABSENCE` lease ends, and meeting audio capture
   reverts to whatever Phase 25 otherwise requires for an owner who is not
   present — normally a lock, unless the owner (or a present local host) has
   separately converted the meeting to a 27b grant before expiry. The catch-up
   for an expired window is generated the same way, bounded to the interval
   up to expiry. A ten-minute toilet break must never silently become
   unattended authorization to record the rest of a two-hour meeting; that
   requires the owner or a local host to explicitly take out a 27b grant.

`AbsenceWindow` is a record on the running meeting, not a new top-level
entity: `meeting_id`, `owner_id`, `left_at`, `returned_at`,
`transcript_start_segment`, `transcript_end_segment`, `status`
(`open`/`closed`/`expired`/`abandoned`). An absence window left open past the
meeting's end without an explicit return closes as `abandoned` when the
meeting capture itself ends, and its catch-up is still generated from its
bounded interval, not the remaining meeting.

## 27b — Physical secretary (owner absent)

1. A local host places Reachy in the meeting room and accepts responsibility
   for placement and for an accessible stop control. The owner preauthorizes
   the room, time window and capture scope remotely or beforehand — an
   authenticated, time-limited grant, not a standing permission.
2. This requires an explicit ADR amendment to [Phase 25](phase-25.md): a
   **meeting capture mode** may ingest room audio into the isolated meeting
   pipeline only while the owner is absent, only for the authorized window,
   and it must never unlock the normal conversation/tool path, remote speak,
   or private-response gates. Ordinary owner-present behavior is unaffected.
3. Show an unmistakable capture indicator throughout; stop locally on expiry,
   stop control, authorization loss, a broken indicator, or disconnection
   beyond the bounded lease. No ambient pre-roll and no capture continuing
   after the owner's authorized window ends.
4. Questions directed at the absent owner are forwarded privately, using the
   same detection and delivery path as 27a. Reachy never answers on the
   owner's behalf, even if the answer exists in a brief, calendar, memory or
   prior conversation — it uses only a fixed, authorized status such as
   "I can't answer for them; I've queued the question for them."
5. Test owner-absent behavior with the owner supervising remotely and a local
   host present, consistent with this repository's rule that unattended
   hardware experiments require explicit, separately accepted supervision
   procedures. Motion can remain disabled for note-taking.

## 27c — Bounded delegation

Reachy may only ever do one of three things on the owner's behalf, and never
improvise beyond them:

1. **Ask a pre-approved question** — content, meeting and delivery count fixed
   in advance by the owner.
2. **Deliver an exact pre-approved statement** — fixed content, no paraphrase.
3. **Relay the owner's own explicitly authored reply**, attributed to the
   owner and delivered verbatim — for example, the owner sends "Tell them
   I'll review it tomorrow" and Reachy says "Hariz says: I'll review it
   tomorrow." The exact owner-authored text is relayed, never rewritten,
   summarized or expanded by an LLM.

Each delivery is bound to an exact content ID, meeting, validity window and
expiry, checked deterministically at send time — never inferred from
context or from the LLM's judgment of what the owner would probably say.
Default to one delivery per approved item; no automatic resend after an
uncertain delivery. Ordinary private replies from the owner (e.g. a normal
Telegram message) stay private and are never broadcast into a meeting unless
an explicit, separate send-to-meeting action is taken for that exact text.
No voice cloning and no claim that Reachy is the owner.

## Authority, disclosure and privacy

Meeting speech, chat and transcripts are untrusted source material. They
never enter the owner's command/confirmation channel, acquire TEXT authority,
call tools, or override delegation policy. Keep a separate meeting context
without automatic access to private inbox, calendar details, general memory
or owner chat history.

| Capability | Required authority |
|---|---|
| Enable recording (27a, owner present) | Explicit per-meeting owner action; off by default |
| Open/close a temporary-absence lease (27a.2) | Explicit owner action (spoken or UI) plus the accepted narrow Phase 25 ADR amendment for `TEMPORARY_MEETING_ABSENCE`; capped duration, meeting-STT-only, no tool/general-speech authority; presence sensing may only suggest, never decide or auto-extend |
| Attend and capture while owner absent (27b) | Owner's exact attendance grant, the accepted Phase 25 ADR amendment, and a local host's placement/stop acknowledgment |
| Fixed disclosure, status or refusal | Exact versioned content; hub enforces destination and expiry on dispatch |
| Answer a question directed to the owner | Forbidden. Forward privately and leave unanswered pending the owner |
| Ask a pre-approved question / deliver a pre-approved statement (27c) | Exact content ID, meeting binding, validity window; no generation or paraphrasing |
| Relay the owner's own answer (27c) | Owner-authored text plus an explicit authenticated send-to-meeting action bound to that exact question, meeting and expiry |
| Create a task from an action item | Owner review and confirmation through Phase 26 |
| Email/calendar writes, promises, accepting deadlines or commitments | Outside Phase 27; existing action gates are never bypassed |

Meeting artifacts remain private text by default under Phase 26 and
[ADR 0006](adr/0006-response-routing.md). No automatic minutes email, meeting
chat publication, room readout, or sharing with the organizer. Keep meeting
content and any secret URLs out of operational logs. Backups follow
documented retention.

## Questions directed to the owner

Required from 27a onward: when a participant directs a question at the
owner, forward it privately through the owner's bound Telegram chat or
another configured, authenticated private channel. The platform must not
answer on the owner's behalf under any circumstance. Private transcript Q&A
for the returned owner is separate and never publishes an answer into the
meeting.

Detect explicit owner-name/address references and contextual requests for
the owner's input from incremental speech transcripts. Forward ambiguous
cases as "possibly directed to you," with the uncertainty visible; do not
invent speaker identity. Live forwarding requires incremental
transcription/intake, not waiting for Phase 26's post-meeting job, with a
release target of forwarding within 15 seconds of a finalized question
segment under normal connectivity.

Each alert contains the meeting title, question text, timestamp, asker label
when available, minimal relevant context and a private evidence link. Send
only to the owner's verified destination, never a group or meeting audience.
A channel outage queues alerts for later delivery, marked with their
original time; it never triggers an automatic answer. Persist a stable
question ID, meeting/owner binding, source segment IDs, delivery attempts
and acknowledged/deferred status; deduplicate transcript revisions and
bound retries. Unanswered questions remain in the final minutes and the
owner's follow-up list.

## Service ownership and durable lifecycle

Preserve [ADR 0001](adr/0001-service-boundaries.md),
[ADR 0006](adr/0006-response-routing.md),
[ADR 0011](adr/0011-destructive-action-consent.md) and
[ADR 0018](adr/0018-hybrid-llm-routing.md). Two separate Phase 25 ADR
amendments are needed, not one: a narrow `TEMPORARY_MEETING_ABSENCE`
amendment before 27a.2 (capped duration, meeting-STT-only, no tool/general-
speech authority, requires an already-running 27a recording), and the full
owner-absent meeting-capture-mode amendment before 27b (owner-absent
attendance from the start, local host responsibility, stronger operational
controls). This plan alone does not change runtime gates.

- **Core** owns capture-grant policy, occurrence scheduling for 27b,
  question-escalation records, minutes/Q&A and reviewed follow-ups. Reuse the
  Phase 26 meeting job after capture; do not create a second minutes engine.
- **Hub** owns the private-channel session, incremental intake/STT for live
  question detection, and delivery of authorized outputs. It reports transport
  facts to core rather than deciding whether the owner delegated attendance.
- **Embodiment/daemon** own bounded physical capture, the visible recording
  indicator, playback and local stop enforcement.
- **Operator UI** extends Meetings with recording enablement (27a), 27b
  attendance grants, private briefs, progress, transcript references and
  follow-up review. Preserve relative paths, literal transcript rendering,
  owner cookies/CSRF and bearer boundaries.

Extend shared models/protocol constants and versioned migrations with a
capture-grant record for 27b, delegation version, occurrence key, deadlines,
capture consent state and linked Phase 26 artifact IDs, plus an
`AbsenceWindow` record for 27a.2 (meeting ID, owner ID, `left_at`,
`returned_at`, start/end transcript segment, status) and the fixed
`DECISION`/`ACTION_ITEM`/`OWNER_QUESTION`/`DEADLINE`/`TOPIC_CHANGE`/
`INFORMATIONAL` category on classified segments used for both live-meeting
minutes and absence delta generation. Timestamp transcript segments; display
names from any diarization are unverified labels, never inferred from Phase
24 owner recognition.

Persist state transitions and idempotency keys for 27b grants. Reject
replayed, out-of-order and wrongly bound callbacks. Loss of authorization
stops capture/output and initiates local departure/shutdown of the capture
mode; reconcile actual state after recovery. Report coverage gaps and
distinguish attendance failure from minutes-processing failure. By default
failed/cancelled jobs follow Phase 26's partial-data deletion policy;
retaining incomplete notes needs an explicit owner choice made before
capture, and such notes must be marked incomplete.

## Implementation sequence and acceptance

1. Ship 27a first: it needs no ADR amendment, since the owner is present the
   whole time. Wire explicit per-meeting recording enable, reuse Phase 26
   processing, and add private question-forwarding and the no-answer gate.
2. Accept the narrow Phase 25 ADR amendment for `TEMPORARY_MEETING_ABSENCE`;
   add 27a.2 on top of 27a's running capture: the capped lease, explicit
   open/close actions, the `AbsenceWindow` record, incremental deterministic
   categorization, expiry-without-silent-extension, and the interval-bounded
   private delta on return.
3. Accept the full Phase 25 ADR amendment for owner-absent meeting capture
   mode; implement 27b's grants, local capture/indicator/stop enforcement
   and run supervised acceptance with the owner remote and a local host
   present.
4. Add 27c's pre-approved question/statement delivery and the owner-reply
   relay, enforced by exact content-ID/meeting/expiry checks before
   connecting any meeting audio output path.

| Gate | Required evidence |
|---|---|
| Companion (27a) | Real in-room meeting with owner present: explicit recording enable, minutes delivered privately, questions detected and routed privately, no room-spoken private content |
| Continuity during absence (27a.2) | Owner leaves for 5–10 minutes; discussion continues; at least one decision occurs and one question is directed at the owner; owner returns; private catch-up contains both, categorized and prioritized; timestamps/evidence point only to the absence interval, not the full meeting; Reachy makes no owner commitments during the window; separately, a lease left open past its maximum duration expires to `expired`/Phase 25 lock rather than silently continuing capture, and only an explicit 27b conversion resumes it |
| Physical secretary (27b) | Real room audio with owner absent and local host present: placement, indicator, stop, expiry, outage and feedback tested; capture mode never unlocks ordinary conversation/tool path or private room output |
| Bounded delegation (27c) | Approved questions/statements delivered only within limits and expiry; owner-authored replies relayed verbatim only after explicit send action; forged, replayed, expired and post-meeting sends rejected |
| Owner-directed questions | Real questions reach the bound private channel with context and evidence; explicit/ambiguous references, STT revisions, bursts, restart, channel outage and owner silence tested; zero platform-authored answers even when a brief contains one |
| Privacy | No content in logs/localStorage; unauthorized artifact access denied; capture refusal and deletion failures handled explicitly |
| Regression | Appropriate Python/Ruff/browser checks; real Postgres migrations/restore; existing consent, private routing, recognition and telepresence behavior preserved |

Store dated hardware evidence under `docs/verification/`; distinguish
fixtures from real physical acceptance. Update operator/deployment guides
when implemented. No recording, external communication or hardware operation
is part of this plan document itself.

## Deferred: virtual/cloud attendance

A cloud/virtual meeting bot that joins Google Meet/Teams/Zoom without Reachy
in the room is a possible future integration, not part of this phase's
implementation sequence. It contributes little to Reachy's embodied identity
and overlaps with existing Fireflies/Fathom/OpenClaw-style products. If
pursued later, it needs its own feasibility spike and ADR before any
implementation work, and should not gate 27a/27b/27c.

Research checked 2026-09-23, kept here only as background for a future
decision:

- Google's [Meet Media API requirements](https://developers.google.com/workspace/meet/media-api/guides/get-started)
  currently require the project, OAuth principal and all participants to be
  enrolled in Developer Preview, with restricted media scopes — not a
  general-purpose route into ordinary external meetings.
- Microsoft's [application-hosted media bot requirements](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/requirements-considerations-application-hosted-media-bots)
  require a .NET media library and Windows Server in Azure for production —
  not a small addition to this Python homelab.
- A managed bot provider such as [Recall.ai](https://docs.recall.ai/docs/bot-overview)
  documents meeting bots across conferencing platforms as a candidate
  transport, not a selected vendor or proof of acceptance in the owner's
  tenant.

If this is picked up later, treat managed-bot media processing as a separate
off-by-default opt-in from Phase 26's cloud-LLM transcript setting, disclose
vendor processing independently, and do not bypass host controls or silently
switch to browser scraping.
