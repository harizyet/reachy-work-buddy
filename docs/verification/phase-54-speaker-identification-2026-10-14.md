# Phase 54 verification: Identify Speakers (2026-10-14)

Branch `feature/meeting-speaker-identification`. **Nothing deployed, no production data touched, no APK released.** Labels: *unit* = in-process mocks; *PG* = disposable `pgvector/pgvector:pg16` container (removed); *browser* = real Chromium against a real hub+core in process with a synthetic tone recording; *emulator* = Android API 34 AVD against the same fixture hub (AVD `spk_test`, throwaway). Not done: a physical phone, a real diarized meeting with real voices, an owner UAT.

| Acceptance item | Evidence |
|---|---|
| 1 Each speaker has playable samples | unit (selector, routes); browser played a sample of a real WAV through the hub; emulator played one |
| 2 Samples match speaker and timestamps | unit: synthetic WAV, one tone per speaker; every sample (and alternate) fetched by byte range through the real audio route carries only its speaker's tone (Goertzel) |
| 3 Short/overlapping/low quality degrade | unit: too-little-speech reason, overlap and gap and sparse-text marked `low`, unclear shown only when nothing clear exists; browser/emulator show the reason for a speaker with 1.5 s |
| 4 Names persist and show in transcript | unit, PG reconnect, browser reload, emulator after force-stop |
| 5 Changing a name updates surfaces | unit/web: transcript lines, outputs prompt, identify screen |
| 6 No silent stale attribution | unit: `stale_outputs` (incl. removal and no recorded basis); Phase 31 `transcript_changed_since_run` and `attribution_changed`; web and Android banners |
| 7 Unknown supported | unit, web, browser, emulator |
| 8 Deletion removes mappings | unit and PG: the mapping is on the meeting row; no snippet is ever stored |
| 9 Unauthorized clients | hub unit: 401 without session for identify GET/PUT, audio and meeting; 403 without CSRF; browser: 401 after logout |
| 10 Existing workflows | core meeting/analysis/multimodal tests, 102 PG tests, web 356, Playwright (see below), Android 155 |

## Results

- Core: `test_meeting_speaker_identity.py` 30, `test_meeting_speaker_identity_postgres.py` 5 (migration, repeatable, rollback keeps names, supersede, delete). All PG migration tests updated for head 035: 102 passed. Defects found by real tests: the explicit INSERT in `create_meeting` (PG only), a non-implemented `downgrade`, non-idempotent upgrade; all fixed.
- Hub: `test_operator.py` 30 (new identify test), `test_web_client.py` 18 after regenerating `samples.json` (ids/timestamps churn is normal for that file).
- Web: vitest 356 (7 new); `tsc` and build clean; Playwright `speakers.spec.ts` desktop + mobile (real `<audio>`, stops at the sample end, names saved, reload, logout 401, no sideways scroll). One unrelated `app.test.tsx` test failed once under parallel load and passed alone and on rerun.
- Android: JVM 155 (9 new). Emulator: signed in through the real UI, played a sample (Pause shown, back to Play at the end), named one speaker and marked one unknown, one Save, transcript showed the name and kept it after force-stop. The emulator has no audio output (`-no-audio`), so what was verified is player state and timing, not sound. The emulator's bottom bar is hidden by the known IME quirk, so the density was set to get the rail layout; the detail pane is therefore narrow in screenshots.
- ruff clean.
- **Full Playwright (both projects): 131 passed, 6 skipped, 9 failed.** The 9 failures are `notepad.spec.ts:42` ("Tasks for next week", reply wording) and `planner.spec.ts:379` and `:403` (no-coding-agent Overview, list cancelled on logout), each on desktop and mobile where applicable. **Not caused by Phase 54:** with my work stashed, the same desktop specs on pristine `main` (`b81ec7a`) fail identically (5 of 5, same assertion messages). They are stale browser tests of earlier phases, left unchanged here. All `speakers.spec.ts` and `analysis.spec.ts` tests pass.

## Limits and open items

- Sample quality on real recordings is unjudged: the fixture is tones. A real meeting with real diarization needs the owner's listen.
- `contact_id` has no directory behind it; suggestions are names used in other meetings.
- Regeneration is the owner's action; nothing regenerates automatically.
- Android: no automated UI test (JVM logic and emulator walk-through only).

## Android debug APK for owner UAT (not installed, not a release)

`~/reachy-releases/reachy-companion-0.19.0-speakers-debug.apk`, sha256 `d4483df6925ad723b90f5c565e085418cc6bd0668c27a038db940c6610842102` (checksum file alongside). Built from the Phase 54 branch; `versionName` is still 0.19.0 / versionCode 4 (bump at the next real release), so installing it replaces any other 0.19.0 debug build. It needs the hub to run the Phase 54 core and hub, which are NOT deployed: against today's production hub the Identify speakers section will show an error and everything else behaves as before.
