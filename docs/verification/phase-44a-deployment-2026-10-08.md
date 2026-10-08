# Phase 44A production deployment, 2026-10-08

Migration `025_meeting_description` to `026_source_sensitivity`, applied to the homelab following the [runbook](../deployment.md#applying-migration-026-phase-44a---runbook-prepared-and-not-executed) after the [rehearsal](phase-44a-rehearsal-2026-10-08.md). The owner authorised it on 2026-10-08 with **physical robot testing deferred**. Software deployment is complete and passed; **the robot acceptance gate is pending, not waived.** Times are Singapore time (UTC+8).

## What was deployed

Code: the pinned commit `5d64d82`. The tree at deployment was `cdf36b1`, which differs from `5d64d82` only in documentation (`git diff 5d64d82 HEAD -- shared services deploy scripts pyproject.toml uv.lock` is empty), so the images are identical to a build of the pinned commit. Rebuilt and redeployed: `migrate`, `companion-core`, `reachy-hub`, `coding-agent-service` (new images `cb4438e68a05`, `8053200d800c`, `b4942102a147`, `da55768ae7f8`). Not touched: PostgreSQL (the start-up dry run showed it as "Running", not recreated), vLLM, the model manager, the sidecars, Caddy, and the robot host.

## Timeline and downtime

| Time | Step |
|---|---|
| 11:15:09 | Preflight (below) |
| 11:15:55 | Core stopped first, then hub and coding-agent (all three stopped by 11:15:56); 0 database clients left |
| about 11:16 | Final dump taken and verified; rollback images tagged |
| 11:17:16 to 11:17:27 | Build (11 s, layer-cached, no errors) |
| 11:17:32 to 11:17:35 | Migration (exit 0) |
| 11:17:46 | `up -d` for core, hub and coding-agent (the migrate gate re-ran as a no-op) |
| 11:17:55 | Hub and core healthy |

**Downtime of core, hub and coding-agent: 2 minutes.** Web UI, Telegram, voice, alarm delivery and reminder pushes were paused for that time. No alarm or reminder fell due in it.

## Preflight (11:15)

Revision 025; no scheduled alarm or pending reminder overdue or due within 45 minutes; the one meeting complete; no non-terminal coding-agent session; model manager `ready_t1` with no transition and no error; no voice session (hub `robot-voice` session `None`); 271 GB disk free; the code between `5d64d82` and the tree identical.

## Backup and restore check

`~/reachy-backups/reachy-before-phase44a-20261008-111605.dump`, 108,068 bytes, mode 0600, sha256 `ca05111a8087f20b...`, taken after the writers were stopped (per-table counts at stop equalled the preflight counts, so nothing was written in between). `pg_restore --list` showed the tables. It was restored into a throwaway container on an internal network with no ports: revision 025 and identical counts for all 39 tables; the container and network were removed. **Finding:** `~/reachy-backups` holds no copy of the keyring files (`.env.secret-keys.json`, `.env.coding-agent-secret-key.json`). This deployment does not change them and they remain in place, but a dump cannot be used without them; keep a separate off-host copy.

## Rollback readiness

Pre-upgrade images tagged `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:025` (`cc5727d76bae`, `46f0a08e2e08`, `784875d60f3a`, `f85fb038da2c`), plus snapshots of the three stopped containers as `reachy-rollback/...:025-container` (`839c582d1327`, `d26a31d24e9d`, `d21553706dc1`). The containers' own image ids cannot be resolved by `docker image inspect` under the containerd image store; the tags are the running images by creation time (each container was created seconds after its tagged image was built), and the container snapshots are the fallback. The dump restore was rehearsed on the copy and works (see the rehearsal record). To roll back, follow the runbook's recovery section with this dump. Keep the dump and the tagged images until the owner accepts the deployment.

## Smoke tests

| # | Check | Result |
|---|---|---|
| 1 | Revision | `026_source_sensitivity` |
| 2 | Columns | `sensitivity` on the five tables, `project_scope` on `document_chunks`, `notes`, `tasks` (and the existing one on `meetings`) |
| 3 | Backfill and counts | meeting `work-private`; all 39 per-table counts identical to the at-stop snapshot, before and after the smoke tests |
| 4 | Scopes | none set on chunks, notes or tasks; the meeting's scope unchanged (none) |
| 5 | Health and logs | hub and core `ok`; zero error, exception or traceback lines in the first eight minutes of core, hub and coding-agent logs |
| 6 | Web UI | the operator UI and its scripts are served (`/hub/ui/`, 47 KB; `planner.js`, `notes.js`, `meetings.js`); authenticated API reads through the hub's bearer path return the records: 7 alarms (none scheduled), the meeting opens with 78 transcript segments and an aligned transcript, its audio serves a range request (206). A person using the browser UI is the one thing not exercised |
| 7 | Create records | a note created with no classification is `work-private`, unscoped; deleted afterwards |
| 8 | Classification | a to-do created through the hub as `sensitive` with scope `smoke` is returned as such; an edit of its text keeps both; an edit that carries `sensitivity` returns 422; an invalid value returns 422; deleted afterwards |
| 9 | Chat | core `/conversation` answers `/help` (public, 925 characters); the local model is still served (`reachy-local`). A model-backed turn was deliberately not sent, to keep the shadow-router trial data and the owner's session unchanged |
| 10 | Telegram | polling healthy (last poll seconds earlier, no error); a reminder due in two minutes was claimed by the notify loop 18 s after it fell due. **Receipt of the push in Telegram needs the owner's confirmation** |
| 11 | Robot connectivity (no motion) | `nano-1` is **offline**: the hub reports it unavailable, and the Nano's embodiment service does not answer on its tailnet address (the host answers ping, port 8100 gives no HTTP response). Nothing was sent to the robot. This is not something the hub restart can cause; the robot reconnects on its own when its service is up. **Pending the physical gate** |
| 12 | Voice API | hub text-to-speech returns a WAV (62 KB); the voice-state API reports no session; the speech-to-text model is present in the hub's cache (no re-download). No transcription was run |
| 13 | Continuity | no alarm or reminder fell due during the downtime: 0 alarms fired, 0 reminders notified (other than the smoke reminder), 0 alarms scheduled-and-overdue. No missed alarms or reminders |

All smoke-test records were removed (tasks, notes and reminders are 0 again). The rehearsal and verification containers are gone.

## Acceptance

- **Software deployment: complete, passed and accepted by the owner (2026-10-08)**: revision 026, counts identical, no errors, classification working through core and hub.
- **Telegram:** the owner confirmed the test reminder arrived.
- **Pending, not waived:** physical robot connectivity, movement and voice (the robot was offline during the deployment); a browser pass through the web UI.
- Phase 44B was approved to start after this acceptance. Knowledge retrieval is not enabled.
