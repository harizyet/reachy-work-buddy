# Phase 54: Identify Speakers

Status: **built on branch `feature/meeting-speaker-identification`, not merged, not deployed, no APK released.** Decision: [ADR 0038](adr/0038-meeting-speaker-identification.md). Evidence: [verification record](verification/phase-54-speaker-identification-2026-10-14.md).

Open a completed meeting, choose **Identify speakers**, listen to two or three short samples of each detected speaker, name them (or mark Unknown / Skip), save. The names then appear in the transcript, summary, minutes and analysis.

## What was built

| Layer | Where |
|---|---|
| Sample selection (pure, deterministic) | `companion_core/meetings/speaker_samples.py` |
| Identity records, fingerprint, supersede | `companion_core/meetings/speaker_identity.py`, `Meeting.speaker_identity`, `MeetingOutput.speaker_basis`, `Meeting.stale_outputs` |
| Routes | core `GET/PUT /meetings/{id}/speakers/identify` (the older `PUT .../speakers` writes the same record); hub proxies in `reachy_hub/operator.py`; constant `MEETING_SPEAKERS_IDENTIFY` |
| Storage | migration `035_meeting_speaker_identity`, `deploy/homelab/rollback-035.sql` |
| Phase 31/53 | assignee note, `attribution_changed` on items |
| Web | `features/meetings/SpeakerIdentify.tsx`, section in `MeetingDetail.tsx`, stale banners |
| Android | `data/SpeakerIdentify.kt`, `ui/SpeakerIdentifyScreen.kt`, `MeetingPlayer.playRange` |

## Not built (by design)

Outbound email, a contact directory, voice embeddings, any stored or exported audio sample, automatic regeneration of summaries.

## Before deploying

Owner approval, then the usual sequence: backup, build core + hub + coding-agent together, apply 035, new Phase 48 boundary ([deployment](deployment.md)). The web `dist` is built by the hub image. Android 0.19.0 is unchanged in version; bump at release.
