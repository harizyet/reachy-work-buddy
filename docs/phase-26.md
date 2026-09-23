# Phase 26 — delegated meeting attendance and secretary

Status: planned, not implemented. The product goal is a disclosed AI secretary
that attends virtual meetings on the owner's behalf, keeps useful notes, and
eventually represents the owner through Reachy in a physical meeting when the
owner is unavailable. Fireflies/Fathom-style attendance and notes are the
baseline; bounded participation is a separate release gate.

Build on [Phase 25](phase-25.md) for transcription, minutes and reviewed action
items, and Phase 23 for migrations, encrypted credentials and read-only calendar
access. Virtual attendance does not depend on a robot or Phase 24. Physical
attendance depends on Phase 22b hardware acceptance, Phase 24's implemented
security gates, and the explicit meeting-mode amendment described below.
Phase 23 real-account acceptance remains necessary for calendar-backed use.

## Delivery stages

| Stage | Owner outcome | Release boundary |
|---|---|---|
| 26a — Virtual note-taker | Select a calendar occurrence or paste a supported meeting link; Reachy's disclosed bot joins while the owner is absent, forwards owner-directed questions privately and delivers minutes | One proven provider/platform path first; observe-only except fixed disclosure/status messages; never answers for the owner |
| 26b — Bounded secretary | Supply an agenda, questions and a shareable brief; Reachy can deliver approved statements, ask approved questions and collect answers | Separate per-meeting participation permission; deterministic output checks; no autonomous commitments or unrestricted conversation |
| 26c — Physical delegate | A local host places Reachy in a meeting; the owner authorizes attendance remotely or beforehand; notes arrive privately afterward | Owner-absent capture and narrowly scoped speech require an accepted ADR amendment and supervised hardware acceptance |

Completion of 26a is not completion of Phase 26. Each stage has separate
evidence and can remain disabled while earlier stages are usable.

## Owner workflow and useful output

1. In Meetings, choose **Send Reachy**, select a calendar occurrence or enter
   a supported URL, and review the time, organizer, destination, provider,
   processing locations, retention and attendance mode. Calendar read access
   does not itself authorize joining. No join-everything default.
2. Approve an occurrence-specific delegation in authenticated text. Bind it
   to the owner, meeting identity/link, time window, mode and expiry. For v1,
   recurring meetings need approval per occurrence; changing the destination,
   permissions or time outside the approved window invalidates approval.
3. Optionally provide a private preparation brief and a separate, explicit
   shareable brief. Select exact statements/questions Reachy may deliver in
   secretary mode. Preview the disclosure identifying Reachy as an AI assistant
   taking notes for the absent owner, without impersonating the owner.
4. Show scheduled, joining, waiting for admission, attending, paused, leaving
   and processing states, plus actionable failure reasons. Let the owner
   cancel, stop capture or leave remotely. A waiting bot is not reported as
   attending. Join-only and recording authorization are separate states.
5. Deliver summary, decisions, unresolved questions, action candidates and
   an **Anything requiring your decision** section. Include timestamped
   evidence links, attendance interval, capture gaps and attribution quality.
   Proposed owners/deadlines remain unknown unless supported by evidence.
6. Let the owner ask questions privately against that meeting's transcript,
   with source references and an explicit insufficient-evidence answer.
   Review/edit action candidates through Phase 25's task-confirmation path;
   prepare follow-up drafts without sending messages or modifying calendars.

The owner can attend the same call without creating another bot. A hybrid
meeting uses one selected capture source; do not double-record through both
the robot microphone and a virtual bot. Initial scope is one active attendance
per owner, with conflicts surfaced for explicit selection rather than guessed
priorities. Use timezone-aware occurrence times and show the owner's timezone.

## Questions directed to the owner

Required from 26a onward, including physical meetings in 26c: when a participant
directs a question to the owner, forward it privately through the owner's
bound Telegram chat or another configured, authenticated private channel.
The platform must not answer questions on the owner's behalf, even if the
answer appears in a brief, calendar, memory or previous conversation. Private
transcript Q&A for the owner is separate and never publishes an answer into
the meeting.

Detect explicit owner-name/address references and contextual requests for the
absent owner's input from incremental speech transcripts and supported meeting
chat. Forward ambiguous cases as **possibly directed to you**, with uncertainty
visible; do not invent speaker identity. Live forwarding requires incremental
transcription/intake in hub, not waiting for Phase 25's post-meeting job.
The provider spike must prove this path, with a release target of forwarding
within 15 seconds of a finalized question segment under normal connectivity;
measure end-of-speech-to-channel delivery separately, including STT delay.

