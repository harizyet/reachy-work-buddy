# Phase 32A.V: coordinated UAT deployment to the homelab (2026-10-15)

Owner authorization: "Approve resuming the controlled homelab deployment preflight" with conditions (coordinated deploy of migration 038 with core, hub, coding-agent and the speaker sidecar; fresh restore rehearsal; Phase 48 boundary; rebuild the APK from the committed branch). **Not merged. No threshold set. Voice evidence is non-authoritative. Calibrated verification, meeting speaker identification, new session management and robot features are not enabled.** Evidence before deploy: [synthetic validation](phase-32a-synthetic-validation-2026-10-15.md), [Android slice](phase-32a-android-2026-10-15.md).

## What was deployed

| | Before | After |
|---|---|---|
| Schema | `037_processing_provenance` | `038_voice_profiles` (`voice_profiles` empty) |
| core | `41e49f86816f` (tag `deepfix-08160e7`) | `49afe7a51686` (tag `p32a-aa3e38b`) |
| hub | `cd95ae5fb26b` | `964b2618039d` |
| coding-agent | `9a98434aa79c` | `d463050ff880` |
| migrate | `b3ae77c2f0d1` | `7a5b336f7de5` |
| speaker | none | `a8b2b22dda4c` (`reachy-speaker:p32a-aa3e38b`, profile `speaker`, no published port, volume `reachy-homelab_speaker-data`) |
| `.env` | | one line added: `VOICE_IDENTITY_ENABLED=true` (backup `env-before`); thresholds stay unset |

**Source.** Branch `deploy/phase-32a-uat` at `aa3e38b8de87f71f49c83ef92667231d3bd51508`, built in the clean worktree `../reachy-work-buddy-deploy-32a`: `23db3fb` (the code that was running; the hub/core images dated from `aa8a39f`/`08160e7` and there is no service, shared or web code difference from `08160e7` to `23db3fb`) + `4acc4f9` (test tracking only) + the two Phase 32A.V commits (`85712a8`, `b0f88ba`, cherry-picked). **Deliberately not included:** `1a43805` (persona default, an open owner decision) and the earlier session's uncommitted `RecordingHandoff` regex change and documentation edits. The diff of the deploy head against the running base touches only Phase 32A.V files (`services/reachy-hub`, `shared`, migration 038 and its test updates, `deploy/homelab` speaker and compose, `tools`, Android, docs). The feature branch `feature/phase-32a-voice-identity` (`b0f88ba`) holds the same two commits on top of `4acc4f9` and `1a43805`.

## Gates (all passed before any production change)

