# ADR 0040: Verified processing provenance and fixed disclosures in meeting email

Status: proposed (built on a branch with [ADR 0039](0039-supervised-meeting-minutes-email.md); not merged or deployed).

## Context

A meeting-minutes email tells outsiders who Reachy is, how reliable it is and where the meeting's content went. The first version ended with a generic line. Nothing recorded where each step ran (transcription,
speaker detection, summary, minutes, title, analysis), so any privacy sentence would have been an assumption, and the owner could edit it away. A sentence like "processed entirely on private infrastructure" is
a factual claim to people who never saw the system, so it must follow records or not be made.

## Decision

1. **Record where each step ran, as it runs.** `Meeting.processing_events` is an append-only list of `{step, location, at, subject}`, `location` being `local`, `external` or `unverified`. It is written in the same
   statement as the step it describes (the worker stages, `set_output`, `set_title`), or just before content leaves for a non-local model (cloud summaries and minutes, titles, correction suggestions, the owner's
   explicit cloud question about a meeting, analysis runs), so a failed attempt still counts. Regenerating or clearing an output never removes an event.
2. **Where an endpoint is comes from its address.** `endpoint_location` calls an address local only when it is loopback, private, link-local, Tailscale (100.64/10), or a single-label or `.local/.lan/.internal`
   name. A public host name is `unverified`: a name cannot show that the machine behind it is private. The cloud role is `external`. In-process alignment is `local`.
3. **The verdict is computed, never asserted.** `assess` returns `external` if any step is recorded external; otherwise `local` only when every needed step has a local record (transcription, speaker detection,
   alignment, and for the summary, minutes, generated title and included analysis run, a local record tied to that exact output) and nothing is unverified; otherwise `unverified`. Records that predate this ADR
   are absent, so old meetings are `unverified`, never local. No model is consulted.
4. **Statements.** `local`: "This meeting was processed entirely on private infrastructure. No meeting content was sent to external AI services." `external`: "Some meeting content was processed by an external
   AI service for <steps>." plus "All other processing took place on private infrastructure." only when every other step is positively local; no provider, host or model names. `unverified`: a neutral line
   about Reachy being a self-hosted assistant designed with privacy in mind, saying that a verified record is unavailable and that the message makes no claim. A separate sentence always states that **email
   delivery is separate from AI processing** and that sending through Gmail (or another provider) transfers the approved email and its attachment to that provider.
5. **Fixed text is a rendering layer.** The draft's `body` is only the editable middle. `email/frame.py` renders the opening (who Reachy is, whom it writes for, the "about me" paragraph, meeting, date,
   participants) and the closing (attachment line, accuracy note, sign-off, processing and delivery statements, "Reviewed and approved by <owner>") from a `frame` stored in the draft's `source` at preparation.
   The preview, the package hash and the sent message all use the same function. A meeting-minutes draft without a valid frame cannot be turned into a message. The owner's name is a sender setting and is required.
6. **Approval, hash and delay are unchanged and now cover the disclosure.** The package hash includes the frame and the full rendered text. `source_is_current` also compares the verdict, so new external
   processing after preparation blocks queueing until the message is prepared again; the dispatch loop's sender refuses (without retrying) if the verdict changed after approval, and queueing refuses if the mail
   service changed.

## Consequences

- Meetings processed before this ADR carry the neutral statement until their summary and minutes are written again with locally recorded steps; their transcription and speaker steps stay unrecorded, so they stay neutral.
  This is deliberate.
- A local model served from a public host name is reported as unverified. The fix is an internal address or name, not a weaker rule.
- The email is plain text; the identity and disclosure text carries no markup. An HTML alternative would need the same single renderer and is not part of this change.
- Migration `037_processing_provenance` adds `meetings.processing_events` and `mail_sender.owner_name`; `deploy/homelab/rollback-037.sql` drops them (cancel unsent meeting-minutes drafts first).
- Not covered: documents attached to a meeting (Phase 53 slides) are outside the record; chat questions about a meeting that the owner did not send to the cloud are local by routing and are not recorded.
