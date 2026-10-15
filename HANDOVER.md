# Handover

Snapshot: 2026-10-15. Read [AGENTS.md](AGENTS.md) first. This page is the current
state and the open items only; [project state](docs/project-state.md) owns
deployment limits and cross-phase acceptance, the [roadmap](docs/plan.md#6-implementation-roadmap)
owns phase status, and [deployment](docs/deployment.md) owns procedures. Dated
evidence is in [verification records](docs/README.md#verification-records).

The earlier chronological log (about 860 lines, every phase from 22 to 55) was
retired on 2026-10-15. It is not lost: `git show 1a43805:HANDOVER.md`. Do not
rebuild it here; put a finished item in its phase page, ADR or verification record,
and keep only what the next session must act on.

## Where things stand

- **Repository:** `main` (clean; `origin/main` identical). Feature branches are all
  merged and deleted except `phase-47f`, which is checked out in the worktree
  `../reachy-work-buddy-47a`. Two detached deploy worktrees also exist
  (`../reachy-work-buddy-deploy-030`, `../reachy-work-buddy-deploy-docfix`); they are
  leftovers from earlier deployments and can be removed with `git worktree remove`
  once the owner agrees.
- **Homelab (compose project `reachy-homelab`, MS-01):** schema
  `037_processing_provenance`; core, hub and coding-agent redeployed together at each
  schema step, and core and hub again for the deep-local generation budget and model
  tier tags. Image IDs and the Phase 48 segment boundaries are in the
  [deployment records](docs/README.md#deployment-records), not here.
- **Production flags on:** `DOCUMENT_LIBRARY_ENABLED`, `NOTEPAD_PROCESSING_ENABLED`,
  `INTENT_ROUTER_ENABLED`, `MEETING_ANALYSIS_ENABLED` (supervised trial, no analysis
  run yet at last record), `MEETING_MULTIMODAL_ENABLED`, `MEETING_EMAIL_ENABLED`, and
  `SHADOW_ROUTER_ENABLED` (Phase 37 trial), and the Phase 48 flags (memory candidates and
  capture, indexing, retrieval, `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED`). Verified against the
  running core container and `deploy/homelab/.env` on 2026-10-15. Selective *answering* is
  absent: Compose does not pass `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED`. The old
  "shadow: owner said NOT yet" note (2026-10-12) concerned the older B1a shadow
  (`KNOWLEDGE_SHADOW_ENABLED`, `knowledge/shadow.py`), which is not passed by Compose and is
  off; the Phase 48F selective shadow has been on since 2026-10-10. Re-check with
  `docker inspect` (never `docker compose config`).
- **Model manager:** runs as a systemd **user** unit
  (`scripts/install-model-manager-service.sh`, `Restart=always`, lingering on); a killed
  manager came back in under 15 s. A real machine reboot has not been tested.
- **Android:** 0.19.0 in the tree; the newest APK is
  `~/reachy-releases/reachy-companion-0.19.0-tier-tags-debug.apk` (sha256 `9491e5e0…3d27`),
  installed and accepted by the owner (not itemised). Debug APKs are delivered by hand.
- **Meeting-minutes email (Phase 55, ADRs 0039 and 0040):** deployed, merged and
  accepted after owner UAT, but no real send has been recorded yet. The owner must
  enter their name in Settings before a message can be prepared. Meetings processed before
  schema 037 carry the neutral "unverified" statement.
- **Recently owner-accepted (reported, not itemised):** Home dashboard, calendar feed
  (production URL and addresses set), persona location for weather, phone bottom bar,
  Identify Speakers (Phase 54), voice and typed recording command (Phase 52), the
  provenance disclosure.
- **Persona default:** commit `1a43805` changed the shared default persona prompt so
  Reachy says it works for one owner, not a team. It is a partial guard only: the default
  cannot name the owner, and the prompt in `persona_config` is owner-editable and is
  the only persona text the model sees. The owner's own named prompt works. **Not
  recorded as deployed** (it touches `shared/models`, core, hub and the web bundle).

## Open items

Needs the owner (nothing here is approved until they say so):

1. A real Gmail send of the meeting-minutes email with the provenance text. The
   local-only sentence has never been produced from a real production recording.
2. The model-manager reboot test and the Google sign-in round trip.
3. Phase 53 acceptance on the owner's own deck and meeting (deployed and enabled
   2026-10-14; no acceptance recorded). Phase 31: a real 30 to 60 minute meeting
   analysed and reviewed.
4. Whether to deploy the persona-default commit, and whether to add a fixed,
   non-editable instruction filled with the owner's name (needs a core redeploy).
5. (Resolved 2026-10-15: `.gitignore` now anchors `/test/`; the Android unit tests are tracked.)
6. Off-host copies of the SecretStore key file and keyring files (none exist; the
   key backup at `USB Storage/reachy-keys/` was accepted as sufficient on 2026-10-08).
   The Postgres backup plan ([implementation plan](docs/postgres-backup-implementation-plan.md))
   is paused, not implemented.
7. Phase 37 shadow-router trial (enabled 2026-10-05, 500-turn cap; `SHADOW_ROUTER_ENABLED=true` in the running core): evaluation chain
   in [shadow-router](docs/shadow-router.md#trial-procedure), then destroy every
   recorded file (owner retention rule). Current state of the log unverified.
8. Phase 30 calibration (wake alert threshold, the 24g held-out run) and the removal
   of `WAKE_DEBUG_LOG_REJECTED_TRANSCRIPTS` once calibration ends. See
   [Phase 30](docs/phase-30.md).
9. Phase 32A ([phase-32](docs/phase-32.md), [ADR 0041](docs/adr/0041-shared-voice-identity.md)): G0 approved 2026-10-15 (HTTPS deferred;
   HTTP over Tailscale stays). 32A.V is built end to end on the **unmerged, undeployed, uncommitted** branch
   `feature/phase-32a-voice-identity`: `speaker` sidecar, `voice_profiles` (migration 038, schema head moves), `/voice-identity/*`
   routes, Android 0.20.0 (capture, enrolment, owner-match line, GV evaluation screen), GV tool. Debug APK
   `~/reachy-releases/reachy-companion-0.20.0-voice-identity-debug.apk` (sha256 `01c1a821…ef6`) is **not installed**; rollback is the
   0.19.0 tier-tags APK. Needs from the owner: review and physical-phone UAT
   ([checklist](docs/verification/phase-32a-uat-checklist.md)), a hub prepared for it (separate approval: migration 038, `speaker`
   profile, `VOICE_IDENTITY_ENABLED`, `OWNER_RECOGNITION_CAPTURE_DIR`), consented GV recordings
   ([protocol](docs/verification/phase-32a-gv-protocol.md)), and later any threshold approval and the 32A.1 session-revocation gate.
   No threshold is selected. Evidence: [verification record](docs/verification/phase-32a-android-2026-10-15.md),
   [synthetic-audio validation](docs/verification/phase-32a-synthetic-validation-2026-10-15.md) (0 functional failures; one speaker-service
   defect found and fixed; synthetic-only measurements, no real FAR/FRR). Branch commits `85712a8`, `b0f88ba`.
   **Deployed to the homelab for UAT 2026-10-15 12:50 UTC** ([record](docs/verification/phase-32a-deployment-2026-10-15.md)): schema
   `038_voice_profiles`; core, hub, coding-agent and migrate rebuilt and the new `speaker` container started (profile `speaker`, no
   published port); `VOICE_IDENTITY_ENABLED=true` in `.env`, thresholds unset, so nothing can be verified. Built from the clean branch
   `deploy/phase-32a-uat` (`aa3e38b`, worktree `../reachy-work-buddy-deploy-32a`, keep it for rollback or rebuild), which excludes the
   persona-default commit and the earlier uncommitted edits. Rollback images `reachy-rollback/*:pre-32a`; dumps and a Phase 48
   boundary in `~/reachy-backups/phase32a-deploy/` and `phase48-boundary-32a/` (new Phase 48 segment from 12:50:05Z; three probe turns
   of mine are listed in the record). UAT APK `~/reachy-releases/reachy-companion-0.20.0-voice-identity-aa3e38b-debug.apk` (sha256
   `fc257508…ca22`, **not installed**: no device was designated; the older `…-voice-identity-debug.apk` is superseded). Next: the owner
   installs it ([runbook](docs/verification/phase-32a-device-runbook.md)). **Calibrated 2026-10-15 15:57 UTC at the owner's acceptance of the interim GV evidence** (accept 0.50 / inconclusive 0.35, hub recreated alone; [decision](docs/verification/phase-32a-calibration-decision-2026-10-15.md); revert by removing the two lines from `.env`). Unfinished by choice: consenting second person, replay and synthetic probes, noisy and next-day clips; revisit if the app misjudges. Display-only; 32A.M, 32A.1, robot features and merging still need separate approval.

Deferred by decision: 50F federated retrieval (waits for the Phase 48 window) and the
Proxmox worker move; Phase 44 scorer research (stopped 2026-10-10) and dev16
acceptance (not frozen, not run); 44C and 44G; Phase 46 least-privilege roles (plan
only); backup phase.

Known defects, not fixed: reminders reach Telegram up to about 60 s late
(`reminder_notify_loop` sleeps before polling); `claim_due_alarms` marks an alarm fired
before delivery, so one claimed during a hub stop is lost and old alarms ring after a
long outage; core's 300 s reconcile rewrites a ready document's `updated_at`; a
recreated hub re-downloads `small.en` (about 2 minutes before voice works).

Known test failures, identical on pristine `main`: core `test_knowledge_index`
reconcile and `test_knowledge_retrieval` historical mode (both need a database; the
contention-tool tests in the same file are intermittent), hub `test_web_client::test_sample_responses_still_match_the_hub` and `test_calendar_feed_hub` upload test (both also fail on a pristine checkout of `4acc4f9`, 2026-10-15), nine Playwright specs
(notepad, planner), embodiment `test_wake.py` is timing-flaky. Do not report these
as regressions.

## Rollback assets kept (current deployment only)

Images: `reachy-rollback/companion-core:pre-deepfix`, `reachy-hub:pre-tier-tag`,
`coding-agent-service:pre-037`, `migrate:pre-037`, `document-worker:pre-034`. In
`~/reachy-backups`: the pre-037 dump
(`reachy-before-037-stop-20261015-015152.dump`), the Phase 48 boundary directories (cited
by verification records), SecretStore key copies, key-backup stamp and passphrase
file. `deploy/homelab/.env.bak-before-meeting-email` is the only `.env` backup. Older
records that say "keep the dump or tag until accepted" refer to assets deleted on
2026-10-15, except those listed here.

## Machine state

- **Disposable leftovers that may exist:** containers `spk-test-pg` (port 55435) and
  `mm-test-pg` (port 55433) (`docker rm -f`), the AVD `spk_test`. The scratch Postgres
  `aq-scratch-pg` (port 55444) is stopped.
- **Homelab:** the diarization container is the owner's standalone one, joined to
  `reachy-homelab_default` by hand (`docker network connect` again after any recreate);
  an unrelated `ovms` container runs on localhost:8000, leave it alone. vLLM
  (`reachy-local`, Qwen2.5-7B) needs the `vllm` profile passed to the launcher to survive
  a restart. The model manager token is `deploy/homelab/.env.model-manager`.
- **Nano (last reported 2026-09-27, recheck before use):** `reachy-embodiment.service` and
  `reachy-daemon-recovery.service` enabled; embodiment host-networked on 8100, daemon on
  loopback 8000; sudo needs a password, so the owner runs `systemctl` and container
  recreates; this dev box has key SSH as `Reachy-Mini-Jetson`. Use `~/reachy-venv/bin/python`
  for `voice-timing.py` (pass `--session N`). Check `df -h /` before `--build`: a full disk
  (old embodiment images) broke builds and spent the once-per-boot recovery once.
  Conversational motion switches reset to off on any embodiment restart.
- **Credentials:** hosted keys live in gitignored `deploy/homelab/.env.local`; check
  presence and ignore rules without printing values.

## Cautions

- Stage files explicitly; never `git add -A`. Do not use `git checkout -- <file>` to drop
  debug code (it reverted an uncommitted fix once). `clients/android/.kotlin/` is a build
  artefact.
- Run `ruff check .` from the repository root. From a service directory it ignores the
  repo config and reorders imports in unrelated files.
- Never print `docker compose config` (it expands secrets), and always pass
  `-p reachy-homelab --env-file .env`; a bare run once created a stray `homelab` project.
  Deploy sequence and the rule to preserve the running image by immutable ID before a
  rebuild: [deployment](docs/deployment.md#upgrades-and-verification-cleanup).
- Recreating core ends a Phase 48 evidence segment: read
  `GET /memory-candidates/capture-counters` first, stop core gracefully
  (`docker stop -t 30`) to flush shadow telemetry, and record the boundary. Never phrase a
  probe "Remember ..." (it creates a real memory). Phase 48 capture code and the Phase 44
  candidate freeze (`knowledge/answerability_b1/`, `selective/CANDIDATE_FREEZE_*.sha256`,
  `memory/candidate_*.py`, `knowledge/routing.py`) are frozen; consumed benchmark sets
  (dev8, dev10, dev12, dev14, the scorer-v3 validation) must not be tuned against.
- The blind-review answer key lives outside the repository
  (`~/.local/share/reachy-blind-review/phase-44e/`, 0600). Private case files are in
  `~/.local/share/reachy-phase48e/`. Never commit either.
- Postgres tests need a disposable pgvector container and `DATABASE_MIGRATION_TEST_URL`;
  browser tests need Playwright on `NODE_PATH`; emulator checks use a throwaway in-process
  hub, never production ([development](docs/development.md)).
- Never set `CALENDAR_FEED_ALLOW_LOCAL_FOR_TESTING` outside tests. Never `source`, print
  or trace the SearXNG secret file.
- Robot motion and daemon rules, including every owner-granted exception, are in
  [AGENTS.md](AGENTS.md); verify raw device identity before accepting a remote report.