| Gate | Result |
|---|---|
| Verified backups | Preflight dump (1,921,487 bytes), rehearsal dump, and stop-time dump (1,921,487 bytes, TOC of 314 entries equal to the rehearsal dump); `.env`, SecretStore and coding-agent key files copied with matching checksums (`~/reachy-backups/phase32a-deploy/`, 0600/0700). The key file equals the 037-era copy. Off-host copies still do not exist (the owner accepted this earlier) |
| Rollback images | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-32a`, each verified equal to the running image ID before the build |
| Configuration | Environment fingerprints (names and value hashes, no values) for core, hub and coding-agent captured before and after |
| Phase 48 state | Counters read before the stop; shadow-router files copied (see below) |
| Restore rehearsal | A fresh production dump restored into an isolated pgvector container: all 63 tables had row counts equal to production. The new migrate image took it `037 → 038`; every pre-existing table kept its count; `rollback-038.sql` returned it to 037 with the table gone and the counts equal; re-upgrade gave 038 and an empty table |
| Full-stack compatibility on restored data | The exact new core, hub and speaker images against the restored copy (test owner password set on the *copy* only): login, `/voice-identity/status` (ready, uncalibrated), enrolment of eight synthetic clips and commit (profile version 1, encrypted in the copy), verify results `unavailable / not_calibrated` for both the enrolled voice and another voice, a voice turn with transcript (1.0 s warm), the 0.19.0 spoken `/messages` path, 2 meetings intact, chats listed, speaker stopped → the turn still returned a transcript with `service_unavailable` and conversation replies continued, the session stayed valid. The rehearsal containers, network and copy were deleted afterwards |
| Exact revisions and build inputs | Clean worktree, `git status` empty, images tagged `p32a-aa3e38b`, all five image IDs recorded in `built-images.txt` |
| No unrelated changes | See Source |
| `speaker` profile activation | `compose up --dry-run` planned exactly: create the volume and speaker, recreate hub, core and coding-agent, and nothing else. After the real run the other containers kept their uptimes (Postgres 2 weeks, Caddy 2 weeks, vLLM 10 h, document worker 29 h, transcription, diarization, semantic router, SearXNG) |
| Preconditions at the stop | No meeting in progress (both `complete`), no queued or sending email, no reminder pending, the only scheduled alarm is a disabled one from 2026-10-07, no coding session running |

## Timeline (UTC, 2026-10-15)

12:48:56 core stopped gracefully (30 s), hub and coding-agent stopped; stop-time dump taken and compared. PgBouncer restarted (its three idle pooled connections made the migration job refuse, as in the 037 deploy). 12:49 migrate: `038_voice_profiles`. **12:50:03 core, hub, coding-agent and speaker started** (downtime about 67 s). Hub voice providers ready at 12:50:32. Speaker healthy (model `speechbrain/spkrec-ecapa-voxceleb@0f99f2d0` loaded in 20 s; the model weights came from the Hugging Face Hub on first start, no audio or embedding left the host).

## Phase 48 boundary

Counters of the previous segment (`process_started_at` 2026-10-15T03:06:44Z, ended 12:48:56Z): `{"attempted":7,"excluded_spoken":3,"no_match":4}`, saved with a copy of the shadow-router files in `~/reachy-backups/phase48-boundary-32a/` (`segment-before-32a.txt`, `shadow-copy/`, `stop-time.txt`, `start-time.txt`). **New segment from 2026-10-15T12:50:05Z, counters `{}` at start.** Frozen Phase 44/48 files are untouched. **Probes I sent into the new segment** (to verify chat, each "what is two plus two", through the hub with the bearer token): 12:51:28 one text turn, 12:51:28 one voice-modality turn, 12:52:04 one voice-modality turn with the speaker stopped. The counters read `attempted 2, no_match 1, excluded_spoken 1` after the first two; exclude these three turns from any evidence analysis. Separately, the rehearsal core on the *restored copy* answered three such prompts through the owner's configured model provider (the restored secret store holds the real key); they carried no private content.

## Verification after deployment

| Check | Result |
|---|---|
| Schema, containers, health | head `038_voice_profiles`; core, hub, coding-agent on the new images; speaker healthy; hub and core `/health` ok; no tracebacks in start-up logs; 0 restarts |
| Environment | core and coding-agent environments identical to before; hub gained only `VOICE_IDENTITY_ENABLED=true`, `SPEAKER_SERVICE_URL`, and three empty values (`SPEECH_SERVICE_TOKEN`, both thresholds: hash of the empty string) |
| Existing functions, read before and after with the same scripts | Hub (bearer): `/health`, `/status`, `/meetings` 2, `/planner/tasks` 2, `/planner/notes` 3, `/planner/reminders` 0, `/planner/alarms` 9, unauthenticated routes 401/404 as before. Core (service token): `/meetings` 2, `/documents` 0, `/notes` 3, `/tasks` 2, `/reminders` 0, `/memory-candidates`, capture counters, meeting-analysis and meeting-email config, deep-review info. **The only difference between before and after: `/voice-identity/status` went from 404 to 401** (the route now exists and refuses the bearer and anonymous callers) |
| Authentication | anonymous `/auth/me` 401; `/voice-identity/*` and `/owner-recognition/*` 401 through Caddy without an owner cookie; the speaker is not reachable through Caddy (unmatched paths return an empty 200, as for any random path) and publishes no host port |
| Chat | a text turn and a voice-modality turn answered normally; the spoken turn is capped as before and counted `excluded_spoken` |
| Speaker failure | with the speaker container stopped, a chat turn still answered, hub health ok, baseline unchanged; speaker restarted healthy in 7 s |
| Phase 48 | capture counters route works; the new segment counted the probes |

**Not verified (needs the owner):** the owner's browser or phone login, documents upload and Q&A with real files, a reminder or alarm firing, Telegram, Gmail, a real meeting through the worker, any physical-phone behaviour, and the production `/voice-identity/turn` path (it needs an owner session, which I did not mint; it was exercised against the restored copy with the same images).

## Rollback (not invoked)

With the four services stopped: `docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < deploy/homelab/rollback-038.sql` (drops `voice_profiles`, i.e. every enrolled profile; the last line must print `037_processing_provenance`); retag `reachy-rollback/<svc>:pre-32a` as the service images and recreate core, hub and coding-agent (`up -d --no-deps --no-build`); stop and remove `reachy-homelab-speaker-1`; remove the `VOICE_IDENTITY_ENABLED` line from `.env`. The stop-time dump is the full-restore fallback. Keep every asset until the owner accepts.

## Outstanding risks

- A hub recreation re-downloads nothing for the speaker, but the first speaker start needs outbound access to the Hugging Face Hub; a rebuilt speaker with no network will not become ready (voice chat is unaffected, results read `service_unavailable`).
- The compose commands were run from the deploy worktree with a placeholder `SEARXNG_SECRET_KEY` (interpolation only; the SearXNG container was never touched). A later plain launcher run from the main checkout will see a different compose working directory for hub/core/coding-agent and recreate them once; that is expected.
- Voice evidence is uncalibrated and has no anti-spoof or replay protection; nothing may rely on it.
- Evaluation clips are raw owner audio kept (encrypted) on the hub until deleted; the capture directory is on a persistent volume.
- Hub-side STT latency on the homelab for a voice turn is still unmeasured on a phone.
- The persona-default commit and the earlier uncommitted documentation edits remain undeployed and uncommitted in the main checkout.

## Next gate

Owner physical-phone UAT and GV collection ([runbook](phase-32a-device-runbook.md), [checklist](phase-32a-uat-checklist.md), [protocol](phase-32a-gv-protocol.md)); then the evaluation report; then a separate decision on calibration thresholds; then any activation of owner verification, meeting identification (32A.M) or session management (32A.1). Merging the branch is a separate approval.
