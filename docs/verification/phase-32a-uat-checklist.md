# Phase 32A.V: physical-phone UAT checklist (debug APK 0.20.0)

For the owner's review. **Nothing here has been run on a phone.** The APK is built and checksummed but not installed; the hub side (speaker service, `VOICE_IDENTITY_ENABLED`, migration 038) is not deployed. Run this against a hub you have prepared and approved (see the [GV protocol](phase-32a-gv-protocol.md) prerequisites). Record device model, Android version, app and backend commits, result and any waiver for each row (the [Phase 32 acceptance matrix](../phase-32.md#4-acceptance-test-matrix)).

APK: `~/reachy-releases/reachy-companion-0.20.0-voice-identity-debug.apk` (sha256 in `….apk.sha256`). Rollback: `reachy-companion-0.19.0-tier-tags-debug.apk` (the version you accepted). Installing 0.20.0 over 0.19.0 keeps your sign-in and settings; it adds no Android permission.

## A. Install and baseline (voice identity OFF at the hub)

| # | Step | Expect |
|---|---|---|
| A1 | Install 0.20.0 over 0.19.0; open the app | Still signed in; Talk, Meetings, Planner, Library unchanged |
| A2 | Menu → **Voice identity** | "Voice identity is switched off at the hub…"; no enrolment controls; the phone-recognition switch is shown |
| A3 | Talk → voice mode, say "what time is it" | Works exactly as before (the phone's recogniser) |
| A4 | Voice mode: "Reachy, begin meeting recording" | Recording starts as before (Phase 52 behaviour) |

## B. Enrolment (voice identity ON, not calibrated)

| # | Step | Expect |
|---|---|---|
| B1 | Menu → Voice identity | "Speaker service ready. Not yet calibrated: every result shows as unverified or inconclusive." No profile yet |
| B2 | Record a clip in a noisy spot or with the phone far away | Clip listed as "not usable" with a plain reason; not counted |
| B3 | Delete that clip | Removed; count unchanged |
| B4 | Record five good clips, reading the phrases | "5 good clips: ready to save" |
| B5 | Try to save without the consent box, then without the password | Save button stays disabled; nothing is stored |
| B6 | Tick consent, enter a wrong password, save | "That password is not right."; nothing stored |
| B7 | Correct password, save | "Voice profile saved."; profile version 1 listed |
| B8 | Start a new enrolment, record two clips, **Cancel enrolment and delete all clips** | Draft empties; the saved profile is unchanged |
| B9 | Replace the profile (five clips, password) | Version 2 |
| B10 | Try to enrol using a second person's voice mixed with yours | Save refused: "The clips do not sound like one person". (The consistency limit, 0.35, is an uncalibrated placeholder: report if it wrongly refuses your own clips.) |

## C. Using it (not calibrated)

| # | Step | Expect |
|---|---|---|
| C1 | Menu → Voice identity → **Test my voice**, speak | "Owner match: unverified" (or "inconclusive" for a poor clip); never "verified" |
| C2 | Voice mode, ask a normal question | Normal answer; a line under the ball shows "Owner match: unverified" for about ten seconds, then disappears |
| C3 | Voice mode, ask something private (calendar, a note) | The same answer as before this feature: the same privacy ceiling for spoken requests; the match line changes nothing |
| C4 | Voice mode, ask Reachy to send an email or forget something | Reachy still refuses voice confirmation and says to confirm by text |
| C5 | Voice mode with a second person speaking | Conversation works; line says unverified/inconclusive; you are not signed out |
| C6 | Turn the hub's speaker service off (or stop the container), use voice mode | Voice chat keeps working; line says "Voice check unavailable" |
| C7 | Turn the **whole hub** off briefly, then on | A voice turn fails with a message and the mic stops (as a recogniser error does); after the hub returns, Unmute works |
| C8 | Menu → Voice identity → switch on "Use this phone's speech recognition…" | Voice chat uses the phone's recogniser; no match line appears; switch off to return |
| C9 | Start a meeting recording, then open Voice identity and tap Record | "Stop the meeting recording first: the microphone is in use."; the recording is unaffected |
| C10 | Lock the phone and unlock during voice mode | No lasting badge; any earlier result has expired |

## D. Delete

| # | Step | Expect |
|---|---|---|
| D1 | Voice identity → Delete… → wrong password | Nothing deleted |
| D2 | Correct password → **Delete profile** | "Voice profile deleted."; no profile; a voice turn shows "No voice profile" |
| D3 | (Hub operator) `SELECT count(*) FROM voice_profiles` | 0 |

## E. Evaluation session (separate approval to collect)

Follow the [GV protocol](phase-32a-gv-protocol.md). In the app check: password required to switch recording on; the second-person block is disabled until the consent box is ticked; counters rise with each clip; "Delete all evaluation clips…" empties the hub's store and switches recording off.

## F. Only after a calibration is approved (not part of this UAT)

Set the thresholds, recreate the hub, then expect "Owner voice verified" for your voice, "Owner match: not verified" for another person, "inconclusive" for poor clips, and still no change to anything C3 and C4 tested.

## What would fail this UAT

A "verified" shown before calibration; a different answer, privacy ceiling or confirmation rule on a voice turn than before; voice chat stopping because the speaker service is down; a clip or score visible anywhere after the session; a new Android permission prompt; an enrolment that stores without the consent box and password.