Each alert contains the meeting title, question text, timestamp, asker label
when available, minimal relevant context and a private evidence link. Send
only to the owner's verified destination, never a group or meeting chat.
Select the channel during delegation; honor its privacy/notification settings,
surface queued or failed delivery, and never fall back to a public destination.
If no channel is configured, require setup before unattended attendance.

Persist a stable question ID, meeting/owner binding, source segment IDs,
delivery attempts and acknowledged/deferred status. Deduplicate transcript
revisions and callback retries; bound retries and coalesce bursts while keeping
each question accessible. A channel outage queues alerts for later delivery,
marked with their original time; it never triggers an answer. Provider acceptance
of a message is not proof the owner read it. Unanswered questions remain in
the final minutes and the owner's follow-up list.

Reachy may use only a fixed, authorized status such as “I can't answer for
them; I've queued the question for them,” accurately reflecting delivery state.
It must not promise a response or infer one from silence. In 26b/26c, an optional
relay can deliver the owner's own typed answer verbatim, attributed to the
owner, only after an explicit send-to-meeting action bound to that question,
meeting, exact text and expiry. Ordinary Telegram replies stay private unless
that send action is taken. No generated answers, paraphrases, implied consent,
automatic forwarding of owner messages or stale replies after the meeting ends.
An owner can instead join the call or handle the question later.

## Provider feasibility gate

The existing Call Reachy WebRTC connection is not a conferencing-platform bot.
Phase 23's Calendar scopes do not grant Meet media access. Before choosing
dependencies, prove join, lobby admission, capture, departure and cleanup in
an actual owner-authorized test meeting with the owner absent from the call.

Research checked 2026-09-23:

- Google's [Meet Media API requirements](https://developers.google.com/workspace/meet/media-api/guides/get-started)
  currently require the project, OAuth principal and all participants to be
  enrolled in Developer Preview. Its media scopes are restricted. Do not
  assume this is a general-purpose route into ordinary external meetings.
- Microsoft's [application-hosted media bot requirements](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/requirements-considerations-application-hosted-media-bots)
  require a .NET media library and Windows Server in Azure for production.
  Native Teams media hosting is not a small addition to this Python homelab.
