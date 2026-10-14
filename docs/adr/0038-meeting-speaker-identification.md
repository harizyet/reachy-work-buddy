# ADR 0038: Owner-confirmed meeting speaker identities

- Status: **Proposed 2026-10-14** for [Phase 54](../phase-54.md). Extends [ADR 0030](0030-meeting-speaker-names-and-reviewed-corrections.md).
- Date: 2026-10-14

## Context

Diarization labels speakers (`SPEAKER_00`); ADR 0030 let the owner type a name per label. Naming someone from a label alone is hard, so the owner wants to hear short samples of each speaker first, and wants the names to carry into the transcript, summaries, analysis and (later) emailed minutes without any of those silently keeping a wrong attribution.

## Decision

1. **Diarization stays evidence; identity is the owner's statement.** Raw labels and spans are never rewritten. A confirmation is `status` (`named`, `unknown`, `skipped`), an optional `name`, an optional `contact_id`, and a time, keyed by the diarization label, in `meetings.speaker_identity` (migration 035, one nullable JSONB column). `speaker_names` remains the single overlay every reader already uses; it is derived from the `named` identities, so no consumer changed.
2. **Samples are chosen deterministically from existing output and are not stored.** `meetings/speaker_samples.py` scores windows (5 to 10 s) of a speaker's own diarization turns by length, overlap with other speakers, recording gaps and recognised-text density; clean and spread-out windows win, unclear ones are offered only when nothing clear exists, and a speaker with too little speech gets a reason instead. A sample is a time range of the existing recording, played through the existing authenticated `GET /meetings/{id}/audio` (byte ranges). No audio is read or cut on the server, no embedding is computed, no clip is persisted or exported.
3. **A contact is a reference, never an address.** `contact_id` is optional and opaque (no contact store exists yet; the screen suggests names already used in other meetings). The name and any email verification are separate facts; nothing infers an address from a name or a voice. This is the data-model preparation for a later Email Meeting Minutes feature; no sending is implemented.
4. **Re-diarization cannot inherit names.** Each state records a fingerprint of the diarization it was made against. When `mark_diarized` replaces a different result, the confirmations move to `superseded` (readable, never applied) and display names reset to generic; an identical result keeps them. Saving is refused with 409 if the screen's fingerprint is out of date.
5. **Nothing generated keeps a stale attribution silently.** Summary/minutes record a `speaker_basis` of the names they were written under; `Meeting.stale_outputs` lists those that differ (an output with no recorded basis counts as stale once any name is set). Phase 31 and 53 already hash the transcript including display names, so a rename marks their runs changed and the owner re-runs them; Phase 31 items additionally report `attribution_changed` when their evidence names a renamed speaker. Regeneration uses the existing routes.
6. **A name is not proof of ownership.** A first-person commitment still yields a candidate assignee only from the transcript wording; the item now says the name is a label, not proof, and the owner's approval before a task exists is unchanged.
7. **Same trust boundary.** Core exposes `GET/PUT /meetings/{id}/speakers/identify`; the hub proxies them behind the owner-cookie/CSRF or bearer check. Meeting sensitivity, scope and deletion are unchanged: the mapping lives on the meeting row and goes with it.

## Consequences

- Schema head moves to `035_meeting_speaker_identity`: a deploy is backup, then core, hub and coding-agent together (`rollback-035.sql` undoes it; names survive).
- Pre-existing summaries/minutes in meetings that already have names show as possibly stale until regenerated. That is deliberate.
- Sample quality depends on diarization quality; the screen says when only unclear stretches exist.