- A managed bot provider such as [Recall.ai](https://docs.recall.ai/docs/bot-overview)
  documents meeting bots and interactive agents across conferencing platforms.
  This is a candidate transport, not a selected vendor or proof of acceptance
  in the owner's tenant.

Proposed first spike: Google Meet through a managed bot adapter, because the
project already has Google calendar discovery. Compare that with a supported
self-hosted approach before committing. Record supported platforms, tenant
restrictions, host admission/recording controls, OAuth/admin requirements,
data region, deletion behavior, pricing and measured hourly cost. Recheck
provider documentation at implementation time. Additional Zoom/Teams support
must pass its own matrix; do not advertise universal support from one demo.
If managed processing is declined and no suitable local path passes, mark
virtual joining blocked; Phase 25 upload remains available but does not satisfy
26a. Do not bypass host controls or silently switch to browser scraping.

## Authority, disclosure and privacy

Meeting speech, chat, screen content, participant names and transcripts are
untrusted source material. They never enter the owner's command/confirmation
channel, acquire TEXT authority, call tools, or override delegation policy.
Keep a separate meeting context, without automatic access to private inbox,
calendar details, general memory or owner chat history.

The permission boundary is deliberately small:

| Capability | Required authority |
|---|---|
| Join and capture | Owner's exact attendance grant plus the meeting's applicable host/recording permission and participant notice |
| Fixed disclosure, status, refusal or approved question/statement | Exact versioned content allowed by the grant; hub enforces destination and expiry on dispatch |
| Answer a question directed to the owner | Platform answering is forbidden; forward privately and leave unanswered pending the owner |
| Relay the owner's own answer (26b/26c) | Owner-authored text plus explicit authenticated send-to-meeting action for that exact question, text, meeting and expiry; no generation or paraphrasing |
| Changed prepared statement | New authenticated text approval of exact content; never use a prepared statement to answer for the owner |
| Create a task | Owner review and confirmation through Phase 25 |
| Email/calendar writes, promises, accepting deadlines or commitments | Outside Phase 26; existing action gates are never bypassed |

For 26b, core may propose when to ask an approved question, but a deterministic
gate checks its content ID, meeting, validity and remaining send count. Default
to one delivery per approved item, no automatic resend after an uncertain
delivery, and a bounded queue. Support interruption and cancellation of audio.
No voice cloning or claims that Reachy is the owner. An attendee asking a
question cannot expand the shareable brief or authorize disclosure.

Require an owner consent attestation and a visible participant disclosure;
honor platform permission signals. Do not claim these establish legal consent.
Provide an accessible stop-recording control; participant objections pause
capture for resolution, never grant new privileges. Late arrivals must receive
notice through a persistent disclosure or renewed notice. If the adapter cannot
enforce the configured capture policy, leave and report the limitation.

Meeting artifacts remain private text by default under Phase 25 and
[ADR 0006](adr/0006-response-routing.md). No automatic minutes email, meeting
chat publication, room readout, or sharing with the organizer. Approved live
statements are a separate output class, not permission to read private minutes.

Managed-bot media processing needs a separate off-by-default opt-in from
Phase 25's cloud-LLM transcript setting: local summarization does not mean
local capture when a bot vendor receives the audio. Disclose vendor processing
and any provider transcription independently. Retain audio only as permitted
by Phase 25; apply expiry/deletion to vendor copies, local chunks and derived
artifacts. Surface pending/failed remote deletion and retry it; never claim
confirmed deletion from merely submitting a request. Keep content and secret
meeting URLs out of operational logs. Backups follow documented retention.

## Service ownership and durable lifecycle

Preserve [ADR 0001](adr/0001-service-boundaries.md),
[ADR 0011](adr/0011-destructive-action-consent.md) and
[ADR 0018](adr/0018-hybrid-llm-routing.md). Before implementation, accept a
meeting-delegation ADR defining the grants, output classes, provider credential
handoff and physical exception; this plan alone does not change runtime gates.

- **Core** owns delegation policy, occurrence scheduling, durable attendance
  orchestration, audit, preparation, minutes/Q&A, owner-question escalation
  records and reviewed follow-ups. Reuse
  the Phase 25 meeting job after capture; do not create a second minutes engine.
  Core receives text and media references, never raw audio. Credentials remain
  in the core-owned SecretStore; define least-privilege authenticated handoff
  to hub for provider operations, never a general secret-read API.
- **Hub** owns provider adapters, authenticated callbacks, channel sessions,
  incremental media intake/STT, private question notifications and delivery of
  authorized outputs. It reports transport
  facts to core, rather than deciding whether the owner delegated attendance.
  Provider SDK isolation, if required, stays behind hub over defined protocols;
  it does not become a second reasoning or consent service.
- **Embodiment/daemon** own bounded physical capture, indicators, playback and
  local stop enforcement. Existing outbound robot connectivity carries control;
  use the defined media transport rather than buffering audio in control frames.
- **Operator UI** extends Meetings with attendance controls, grants, private
  briefs, progress, transcript references and follow-up review. Preserve relative
  paths, literal transcript rendering, owner cookies/CSRF and bearer boundaries.

Extend shared models/protocol constants and versioned migrations with an
owner-bound attendance record, delegation version, provider/session identity,
occurrence key, deadlines, capture consent state and linked Phase 25 artifact
IDs. Timestamp transcript segments and attach provider speaker IDs only when
available; display names are unverified labels. Mixed room audio may use
anonymous diarization only after separate evaluation; never infer identity
from Phase 24 owner recognition or fabricate attribution.

Persist state transitions and idempotency keys. Use a unique owner/occurrence
key, worker leases and reconciliation with the provider before retries to
avoid duplicate bots after a crash or lost join response. Reject replayed,
out-of-order and wrongly bound callbacks; verify signatures, freshness and
session ownership. Restrict meeting/media URLs to supported provider origins,
validate redirects and block private-network fetches. Do not trust a webhook's
owner field or expose unauthenticated artifact downloads.

Attendance follows `scheduled → joining → waiting/attending → leaving → ended`,
with explicit cancelled, failed and expired outcomes and a paused capture
substate. Finishing capture starts the linked Phase 25 processing job. Bound
join retries, lobby wait, reconnect window, total duration, media buffers,
storage and provider spending. Set concrete configurable limits in the spike
report before release; default maximum meeting duration is two hours, lobby
wait ten minutes, and concurrency one. Calendar cancellation or owner revocation
cancels pending joins and initiates departure from active meetings.

Loss of authorization/lease stops capture/output and initiates departure;
provider-side maximum-duration/auto-leave must bound an orphan bot if hub/core
are unavailable. Reconcile actual departure after recovery. A removed or denied
bot does not keep rejoining. Report coverage gaps and distinguish attendance
failure from minutes-processing failure. By default failed/cancelled jobs follow
Phase 25's partial-data deletion policy; retaining incomplete notes needs an
explicit owner choice made before capture. Such notes must be marked incomplete.

## Physical meeting delegation

Reachy is placed by a person; autonomous navigation, locating rooms and moving
between meetings are out of scope. The camera is off for meeting recording by
default; this phase records audio, not room video or faces. Recognition sensing,
if needed by the existing safety gates, must be disclosed separately.

[Phase 24](phase-24.md) currently denies room speech/input without a verified
owner present. An explicit ADR amendment is required before 26c can operate:
an authenticated, time-limited **meeting capture mode** may ingest participant
audio only into the isolated meeting pipeline while the owner is absent. It
must never unlock the normal conversation/tool path. A separate grant permits
only the exact disclosure/secretary outputs described above while absent;
ordinary room conversation, remote speak and private-response gates stay in
force. Phase 25's owner-start/stop restriction is extended only to these bounded
scheduled grants, not ambient capture.

A local meeting host accepts responsibility for placement and an accessible
stop control. The owner preauthorizes the room/robot/time window; the host
acknowledges participant notice before capture starts. Show an unmistakable
capture indicator throughout, and stop locally on expiry, stop control,
authorization loss, broken indicator or disconnection beyond the bounded lease.
No ambient pre-roll or continuing capture after departure. Refuse simultaneous
telepresence/Call Reachy capture and avoid speaker-to-microphone feedback.

Owner absence from the eventual meeting is a product requirement, not permission
to run unattended hardware experiments. Initial startup, motion and physical
acceptance require the owner present and supervising under repository rules.
Test owner-absent behavior with the owner supervising remotely and a local host
present. Any relaxation of operational supervision requires a separately
accepted deployment procedure; motion can remain disabled for note-taking.

## Implementation sequence and acceptance

1. Finish required Phase 23/25 foundations. Run the provider feasibility spike
   and record a concrete support/cost/retention matrix; accept the delegation ADR.
2. Implement grants, migrations, scheduling and hub adapter with idempotent
   join/leave, callback validation and bounded recovery. Ship the 26a UI and
   reuse Phase 25 processing/private delivery. Include incremental question
   detection, durable private-channel forwarding and the no-answer gate in 26a.
3. Add evidence-linked Q&A and the shareable-brief/approved-output flow; enforce
   26b permissions in code before connecting meeting audio/chat output.
4. Accept the physical-mode ADR amendment and deployment procedure; implement
   local capture/indicator/stop enforcement and run supervised 26c acceptance.

| Gate | Required evidence |
|---|---|
| Virtual attendance | Real 30–60 minute supported-platform meeting, owner absent from call: scheduled join, host admission, disclosed capture, automatic departure, private evidence-linked minutes and reviewed tasks |
| Scheduling | Controlled-time tests for timezone/DST, changed/cancelled occurrence, conflicting meetings, expired grants and recurrence; no unauthorized or duplicate joins |
| Recovery | Real process restarts during joining/capture/processing; duplicate/out-of-order callbacks, lost responses, removal, network outage and orphan timeout; gaps/failures accurately visible |
| Authority | Malicious speech/chat/transcripts and forged owner/modality/callback data produce no private retrieval, confirmation, unapproved speech or external writes |
| Owner-directed questions | Real virtual and physical questions reach the bound private channel with context and evidence; explicit/ambiguous references, STT revisions, bursts, restart, channel outage and owner silence tested; report detection misses/false alerts and delivery latency; zero platform-authored answers even when the brief contains an answer |
| Owner reply relay | Ordinary private replies are never broadcast; only explicitly sent owner-authored text is relayed verbatim to the matching question/meeting; forged, replayed, expired and post-meeting sends rejected |
| Secretary | Approved questions/statements delivered only to the bound meeting within limits; uncertain delivery is not repeated; unanswered questions return privately; cancellation stops queued/live output |
| Privacy | No content in logs/localStorage; separate vendor/cloud opt-ins; unauthorized artifact access denied; capture refusal and remote/local deletion failures handled explicitly |
| Physical | Real room audio with owner absent and local host present; placement, indicator, stop, expiry, outage, feedback and overlapping speech tested; no ordinary voice/tool unlock or private room output |
| Quality and capacity | Human-reviewed decisions/actions and evidence timestamps, unknown speakers honest, no invented commitments; record processing latency, resource use, media gaps and cost on the deployed stack |
| Regression | Appropriate Python/Ruff/browser and isolated-dependency checks; real Postgres migrations/restore and built-image integration; existing consent, private routing, recognition and telepresence behavior preserved |

Store dated provider and hardware evidence under `docs/verification/`; distinguish
fixtures, real virtual calls and physical acceptance. Update operator/deployment
guides when implemented. No account connection, paid provider provisioning,
recording, external communication or hardware operation is part of this plan.
