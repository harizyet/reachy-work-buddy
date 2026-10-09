# Handover

Current session snapshot: 2026-10-08. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) owns deployment limits and open acceptance.

## Current work

### State at 2026-10-08

- **Repository:** `main` at `c4cc7a8` (code) was pushed with a clean tree; the documentation sweep that follows it is committed on top. Earlier entries below the
  next heading date from before this session and may describe state that has since been committed or deployed.
- **Homelab (compose project `reachy-homelab`):** core, hub and coding-agent rebuilt and running after the last deploy; database at revision
  `025_meeting_description`; vLLM (Qwen2.5-7B) healthy; the model manager is still the host process; nothing on the robot host changed.
  Backups of every upgrade are in `~/reachy-backups` (names in the [evidence record](docs/verification/clients-meetings-alarms-2026-10-07.md)).
- **Android:** version 0.15.1 (local, uncommitted: full-screen voice mode with an animated ball, `ui/VoiceModeScreen.kt`; JVM tests and the debug build pass, replies now stream from the new hub route `POST /speech/stream` (hub tests with a fake voice pass; real Piper and the real phone not exercised, hub not rebuilt or deployed, no schema change); **not yet seen on an emulator or phone**; no Info/Share/Change-voice buttons because the hub has no voice selection; an on-phone neural voice was considered and declined, the fallback is the phone's built-in voice). 0.14.0 is the last delivered APK (debug builds delivered by hand, not stored in the repo). Verified on an emulator only.

### Delivered 2026-10-07 to 2026-10-08

| What | Canonical documentation |
|---|---|
| Meeting alignment, silent-recording check and flags, recording playback with click-a-line and per-line edit, automatic titles and descriptions, longer summaries and minutes | [Phase 27](docs/phase-27.md), [41](docs/phase-41.md), [43](docs/phase-43.md), [services reference](docs/reference/services.md), [operator guide](docs/operator-guide.md) |
| Alarm clock screens (repeat days, on/off) and the phone backup alarm (the app rings when Reachy is offline, finds nobody or fails) | [Phase 38](docs/phase-38.md), [ADR 0027 addenda](docs/adr/0027-alarms-and-presence-gated-delivery.md) |
| Android: Alarms, Notes, Reminders (Apple-style), Pixel Fold layouts, Reachy-voice replies read once, chat history with delete | [Phase 40](docs/phase-40.md), [ADR 0029 addendum](docs/adr/0029-android-companion-app.md), [Android README](clients/android/README.md) |
| Web: Apple-style Notes, To Do and Reminders, Alarms; delete saved chats; meeting speaker chips, player, line edit, title edit | [operator guide](docs/operator-guide.md) |
| Hub routes: `/speech`, `/meetings/{id}/audio`, `PUT /meetings/{id}/title`, `POST /meetings/{id}/describe`, `PATCH /planner/alarms/{id}`, `DELETE /chats/{id}`; alarm creation by clock time; wake-phrase acknowledgement mid-conversation | [services reference](docs/reference/services.md), [operator guide](docs/operator-guide.md) |
| Migrations 022 to 025 | [deployment](docs/deployment.md#schema-upgrades-and-credential-keys) |

### Phase 44 (44A closed for development, 2026-10-08)

[docs/phase-44.md](docs/phase-44.md) holds decisions D1 to D11, the 44A acceptance table and readiness assessment; evidence is in [the verification record](docs/verification/phase-44a-2026-10-08.md) and the [case-level review of the 44 holdout cases](docs/verification/phase-44a-holdout-case-review-2026-10-08.md). **Committed and pushed:** `bdc9efd` (44A), `0c146f0` (voice test fixture), `5d64d82` (runbook and closure), `cdf36b1` (rehearsal record, debt note). **Deployed to the homelab 2026-10-08 11:15 to 11:18 SGT** from the pinned code `5d64d82` (docs-only difference): database at `026_source_sensitivity`, core, hub and coding-agent rebuilt, 2 minutes of downtime, 13 smoke checks passed ([record](docs/verification/phase-44a-deployment-2026-10-08.md)). Backup `~/reachy-backups/reachy-before-phase44a-20261008-111605.dump`; rollback images `reachy-rollback/*:025` (and `*:025-container`); keep both until the owner accepts the deployment. The owner **accepted the software deployment** and confirmed the Telegram test reminder arrived. **Pending, not waived:** the robot acceptance (the Nano's embodiment service did not answer on its tailnet address during the deployment, so `nano-1` is offline and nothing was tested on it) and a browser pass through the web UI. A separate off-host copy of the keyring files (`.env.secret-keys.json`, `.env.coding-agent-secret-key.json`) is advisable; none is in `~/reachy-backups`. Phase 44B was approved to start on 2026-10-08.

Benchmark: the frozen holdout was scored once per track (`44A-baseline` synthetic, `44A-production-embedding-baseline` real MiniLM); both recorded and logged, nothing tuned on them. The labels are **provisionally reviewed, pending the owner's independent inspection**, and the corpus is synthetic, so the figures are not evidence of real-world retrieval quality. Real MiniLM raised today's document recall (recall@5 0.16 to 0.25, intervals overlapping) while nearly tripling unauthorized exposed hits (11 to 30): relevance and access control must be judged separately.

**Next decision (owner):** accept the software deployment (leaving the robot gate open), then start 44B. 44B needs approval, and retrieval-time source revalidation is non-negotiable for it; 44E must add action-boundary probes for every new path that puts retrieved text in a prompt. No UI control for classification exists yet.

Tests (disposable `pgvector/pgvector:pg16` container, removed afterwards): final state `pytest services shared` 1567 passed, 22 skipped, 1 failed (hub `test_spoken_command_text_does_not_actuate_the_robot`, known, reproduces on the clean base). Embodiment `test_wake.py` is timing-flaky on every tree tried. `jsonschema` was installed into `.venv` with `uv pip`, not `uv sync`.

### Phase 44B (built 2026-10-08, committed and pushed; migration 027 DEPLOYED 2026-10-08 13:20 with indexing off)

The unified index, transactional outbox (filled by database triggers), indexing worker, reconciliation and retrieval-time revalidation: [phase record](docs/phase-44.md#11b-44b-unified-index-outbox-and-revalidation-2026-10-08), [verification](docs/verification/phase-44b-2026-10-08.md), and the [rehearsal and readiness record](docs/verification/phase-44b-rehearsal-2026-10-08.md). Commit `a6e1979` (message "Add comprehensive tests for migration 027 on Postgres", made from the shared checkout) contains all of 44B; `57713c6` is the security fix (failures never copy indexed content into the outbox or logs). **Deployed 2026-10-08 13:19 to 13:21 SGT** from pinned commit `5f7f3ab` (images built from a clean worktree): the live database is at `027_knowledge_index`, `KNOWLEDGE_INDEXING_ENABLED=false` (index empty, one outbox row for the existing meeting), about 77 s downtime, smoke tests passed ([record](docs/verification/phase-44b-deployment-2026-10-08.md)). Backup `~/reachy-backups/reachy-before-phase44b-20261008-131937.dump`; rollback images `reachy-rollback/*:026` and `*:026-container`; keep until the owner accepts. Robot acceptance, a browser pass and Telegram receipt of the smoke reminder are pending, and the keyring still has no off-host copy. Rehearsed on a restored production copy: migration 1.75 s, trigger overhead 0.2 to 0.4 ms per write, about 4.5 KB of index per part, rollback in 0.09 s (`deploy/homelab/rollback-027.sql`; run it before restoring an older dump), every real write path checked. `KNOWLEDGE_INDEXING_ENABLED` stays `false` in production until separately approved. The bounded contention test was **run 2026-10-08 13:34** (real worker, MiniLM, small.en Whisper, vLLM chat; no abort): chat +10%, speech p95 +28%, indexer 30.6 items/s beside the foreground vs 71.5 alone, recovered to baseline, no extra CPU or memory limit needed at 2 embed threads ([result](docs/verification/phase-44b-contention-result-2026-10-08.md)). A supervised indexing trial the same day built the whole backfill (80 rows for the one meeting; validated read-only against the source; revalidation controls verified on the live index) and was reverted early when it hit the Postgres connection limit: **the flag is `false`, the 80 index rows remain, retrieval is off** ([trial record](docs/verification/phase-44b-indexing-trial-2026-10-08.md)). Plans only, for review: [44E](docs/phase-44e-plan.md) and the 44F candidate/review memory capture in phase-44 section 3.1; no 44E or 44F code. Not done: 44D retrieval (local development authorised, benchmarked on the dev split only; the frozen holdout is not to be rerun until a candidate and decision point are approved), the context builder (44E).

**Shared checkout:** another session is working in this tree (Android voice mode, hub `/speech/stream`) and its uncommitted edits sit beside mine; it once committed and pushed my uncommitted 44B work in one commit. Stage files explicitly (never `git add -A`) and commit promptly.

### Phase 44D (local development authorised 2026-10-08; benchmarked on the development split only)

Three retrieval configurations over the 44B index, each ending in retrieval-time revalidation under the trusted `AccessContext`: B1a lexical (PostgreSQL full-text), B1b lexical + pgvector fused by reciprocal rank, B1c with a cross-encoder rerank of the authorised survivors. Code in `companion_core/knowledge/search.py` and `retrieval.py`, benchmark adapters in `benchmarks/knowledge_retrieval/kbench/b1.py`; comparison in [the 44D record](docs/verification/phase-44d-dev-2026-10-08.md). On the dev split B1a reaches R@5 0.86 (MRR 0.66, 8 ms median), B1b R@5 0.79 (MRR 0.80, 28 ms, several times the CPU and memory), B1c is not justified; **no variant exposed anything unauthorised** (with the pre-filter off, revalidation alone dropped every proposed row). Nothing is wired into a route, the conversation or a flag. **Frozen holdout, decision point `44D-first-look` (owner decision D12, frozen at `0117c6e` before scoring, B1a and B1b scored once each, B1c excluded):** R@5 0.83 and 0.86 against 0.84 for keyword overlap over everything and 0.25 for today's lookups, **zero exposure** for both (the baselines expose 104 and 30), B1b's MRR +0.076 over B1a (interval just excluding zero), nothing else separating them; relationship is the weak category; [record](docs/verification/phase-44d-first-look-2026-10-08.md). The harness still refuses any other B1 holdout run until a new decision point is approved (`KBENCH_HOLDOUT_APPROVAL`). Answer quality is not evaluated. Not started: entities, extraction, production activation, the context builder (44E).

### Phase 47 React web platform and Brain visualization (47A to 47D and 47F merged and deployed 2026-10-08)

[docs/phase-47.md](docs/phase-47.md): owner decisions D1 to D6, the migration matrix, the 47A record (section 13) and the 47B record (section 14: parity table, deliberate differences, known limits). Evidence: [47A](docs/verification/phase-47a-2026-10-08.md), [47B](docs/verification/phase-47b-2026-10-08.md). The whole legacy operator UI is rebuilt in `clients/web` (React, TypeScript, Vite, HashRouter) and served by the hub at `/web/`; `/app/` is unchanged. The hub image builds it in a digest-pinned Node stage (no Node in the runtime). Not migrated: Call Reachy/telepresence (`clients/web-pwa`, decision D5); not built: memory and document screens (backend gaps in section 7a). The worktree `../reachy-work-buddy-47a` is the working area for Phase 47; run `npm ci` in `clients/web` after a fresh checkout. **47C** (3D Brain), **47D** (real records through a read-only owner-only Brain API in core and hub, plus a bloom toggle in Settings > Display) and **47F** (the legacy `/ui/` retired) are merged to main and **deployed to the homelab 2026-10-08** ([47D deployment](docs/verification/phase-47d-deployment-2026-10-08.md), [47F](docs/verification/phase-47f-2026-10-08.md)); the owner confirmed the React client works. `/web/` (Caddy `/hub/web/`) is the operator UI; `/ui/` redirects to it and the old files are the `/ui-legacy/` rollback; Google sign-in returns to `#/settings/accounts` (the live round trip is not yet exercised). Call Reachy stays at `/app/`. Rollback images `reachy-rollback/*:027-pre47d`, dump `~/reachy-backups/reachy-before-phase47d-20261008-220617.dump`. Pre-existing unrelated test failures: core `test_knowledge_index` reconcile, hub `test_robot_voice` spoken-command. **Next, needs approval:** 47E (relationships) depends on Phase 44C/44F decisions; deleting `clients/operator-ui` after a settled period; memory/document screens need backend work (phase-47 section 7a).

### Open, unverified or worth watching

- **Phase 45 (database connections) is deployed and accepted at the infrastructure level (2026-10-08).** Core, hub and coding-agent each use one shared pool and reach PostgreSQL through PgBouncer 1.25.2 (transaction pooling; `.env` has `DB_HOST=pgbouncer`, `DB_PORT=6432`, `DB_PREPARE_THRESHOLD=off`); migrations and recovery stay direct. 8 backends at rest (was 98), 19 at 32 concurrent workers, 73 s downtime ([record](docs/verification/phase-45e-deployment-2026-10-08.md), [Phase 45](docs/phase-45.md)). Rollback: remove those three `.env` lines and `up -d --no-build --no-deps` the three applications; images `reachy-rollback/*:027-pre45`, dump `~/reachy-backups/reachy-before-phase45e-20261008-154338.dump`; do not roll back merely because the open items below are pending. Encrypted key backup at `USB Storage/reachy-keys/` (accepted by the owner as sufficient). **Telegram reminder delivery confirmed by the owner (2026-10-08, the Phase 45E smoke reminder arrived).** **Still open (not waived):** browser UI interaction, voice integration, physical robot testing. **Availability observation:** a PgBouncer restart interrupts for up to about 10 s (one call took 7.4 s; no errors, no loss or duplicates) because it waits for pooled clients on SIGTERM until Docker kills it; options to test are in the record. **Next, priority:** [Phase 46](docs/phase-46.md), least-privilege roles (plan only; no credential changes or deployment yet). **Separate plan:** persistent hub speech-model cache ([Phase 45 section 11](docs/phase-45.md#11-follow-up-persistent-speech-model-cache-for-the-hub-plan-not-started), not started). **Phase 44 resumed 2026-10-08 (evening):** the supervised indexing re-trial passed ([record](docs/verification/phase-44b-indexing-retrial-2026-10-08.md), pushed `8ded707`) for connection stability, PgBouncer behaviour, source consistency and access filtering under an idle indexer; the flag is `false`, and a **production indexing-workload gate stays open** (real MiniLM and the outbox claim/lease/complete path unexercised; never satisfy it by hand-inserting outbox rows). **Phase 44E local development is done up to its gate (2026-10-09, commits `ac74604`, `adb2f8d`, local until pushed):** `knowledge/context.py` (builder) and `benchmarks/answer_quality/` (68 cases, 6 conditions, scratch Postgres `aq-scratch-pg` on 127.0.0.1:55444 started by hand, stop it with `docker stop aq-scratch-pg`); results in [the development record](docs/verification/phase-44e-development-2026-10-09.md) (retrieval 21 to 22 of 25 full-correct vs 1 with none and 3 with Phase 43; fabrication 0 of 10 vs 3; B1a and B1b not separable; zero leaks; one planted-instruction case swayed the 7B's reasoning). **The single `44E-first-look` holdout scoring was run and is spent (2026-10-09):** [report](docs/verification/phase-44e-first-look-2026-10-09.md) (full-correct of 25: none 1, Phase 43 4, B1a 18, B1b 19, oracle 23; B1a vs B1b not separable, p = 1.0; zero leaks into any prompt, no action taken on injected text; losses are generic status/relationship retrieval and attached-meeting questions, where Phase 43 wins). Recommendation: B1a may go to measure-only shadow mode if the owner wants it (a cost tie-break, not a quality finding); B1b not; neither activated. **Follow-up development 2026-10-09 (local, not deployed):** B1a provisionally selected for future measure-only shadow (tie-break only); built deterministic status routing (`knowledge/routing.py`, tasks/reminders from the stores; Phase 43 attached-meeting path kept), a disabled-by-default measure-only shadow (`knowledge/shadow.py`, `KNOWLEDGE_SHADOW_ENABLED`, numbers-only telemetry, bounded, reversible), scorer v2 with first-look annotations (originals untouched), a 21-answer blind review package (`benchmarks/answer_quality/blind_review/phase-44e`, **the owner's review is pending; do not open the KEY file first**), 12 live-route security regression tests, and 22 new dev cases; results in [the follow-up record](docs/verification/phase-44e-followup-2026-10-09.md) (routing 11 to 12 of 14 vs 5 full-correct, p = 0.016; stricter header and conflict hint gave no net gain; unsupported inference still unsolved; shadow job p50 7 ms, p95 17 ms). A scratch Postgres `aq-scratch-pg` may be stopped. **2026-10-10 (local, shadow NOT approved for production):** qualification (`knowledge/qualify.py`), aggregate-only telemetry with a reconciled funnel and 30-day retention (`knowledge/shadow_telemetry.py`), shadow lifecycle (`start`/`stop`), a constant restricted-channel reply, 7 production-lifespan integration tests on a disposable Postgres (`DATABASE_MIGRATION_TEST_URL`), a real-model live-route security run, a claim-verification experiment (no usable gate; conflict warning promising), and a sealed blind-review workflow whose key is gitignored (only `KEY.sha256` is committed) — record: [shadow readiness](docs/verification/phase-44e-shadow-readiness-2026-10-10.md). **The pushed commit is `22d408d`** (the two approved commits rebuilt as one to keep the key out of git). **2026-10-10 (later):** the supervised production indexing-workload trial was APPROVED and is PREPARED, NOT RUN: [plan and runbook](docs/verification/phase-44b-indexing-workload-trial-plan-2026-10-10.md), tooling `tools/knowledge_indexing_trial.py` (read-only preflight, monitor with abort gates, 4 Hz outbox watch, verify) and `tools/knowledge_index_validate.py`; it needs the owner present and a pre-trial dump (`reachy-before-phase44e-indexing-trial-*.dump`, not yet taken). The blind-review answer key now lives OUTSIDE the repository at `~/.local/share/reachy-blind-review/phase-44e/` (0600; `KEY.sha256` committed as a seal). Shadow telemetry retention default is 30 days (owner). Local conflict-omission detector findings: [record](docs/verification/phase-44e-conflict-detector-2026-10-10.md) (v2 precision 1.00 recall 0.43; not a gate). [Phase 44H](docs/phase-44h.md) holds regression case H-001 (false robot-standby claim) and the receipt-boundary investigation (no reply-path code). **Receipt-boundary architecture proposal (for review, no code):** [phase-44h-receipt-boundary-proposal.md](docs/phase-44h-receipt-boundary-proposal.md). `da07f33` is pushed. **The supervised production indexing-workload trial was RUN on 2026-10-09 and PASSED** ([record](docs/verification/phase-44b-indexing-workload-trial-2026-10-09.md)): one genuine owner note (written through the Android client; the trigger itself verified indirectly from timestamps) was claimed, leased (13.2 s including the cold MiniLM load, +516 MB), embedded and indexed; index 81 rows consistent with the stores; no abort condition from the work; flag restored to `false` and recovery clean. **Accepted by the owner 2026-10-10; the basic Phase 44B production indexing-workload gate is CLOSED** (no permission for continuous indexing, retrieval or shadow). The production index now holds the owner's note row (81 rows, to be preserved); retrieval, shadow and permanent indexing remain off. Pre-trial dump: `~/reachy-backups/reachy-before-phase44e-indexing-trial-20261009-1015.dump`. **Pending outbox (account for it at the next authorised indexing activation):** a second genuine owner note produced one outbox row (`note`, generation 30 from repeated edits, 0 attempts, not failed, enqueued 2026-10-09 02:42:52 UTC) while indexing is off; the worker will claim it when indexing is next enabled. Do not insert, delete or edit outbox rows by hand. Follow-ups: offline model-cache [proposal](docs/phase-44-model-cache-proposal.md) (design only; vector equivalence of the pinned revision to the 81 stored vectors verified read-only, max difference 1.2e-7, so no re-embed or relabel is needed to pin it; nothing changed in production); monitor-tool regression tests added (`test_knowledge_indexing_trial_tool.py`); the **21-answer blind-review package is ready for the owner, who has not rated yet (the ratings template is empty); when the ratings arrive run `blind_compare.py` and report agreement, correctness, unsupported claims and fabricated actions, B1a/B1b/oracle differences and cases to investigate; do not reveal conditions or scores before then** (`benchmarks/answer_quality/blind_review/phase-44e/`, instructions in its README; the key is sealed outside the repository, verified by `test_blind_review_workflow.py`). Conflict detector v2/v3: kept as experiments, further implementation deferred. **Remaining 44E gates:** owner blind review, real-world qualification precision check, 44H security review (receipt-boundary proposal pending architectural review), separate authorization for any shadow deployment; the production indexing-workload gate is CLOSED by the trial above. 44F not started. 44F selection mechanisms are proposed in [phase-44 section 3.1a](docs/phase-44.md#31a-44f-candidate-selection-mechanisms-proposed-2026-10-08-plan-only-evaluated-before-any-use) (plan only).
- **Reminder delivery lateness (reliability issue, recorded 2026-10-08, not fixed).** A planner reminder reaches Telegram up to about 60 s after it is due, and after a hub restart the first check comes a minute after start. `reminder_notify_loop` in `reachy_hub/app.py` sleeps first, then polls core every `coding_agent_notify_interval` (60 s). The smoke reminder in the 027 deployment was claimed 57 s late for exactly that reason (hub started :41, reminder due :47, next poll :41). Reminders due during a hub restart are still claimed and delivered late, with no staleness cutoff. Alarms are polled every 5 s and are not affected. Not a regression and not part of Phase 44. A fix would be its own small change (a shorter reminder poll, or a poll right at start); it was deliberately not started here.
- **Alarm delivery gap (technical debt, found 2026-10-08, deliberately not fixed in 44A).** `claim_due_alarms` marks an alarm fired before the hub delivers it, and there is no staleness cutoff. An alarm claimed but not yet delivered when the hub stops is lost, and after a long outage old alarms ring at restart. Deployments avoid it by timing (nothing due within 45 minutes, core stopped before hub); a real fix is a separate change to the delivery semantics (claim with a lease, then confirm; skip or label alarms that are hours late).

- **Spoken replies on the owner's phone.** After app 0.12.1 the owner reported replies not playing at all. It could not be reproduced (emulator: reply detected, voice fetched, playback started;
  production Piper works). Version 0.12.2 hardened playback (audio focus, fallback to the phone voice, recogniser released). Ask the owner whether it was the typed or mic path, whether any voice is heard, and the media volume.
- **Silent recordings.** The one real recording is two thirds silent; the old build without a foreground service is the likely cause but this is unconfirmed on the current build. Test: record five minutes with the screen locked and look for the yellow warning.
- **Phone alarm** has only run on an emulator. Needs a physical test with a real "robot unavailable" and "nobody detected" outcome and Doze. Alarms set elsewhere reach the phone within about 15 minutes.
- **Alarm time zone:** the server reads clock times in the assistant's (persona) time zone; the screens show the device's. Keep them the same.
- **Summaries and minutes** were lengthened but not rerun on the real 7B; a deep-tier run on the GPU is unverified. Reminders cannot be reopened (no hub route).
- **Not exercised against production:** the web UI (no owner session in development) and the app on a physical phone or Fold.
- **Failing before this work, still failing:** hub `test_spoken_command_text_does_not_actuate_the_robot`, the browser fixture "Hey Reachy" label test (`voice.test.cjs`); embodiment `test_wake.py` is timing-flaky.

### Cautions for the next session

- Run `ruff check .` from the repository root (running it inside a service directory, or with a relative `..` path from one, reformats unrelated files: it rewrote the imports of 194 files once on 2026-10-09; they were restored with `git restore` after checking the diffs were import order only).
- Never print `docker compose config`: it expands secrets (a token was rotated once for this). Deploy with `SEARXNG_SECRET_KEY` read from `deploy/homelab/.env.searxng-secret` and the sequence in
  [deployment](docs/deployment.md): dump, stop core, hub and coding-agent, build `migrate` with them, run `migrate ... upgrade --adopt-legacy`, `up -d`. The owner approves each deploy and each commit.
- Postgres tests need a disposable pgvector container and `DATABASE_MIGRATION_TEST_URL`; browser tests need Playwright on `NODE_PATH`. Emulator checks use a throwaway in-process hub, never production. None of these helper scripts are in the repository.
- Do not use `git checkout -- <file>` to drop debug code: it reverted an uncommitted fix once (re-applied).
- Core now depends on PyAV (`av`, decodes recordings for the silence check); `uv.lock` was updated.

### Earlier entries (before 2026-10-07)

**Phase 38 alarm clock + presence-gated delivery (started 2026-10-05, uncommitted):** docs done ([phase-38](docs/phase-38.md), [ADR 0027](docs/adr/0027-alarms-and-presence-gated-delivery.md), roadmap row). 38.1 core alarm domain implemented: `Alarm` model, in-memory/Postgres methods on `PlannerStore`, migration `015_alarms`, `SCHEMA_REVISION` bumped, routes `/alarms*` in core, tests in `test_planner.py` (core suite green, ruff clean). 38.2 occupancy sweep implemented and tested against simulation (embodiment `/sweep*`, `MotionController.sweep_to/sweep_home`, hub `occupancy.py` with MediaPipe face detector, hub Dockerfile pins the model, `PRESENCE_SWEEP_ENABLED` default off; real-model test via `FACE_MODEL_PATH`, optional `FACE_PHOTO`; never run on the real robot, face detection untested on real camera frames). 38.3 implemented: core stations (table in migration 015), hub `alarm_audio.py` (TuneIn search/resolve, SSRF guard with residual DNS-rebind risk noted in the module, PyAV chunked decode, chime, chunk playback), embodiment `/audio/stop`; live TuneIn+decode verified with SWR3, no robot playback. 38.4 implemented: hub `alarm_delivery.py` + `alarm_loop`/`alarm_tick` in `app.py` (order privacy=no wake arm, robot unavailable, DND/meeting, sweep; Telegram fallback with reason; outcome recorded; linked-reminder dedupe), `AlarmDeliverer.stop()` exists but no route yet; tests `test_alarm_delivery.py`, `test_alarm_loop.py`. 38.5 implemented: core `alarm_intent.py`, `/alarm` and `/alarms` commands (shared/protocols/commands.py, Telegram menu), weekday parsing in `reminder_time.split_reminder_when`, in-memory session-scoped reminder->alarm offer in `process_conversation_turn`; tests in `test_planner.py`. Not yet: 38.4 live check (sweep sentence kept for context: owner asked 2026-10-05 for a room sweep rather than one forward frame; sweep idea: owner asked 2026-10-05 for a room sweep rather than one forward frame, recorded in ADR 0027 and gated by owner approval for unattended production motion), UI tab and stop route are done (38.6, `alarms.test.cjs`; fixture whitelists in the other operator-ui tests were stale and were fixed; `voice.test.cjs` 'Hey Reachy' toggle label assertion fails and is unrelated). Migration 015 and the core/hub/coding-agent images were deployed 2026-10-05 (backup taken, schema verified, Postgres durability test passes); Live 2026-10-05: Telegram alarm, sweep (embodiment now on by default, head yaw follows body), station matching, 5 s hub alarm poll interval, and an incremental PyAV stream decoder in `alarm_audio.py` (uncommitted; hub redeploy needed). Still owed (38.7): re-run in-room `/alarm class 95 fm in 2 minutes` for full-length playback plus Stop, and an empty-room Telegram fallback. Unattended per AGENTS.md alarm exception. Per-alarm volume (migration `016_alarm_volume`, Volume slider in the Alarms tab, gain applied in the hub) is implemented and tested but uncommitted and undeployed: needs the backup/migrate/rebuild procedure for core, migrate and hub. Reply tone preset (migration `017_persona_tone`, Tone select on the persona card, one style-only system message in core) is implemented and tested, uncommitted and undeployed; deploy together with 016. Phase 39 (receipts + persona templates, uncommitted; 016-018 deployed to the homelab 2026-10-06): [phase-39](docs/phase-39.md), [ADR 0028](docs/adr/0028-persona-responses-and-action-receipts.md); stages 39.0-39.2, 39.4-39.6 done (migration 018, core `/receipts*`, `persona/render.py`, hub `receipt_notify_loop`, Activity tab); 39.3 verbalizer, 39.7, 39.8 not started, 39.9 acceptance pending; deploy together with 016/017. Phase 40 Android app (uncommitted): [phase-40](docs/phase-40.md), [ADR 0029](docs/adr/0029-android-companion-app.md), `clients/android` builds and its 7 JVM tests pass; sign-in, chat-created task, To-do/Notes/Meetings tabs and record+upload verified in an emulator against a throwaway in-memory hub; mic/TTS and a real phone not verified. SDK and JDK were installed under ~/Android (not on PATH). Also fixed this session: the hub operator proxy dropped the alarm `volume` field (`PlannerAlarmBody`); the fix is uncommitted and the hub needs a rebuild to take effect. Phase 41 meeting speaker names + LLM correction suggestions (uncommitted; migration 019, core and hub deployed 2026-10-07, which also deployed the alarm volume proxy fix): [phase-41](docs/phase-41.md), [ADR 0030](docs/adr/0030-meeting-speaker-names-and-reviewed-corrections.md); core migration 019, routes, hub proxies, Android UI done and tested (core, hub, Postgres, 16 Android JVM tests, emulator run with a stubbed model); needs migrate/core/hub rebuild; suggestion quality on a real recording unjudged; web panel does not show names yet. NOTE: running `ruff --fix` from services/companion-core ignores the repo config and reorders imports in every test file; run ruff from the repo root. Phase 41 key terms (migration 020, deployed 2026-10-07 with core and hub; app 0.3.0): global glossary + per-meeting terms + attendees as vocabulary, candidate generation then a model that only chooses; benchmark in services/companion-core/benchmarks/meeting_corrections and docs/verification/meeting-corrections-benchmark-2026-10-07.md. Production vLLM was stopped for model tests and restored with scripts/start-vllm.sh (Qwen2.5-7B, unchanged). On the real recording the production 7B still misses germanite->Gemini (Qwen3-14B-AWQ and batched Gemma-4-12B find it); changing the production local model is undecided. Phase 42 three-tier model escalation (docs + ADR 0031 proposed; Phase 42A swap benchmark measured, nothing built): 7B to 14B to 7B round trip is about 3.5 min, 14B ready in ~115 s, 7B restore ~81 s; manager prototype (42B) is next and not started. Phase 42B/42C (uncommitted): model manager `services/model-manager` (host process, stable `reachy-local` identity, retry-then-fallback recovery, 54 tests, acceptance on real hardware in docs/phase-42.md) and Deep local review in core/hub/Android/web (Reachy unavailable warning, banner, app notification, Telegram notices via receipts). Production vLLM now serves `reachy-local` and core local model = reachy-local. The manager is started by hand (`scripts/start-model-manager.sh --bridge`) and NOT supervised; its token is deploy/homelab/.env.model-manager (rotated once because compose config printed it). Phase 43 (uncommitted; migration 021 and core/hub deployed 2026-10-07; app 0.4.0): delete meetings, summary/minutes with tier labels and rerun on deep/cloud, meeting as chat context with deterministic web search for outward-looking questions and clickable citations (web + Android). docs/phase-43.md. Not run for real: a deep summary/minutes and the web UI against production. Open design: hub-side PyAV chunking to `/audio/play`, hub-side camera person detection, weekday parsing, pending-offer state.

**Real-meeting end-to-end test (2026-10-05, uncommitted):** `services/reachy-hub/tests/test_meeting_real_audio.py`, opt-in via `MEETING_REAL_AUDIO` (+ `TRANSCRIPTION_URL`, `DIARIZATION_URL`). Real: the owner's private recording `test/StarHub Green.m4a` (git-ignored via `test/`; never commit it), hub upload chain, core worker, HTTP clients, transcription sidecar. In-memory: the meeting store. First run found that the diarization sidecar rejected `.m4a` (soundfile only); fixed by a PyAV fallback decode in `deploy/homelab/diarization/app/server.py` (+ `av==14.0.1` in its Dockerfile, unit test in `deploy/homelab/tests/test_speech_uploads.py`). **Deployed 2026-10-05:** the owner's standalone `diarization` container was rebuilt from the repo Dockerfile/app (built in `/home/hariz/inferencing/diarization`, previous sources in `~/reachy-backups/diarization-standalone-before-m4a-*`, previous image tagged `nemotron-diarization-ov:before-m4a`), recreated with `docker compose up -d --no-build` and re-attached with `docker network connect reachy-homelab_default diarization` (do this after every recreate). It now also carries the repo's busy-admission and optional service-token code. Real recording through the live sidecars (iGPU): 1419 s audio, 203 s wall (RTF 0.14), 349 transcript segments, 3718 words, 602 turns, 4 speakers, ends at ALIGNING. Core/hub were not changed or rebuilt. Alignment quality and content correctness were not judged.

**vLLM local model (2026-10-05; RUNNING and ACTIVE, core redeployed with the local spoken-reply token cap raised 100 to 300):** compose service `vllm` (profile `vllm`, container `reachy-homelab-vllm-1`, `Qwen/Qwen2.5-7B-Instruct-AWQ`, ~13.5 GiB VRAM), `scripts/start-vllm.sh`, `--vllm` in start-homelab.sh; see deployment "vLLM on the NVIDIA GPU". The owner repointed the `local` provider in Settings to `http://vllm:8000/v1`; one real turn from core (172.18.0.9) was served by vLLM with 200 OK (checked in the vLLM log). The previous OVMS URL/model were not recorded by me; hosted fallback unchanged. Not verified: reply quality, spoken-turn latency, the Reachy-specific bakeoff, behaviour after a host reboot (the `vllm` profile must be passed to start-homelab.sh to keep it). vllm-bench shares the GPU, so do not run it while this is up. The `ORT_THREADS` compose edit in the same file belongs to another session.

**To-do, reminders and notes tab (2026-10-04, uncommitted, DEPLOYED to the homelab 2026-10-04 incl. migration 014_planner and a coding-agent-service rebuild, pre-deploy dump in ~/reachy-backups; owner browser test pending):** operator-UI tab `planner.js`, hub `/planner/*` owner proxies plus a `reminder_notify_loop` (Telegram push, claim-once from core `/reminders/due`), core `/notes`, `/reminders` and task edit/reopen/delete routes, migration `014_planner` (SCHEMA_REVISION bumped, so deploy needs backup, stop writers, migrate, rebuild migrate/core/hub together; see deployment). Verified: ruff, full core/hub pytest (one failure, `test_robot_voice::test_spoken_command_text_does_not_actuate_the_robot`, also fails without these changes), the Postgres store and migration against a disposable pgvector container. Not verified: the tab in a browser (no playwright here, `node --check` only) and a real Telegram reminder push. The hub reuses `run_coding_agent_notify_task`/interval for the reminder loop. "remind me to X at 4pm" now also creates a reminder (core `reminder_time.py`, persona timezone; core tests pass; NOT yet deployed, needs a core rebuild). Phase 30.3 calibration is still paused until the owner says concurrent work has ended.

**Shadow semantic router (2026-10-05; pipeline committed in ff31d01, the trial tooling, sidecar compose service and docs are uncommitted; TRIAL ENABLED 2026-10-05 ~23:59 local, production behaviour unchanged):**
a router -> few-shot extractor -> deterministic validator that only records what it would propose after each reply is final. Contract, evidence and trial procedure:
[docs/shadow-router.md](docs/shadow-router.md); stages and gates: [Phase 37](docs/phase-37.md) (added to the [forward roadmap](docs/plan.md#forward-roadmap-phases-30)); decision and eventual rearchitecture: [ADR 0026](docs/adr/0026-semantic-routing-and-argument-validation.md) (shadow accepted, promotion proposed, each stage a separate owner decision). Code: `services/companion-core/src/companion_core/shadow_router/` (validator, extractor, pipeline),
`production_handler` labels plus one wrapped background submit in `app.py`, tests in `tests/test_shadow_router.py` (30). Sidecar: `deploy/homelab/semantic-router/`
(compose profile `shadow-router`, `scripts/start-homelab.sh --shadow-router`, internal port 8012, CPU cap 6 with 2 ONNX threads per model, models mounted from `semantic-router/models`, git-ignored; that path
is a symlink to `/home/hariz/inferencing/router/models` on this host). Tools: `tools/shadow_router_report.py`, `tools/shadow_router_grade.py` (blind sheet, report, purge).
- **Flags** (compose defaults off): `SHADOW_ROUTER_ENABLED`, `SHADOW_ROUTER_URL` (default `http://semantic-router:8012`), `SHADOW_ROUTER_LOG_PATH`, `SHADOW_ROUTER_LOG_TEXT`,
  `SHADOW_ROUTER_MAX_TURNS`, `SHADOW_ROUTER_QUEUE_SIZE` (default 3; oldest job dropped when full, counted `dropped_busy`).
- **Contract:** no tool execution, no change to replies or to consent/draft/memory/task/robot state; robot requests stay on `command_suggestion.classify`; extractor uses the local provider only;
  `needs_clarification` records a reason category only; forget/complete keep the resolved target; utterance text and validated args are written only with `SHADOW_ROUTER_LOG_TEXT=true` and never for a sensitive-labelled turn (file mode 0600).
- **Trial status (owner approved 2026-10-05):** ENABLED in `deploy/homelab/.env` (gitignored; backup `.env.bak-before-shadow-trial`): `SHADOW_ROUTER_ENABLED=true`, `SHADOW_ROUTER_LOG_TEXT=true`, `SHADOW_ROUTER_MAX_TURNS=500`, `SHADOW_EXTRACT_MODE=offline`. Started with `scripts/start-homelab.sh --shadow-router --build` (only companion-core was recreated; sidecar `reachy-homelab-semantic-router-1` healthy, 6 CPUs / 3 GB). Records accumulate in the `shadow-router` volume at `/data/shadow-router/shadow.jsonl` (mode 0600, utterance text on, never for sensitive turns) until 500 accepted turns (`trial_complete_skipped` then counts). No record existed yet at hand-off: the file appears with the first real non-slash turn (a smoke turn was not possible, core requires service auth). **When the cap is reached or the owner stops:** set `SHADOW_ROUTER_LOG_TEXT=false` (or remove the SHADOW_* lines), recreate companion-core, then follow docs/shadow-router.md steps 3-8 (extract offline against the shared vLLM on :8003 when idle, blind sheet, grade, report, purge). **Retention policy (owner, 2026-10-05; no deadline other than completing the evaluation): every recorded file (raw log in the volume and any copy, extractions, sheet, labels) is destroyed after evaluation and testing are complete** with `shadow_router_grade.py destroy` plus `shred -u -z` in the container; keep only the aggregates and the saved report. Do not copy the log anywhere backed up. Rollback = remove the lines and `scripts/start-homelab.sh --shadow-router --no-browser`.
- **Evidence (pilot, author-written except MASSIVE):** router fine accuracy 0.919 on MASSIVE-test, 0.89/0.91 on two challenge sets; extractor+validator unsafe executable extraction 1/50 (2%) on a holdout written after the validator was frozen (model alone 36%); 17-turn real run through /conversation left production replies unchanged. Do not change a live handler from those examples; wait for trial data.
- **Two-stage trial (2026-10-05):** live path = router sidecar only (`SHADOW_EXTRACT_MODE=offline`, default); extraction runs later offline with `tools/shadow_router_extract.py` (same frozen extractor and validator, separate results file, raw log untouched, merged by `rid` in the report, scrubbed by `purge --extractions`). Production impact re-check in offline mode: TTFT p95 at baseline, decode within host drift (~10%), router p95 67-90 ms, diarization unchanged, burst accounting exact. Live mode (extractor inside the turn) cost ~10% decode and ~20 ms TTFT; keep it for a later integration test. Details in docs/shadow-router.md. A foreign `bench-influxdb` benchmark once polluted measurements on this host: only measure when load average < 3. The owner's `reachy-homelab-vllm-1` now holds the GPU (port 8003), so a second vLLM cannot be started for benchmarks; use that one.
- **Machine state (2026-10-05):** the standalone sidecar container, the throwaway compose project `shadowcheck` and `vllm-bench` are removed. The trial is NOT enabled; sidecar artifacts live in `/home/hariz/inferencing/router/models` (symlinked into `deploy/homelab/semantic-router/models`). Bench workspace: `/home/hariz/inferencing/bench/router` (`contention_deploy.py` is the regression; `LLM_URL`/`LLM_BASE` env select the vLLM).
- **Open decisions:** run the trial and who grades; bounded retention for the log; whether to add a dedicated extraction model before the first promotion stage; promote read routes first.
- **Caution:** `app.py`'s `create_app` gained a `shadow_router` parameter; tests that build the app must still inject every store (a new required store, e.g. the planner store, breaks harnesses that omit it).

**Privacy mode (2026-10-03, committed ab87c7c, deployed to the homelab hub/core/UI):**
spoken "turn on privacy mode" (hub, deterministic, confirmation then session end),
Telegram `/privacy on|off` (core, all robots) and the Voice tab button all drive the
existing wake arm (disarmed = privacy on). Owner-tested live on 2026-10-03: spoken, Telegram and the
Voice tab button, each with the robot resting in the sleep pose, plus a restart with privacy on. After a spoken privacy conversation ends the
robot now rests once in the sleep pose (5ec6d78, AGENTS.md wake/sleep exception);
the first Nano deploy did not take effect (`start-reachy.sh --build` left the running container on the old image; fixed in 3bd4110, which now replaces it). After the redeploy the owner reported the spoken path working, 2026-10-03; Telegram `/privacy on` did not rest because the hub ends the session before the disarm arrives, so the disarm now rests directly when the monitor was armed (owner re-tested on the Nano after redeploy, 2026-10-03: Telegram and spoken paths both rest). A restart with privacy on did not start in the sleep pose (the hub's registration disarm found an unarmed monitor); the first disarm after process start now rests too (owner re-tested on the Nano, 2026-10-03: restart with privacy on starts in the sleep pose). Nano caution: its 59 GB disk filled with old embodiment images (about 30 GB reclaimable); at 100% the Docker build and `~/.docker/.token_seed` broke and, after a reboot, the daemon failed with "No usable temporary directory" and the once-per-boot recovery was spent. `docker image prune -f` and `docker builder prune -f` freed the space; check `df -h /` before a `--build`. Details in the
[operator guide](docs/operator-guide.md#telegram-query-commands). The hub was
recreated, so `small.en` may re-download (about 2 min) before voice works.

**Spoken goodbye (2026-10-04, committed, hub redeployed, owner-tested on the robot 2026-10-04: passed):** a whole-utterance "thank you" / "that's all" / "goodbye" ends the voice session after a fixed farewell (`end_intent.py`, hub only); the robot then rests via the normal armed path. Fixture-tested, then owner-tested live on the robot ("thank you" gave the farewell, then the sleep pose).

**Confidence-gated wake alert (2026-10-02, deployed to the Nano and homelab hub, calibration in progress):**
`2bf82e4` (no head motion on a raw hit) gave no feedback and was reverted
(cb66bb5). Now every detection still goes to capture/admission but the head raise
needs `WAKE_ALERT_THRESHOLD` (3c7bc6b; robot env file, unset = raise on every
detection, which is how the Nano runs now, image `reachy-embodiment:local`).
Hub option `WAKE_DEBUG_LOG_REJECTED_TRANSCRIPTS` (82ff980, hub env/.env) logs the
first 8 words of rejected candidates; it is OFF (set false in `.env`) and the
code and compose passthrough should be removed once calibration finishes.
Calibration so far (genuine "Hey Reachy, what time is it"): 5 hits, scores
0.88-0.98 admitted and spoken; one 0.78 discarded (no request). Earlier in the
session 3 of 5 attempts were never detected and a 0.95 hit was rejected
`no_wake_phrase` (likely the hub re-downloading `small.en` after a recreate; one
admitted reply was also "withheld", reason not found, possibly DND/meeting).
False-trigger run (2026-10-02, 11:53-about 12:30Z, about 36 min): 16
detections (about 27/h), all hub-rejected, 0 false conversations, all raised the
head. False scores 0.75-0.99 overlap genuine 0.78-0.98, so no score threshold
separates them; no `WAKE_ALERT_THRESHOLD` is set and the Nano keeps raising on
every detection. Owner decision (2026-10-02): detector comparison (30.1d,
`wake-bench.py --record`, 0429566) is deprioritized; continue the rest of Phase 30.
30.2 is done (2026-10-04): the metric is defined in [phase-30](docs/phase-30.md#visible_false_activations_per_hour) and the 24g acceptance, and `tools/wake_metrics.py` ran on real Nano logs (26.7 visible false activations/h on the 0.6 h false-trigger window; no per-hour target agreed).
30.5 backup/restore and a 5-minute hub outage/reconnect passed (2026-10-04, [record](docs/verification/phase-30-2026-10-04.md)). The other "Run" rows need the owner (stop-while-homing and mid-reply switch-off need a live voice session; fresh scene needs a changed scene). The wake arm was off (privacy on) at the last check, so re-arm before calibration.
Open: early-hub-verdict design (needs owner go-ahead), removal of the debug transcript log after calibration, 30.3-30.5.

**Phase 29 is closed for the subscription-first scope (2026-10-02, deployed
to the homelab, uncommitted).** Characterization found that the agent's
`AskUserQuestion` tool call and `permission_denials` separate needs-owner from
done; hooks were not needed. Built: confirmed `WAITING_FOR_INPUT` /
`WAITING_FOR_PERMISSION`, intervention fields and `turn`, a per-session
`reachy-claude-state-*` volume so `--resume` works, `/coding_reply` (verbatim
relay), turn-keyed notification claims, Git observations, and the "Terminal
sessions (view only)" label. Details and the unexercised list:
[closure](docs/phase-29.md#characterization-results-and-closure-2026-10-02).
The agent image `reachy-coding-agent-claude` must be rebuilt on any other host
(`docker build` in `services/coding-agent-service/docker/claude-code`). Terminal
sessions stay view-only; CLI findings and open options (Remote Control spike,
`--bg` provider, idle push) are in
[phase-29](docs/phase-29.md#controlling-terminal-sessions-cli-findings-2026-10-02).
Left
behind by live testing: a `git-probe` project (path `/tmp/claude-1000/gitprobe`)
and two probe sessions in the homelab database. `test_robot_voice.py::
test_spoken_command_text_does_not_actuate_the_robot` fails on a clean tree too.

**Running-session poller (2026-10-02, deployed):** coding-agent-service
now inspects in-flight sessions every 30 s (`CODING_AGENT_POLL_INTERVAL_SECONDS`,
`0` disables) so finished containers reach `COMPLETED` and Telegram's completion
push fires. Verified with fixture runtimes and a lifespan test, not a real Claude
container. Still missing: the 29.4 hook bridge (WAITING_FOR_INPUT/PERMISSION,
hook-driven RATE_LIMITED, Stop/SessionEnd). A live probe (see phase-29 29.4 note) showed hooks surface in the stream with `--include-hook-events`, but a headless run that asks a question still ends as a plain success; do not build WAITING_* from hooks without observed evidence from subscription sessions (the API-key probe originally proposed here is deprioritized, see above). Poller deployed live and verified (probe session reached `completed` unprompted).

**Reachy sees terminal sessions (2026-10-02, built, not deployed):** the status
reply (`/coding_sessions`, "is my claude session done") now adds a read-only
"Terminal sessions" section via companion-core's new
`list_terminal_sessions` client call. Control (resume/send instruction, or
adopting a terminal session as a managed one) was offered and deliberately not
built. Rebuild core to activate; it needs `CLAUDE_PROJECTS_DIR` already
mounted in coding-agent-service.

**Durable coding-agent sessions and Claude allowance are deployed to the
homelab (2026-10-01, Phase 29.27/29.26).** Migration `013_coding_agent` applied
(pre-upgrade dump: `~/reachy-backups/reachy-before-013-20261001-223839.dump`);
migrate, core, hub and coding-agent-service rebuilt and running, health OK, the
allowance route enforces auth. No non-terminal sessions existed at startup, so
no live recovery was exercised. The rest of this entry predates the deploy.
**Coding agents tab (2026-10-01, built, not yet deployed/browser-tested):** new operator-UI tab after Meetings (`coding_monitor.js`) with owner-gated hub proxy routes `/coding-agents/*`; creates projects and sessions, shows allowance, sessions, events and usage. Tests/ruff pass; `node --test` cannot run here (no playwright). Needs a hub rebuild and a browser check. Send instruction/Respond are not in the tab. Deployed to reachy-homelab, with a read-only terminal-sessions list (needs CLAUDE_PROJECTS_DIR, set in .env). CAUTION: always pass `-p reachy-homelab --env-file .env` to docker compose; a bare run created a stray `homelab` project once. An accidental `ruff format` reformatted several coding-agent-service files (whitespace only); the repo does not enforce ruff format.
**Live allowance (2026-10-01, deployed, owner-tested via Telegram):** the
`claude setup-token` token is refused by `api.anthropic.com/api/oauth/usage`
(HTTP 403, inference-only scope), so the owner pastes a full-login
`.credentials.json` (from a separate `CLAUDE_CONFIG_DIR` login) into the
operator UI's "Claude account usage" card (credential name
`claude-code-account`, allowed in `reachy_hub.coding_agent`).
`ClaudeCodeProvider.live_allowance` refreshes it (rotating refresh token,
persisted before use, lock-guarded) and `GET /providers/{p}/allowance` prefers
it (`source: "live"`), falling back to CLI-reported windows on any error.
Refresh URL/client id were read from the pinned CLI binary. If the figures
vanish, check coding-agent-service logs for "Live allowance unavailable".

Operator UI reorganization is implemented locally, not deployed (2026-10-01).
Overview now contains monitoring; Settings consolidates configuration into six
feature tabs; Meetings has a searchable records sidebar; Chat has durable typed
web records and a conversation workspace. Records preserve the existing shared
assistant session rather than creating independent model contexts. Deployment
requires additive migration `012_web_chats` plus rebuilt images, not just a
static-file copy. See the [operator guide](docs/operator-guide.md#settings) and
[verification](docs/verification/operator-ui-2026-10-01.md). Browser, operator API,
real disposable-Postgres persistence and Ruff checks passed. The broader hub
suite has one pre-existing scripted voice-reply assertion failure, reproduced
against the original hub app. The disposable project was removed; production
services, databases and robot were untouched.


Telegram query shortcuts are implemented locally, not deployed (2026-10-01).
The [operator command list](docs/operator-guide.md#telegram-query-commands)
contains the new reads and `/help`. Core dispatches structured commands to
existing handlers; shared metadata supplies hub's startup menu registration.
96 command/conversation/Telegram fixture tests passed, including argument
isolation, private routing, and Telegram bot suffixes. No real Telegram messages,
model invocation, deployment, or robot actions were performed. Rebuild core and
hub to activate the shortcuts and menu on the running bot.


The reported Telegram session/usage reply bugs are fixed locally (2026-10-01),
not deployed: natural Claude Code session questions now reach the deterministic
handler, and usage reads include finished sessions. Replies explain the managed
session scope; status is labelled last recorded. (The in-memory history limitation
mentioned at the time is superseded by the durable store above.)
See [service reference](docs/reference/services.md) for the behavior. Regression
coverage uses the exact reported questions and an in-process service chain with
a simulated provider returning measured usage for a completed session. All 74
focused intent/service/conversation tests and Ruff passed. No live
Telegram message, model invocation, deployment or robot action was performed.


**First real Claude Code completion, live, with the owner's real
subscription (2026-10-01).** The owner registered a real Claude Pro/Max
subscription (`CLAUDE_CODE_OAUTH_TOKEN`) credential through the operator
UI and asked to actually test it. That required deliberately lifting the
no-invocation block added earlier the same session (see further down) —
`_ensure_can_invoke` now only refuses when no credential is configured at
all; a subscription session starts for real but stays read-only
(`--permission-mode plan`, a comprehensive `--disallowedTools` list, and a
real Docker `:ro` mount — previously dormant protection, now the live
protection); an API-key session is unaffected and keeps full permissions.

Turning the owner's "let's test it" into an actual successful run surfaced
three real infrastructure gaps, all found and fixed live, none related to
the guardrail itself:

1. **coding-agent-service's own container had no `docker` CLI at all** —
   every real container launch failed with `FileNotFoundError`. Fixed by
   installing the `docker-cli` package (client-only, no `dockerd`) in
   `services/coding-agent-service/Dockerfile`.
2. **No access to the host's Docker daemon even with the CLI installed** —
   fixed by mounting `/var/run/docker.sock` into the container. **This is
   a real, owner-approved security decision, not a casual default**: a
   container with that socket has host-root-equivalent reach. It's scoped
   to this one orchestrator container, not the session containers it
   spawns — 29.18's "no socket" rule is about those, not this service
   itself, whose entire job is controlling the host's Docker daemon.
3. **`restricted-network` (the default `CodingProject.allowed_network_profile`)
   was never actually provisioned** — `docker run --network
   restricted-network` failed with "network not found" even after the
   socket fix. Fixed by declaring it in
   `deploy/homelab/docker-compose.yml`'s top-level `networks:` with an
   explicit `name:` (Compose would otherwise silently prefix it to
   `reachy-homelab_restricted-network`, which the runtime's literal
   `--network` flag would never match).

With all three fixed, a real session — real `claude` CLI, real Anthropic
API, the owner's real subscription — **completed successfully**: "Hi!
There's nothing to plan here — just let me know what you'd like help
with." This is the first real completion this integration has ever
produced. Confirmed via `/sessions/{id}/usage` too (1581 input / 35 output
tokens, ~$0.08 equivalent — informational for a subscription, not a
charge). Test files updated to match (a subscription session now starts
200/read-only instead of being refused 403); two real-Docker tests re-run
against the actual fixed container. Redeployed live; `ruff` and the full
`services shared` suite (1013 passed) both still green afterward.

**Known follow-up, not yet done:** `DockerCLIContainerRuntime.start()`
doesn't clean up a container Docker creates-but-fails-to-fully-start
(e.g. the network-not-found failures above left a few `Created`-state
containers behind — manually `docker rm`'d this session, but nothing
automatic does this yet).

---

**Telegram status/usage questions and completion notifications
(2026-10-01, owner request: "the flow that needs to be working is that i
can use the telegram bot to ask or be informed if a session is complete or
to check the current usage").** Built before the OAuth-credential work
above, same session:

- `companion_core/coding_agent_intent.py` (deterministic, no LLM) answers
  "is my coding session done"/"what's my claude usage" in any channel,
  via a new `companion_core/coding_agent_client.py` (direct sibling HTTP
  call to coding-agent-service, same pattern as `hub_client.py`).
- `GET /coding-agents/completions/due` on companion-core — a pure,
  claim-once query (same shape as `/calendar/reminders/due`;
  `companion_core/coding_agent_notifications.py` does the claiming — in memory
  when this was written, now Postgres-backed under migration 013).
- A genuine new background loop in reachy-hub, `coding_agent_notify_loop`
  (60s interval), polls that and pushes a Telegram message via the
  existing `push_to_telegram` for anything due. Deliberately skips the
  full `interruption_policy` DND/occupied/urgency routing calendar
  reminders use — always pushes immediately, since "tell me when it's
  done" was the actual ask.
- Verified with a real asyncio task on a short interval against a fake
  Telegram API (not just the pieces in isolation) — see
  `services/reachy-hub/tests/test_coding_agent_notify.py`. Also verified
  live: created a real test session, confirmed reachy-hub's actual running
  loop claimed it via `/coding-agents/completions/due` (empty on
  re-query) without me triggering it manually.

See [docs/phase-29.md](docs/phase-29.md) (29.6/29.13 row) and
[service reference](docs/reference/services.md) for where this sits
relative to the rest of the phase. Still missing: input-needed/rate-limit
notifications (needs 29.4's hooks), and no DND-aware routing.

---

**coding-agent-service is now deployed and running live on this homelab**
(2026-10-01, by owner request "let's run the latest so we can start user
testing"): added to `deploy/homelab/docker-compose.yml` with its own
`CODING_AGENT_SERVICE_TOKEN` and `CODING_AGENT_SECRET_KEY_FILE` (a real
key generated this session at
`deploy/homelab/.env.coding-agent-secret-key.json`, 0600, gitignored, not
backed up elsewhere yet — do that before relying on any credential
surviving a lost volume), both appended to the real `deploy/homelab/.env`.
Built and started via `scripts/start-homelab.sh --build --no-browser`;
`reachy-hub` and `companion-core` were recreated to pick up the new env
vars (expected — not an error), everything else (postgres, caddy,
searxng, transcription, diarization) was left alone and confirmed
untouched. Verified: `/hub/health` and `/core/health` both `ok`, and
`/hub/providers/credentials` returns 401 (login required), confirming the
route actually reaches a real, token-configured coding-agent-service
through hub rather than 404/502/503. Also smoke-tested the full
project/session lifecycle directly against the live container (zero cost
— `provider: "simulated"`, not Claude): `POST /projects`, `POST
/sessions`, `GET /sessions/{id}/events` all worked exactly as the test
suite predicts, confirming the live deployment isn't just "built", it
actually runs. That data is in-memory only and is already gone on any
restart — no cleanup needed.

**What the owner can test right now:** log in to the operator UI and use
Settings · Accounts · Coding agent credentials — that's wired to the
browser and live. **What they cannot test yet:** starting a real Claude
Code session from the browser — there is no operator-UI or hub-proxied
path to register a `CodingProject` or start/poll a session, only raw
routes on coding-agent-service's own internal port (same `expose`-only,
no `ports:`, pattern every other homelab service uses — reachable from
the host only via `docker exec <container> ... /usr/local/bin/python3`
inside the Docker network, not a stable localhost URL). That gap (a
project/session UI, or at minimum a hub proxy plus a documented curl
recipe) is real follow-up work, not something this session built. See
[deployment](docs/deployment.md#key-provisioning) for the key-provisioning
procedure now documented there.

Phase 29 (coding agent supervisor) was added to the roadmap this session,
and its first stage, 29.1 (contracts and session store), is now
implemented at `services/coding-agent-service`: `CodingAgentSupervisor`
creates/resumes/stops a durable `CodingAgentSession` against a provider
registry and records normalized `CodingAgentEvent`s; a `SimulatedProvider`
and an in-memory store stand in for the real Claude Code adapter (29.3)
and Postgres durability (29.27), both still planned. Wire models
(`CodingProject`, `CodingAgentSession`, `CodingAgentEvent`,
`ProviderCapabilities`, `UsageSnapshot`, request schemas) live in
`shared/models/coding_agent.py`; routes/service-token constant in
`shared/protocols/coding_agent.py`. Added to the uv workspace
(`services/coding-agent-service`); `uv sync --all-packages` restored after
an accidental `--package`-scoped sync pruned the shared dev venv mid-session
(no production impact — dev venv only).

29.2 (container runner) is implemented too: `runtime.py`'s
`DockerCLIContainerRuntime` shells out to the real `docker` CLI to start a
labeled, resource-limited, non-root, no-socket container, and
`reconcile.py`'s `reconcile_sessions` marks a session `LOST` (never
`COMPLETED`) when its container is no longer running. Verified against
this machine's **real, live Docker daemon** — the same one running the
actual `reachy-homelab-*` production containers — using disposable
`busybox` containers labeled distinctly and always cleaned up; no
`reachy-homelab-*` container was touched, started, stopped or restarted.

29.19 (credentials) was pulled forward out of sequence, per explicit
instruction this session to make sure any real keys/login credentials this
phase needs are reachable from the web UI rather than left to env files:
`credentials.py`'s `EncryptedFileCredentialStore` (AESGCM, own key file via
`CODING_AGENT_SECRET_KEY_FILE`, separate from companion-core's keyring)
backs `PUT`/`GET`/`DELETE /providers/{provider}/credential` in
coding-agent-service; `reachy_hub/coding_agent.py` +
`reachy_hub/coding_agent_client.py` proxy those under owner cookie+CSRF
auth (same shape as `reachy_hub/accounts.py`); and the operator UI's
Settings · Accounts tab has a "Coding agent credentials" card
(`clients/operator-ui/coding_agents.js`) to set/replace/remove the Claude
Code or Codex credential — the secret is never echoed back once saved,
only `last_four`.

29.3 (Claude Code provider) is also now implemented, making the 29.2
runtime and 29.19 credential both actually used for the first time:
`claude_provider.py`'s `ClaudeCodeProvider` is wired into
`create_app()`'s default provider registry under `"claude-code"`, alongside
`"simulated"`. `services/coding-agent-service/docker/claude-code/Dockerfile`
builds a real image (`node:20-slim` + `npm install -g
@anthropic-ai/claude-code`) — **this was actually built and run on this
machine's real Docker daemon** (`docker build ...`, then `docker run
reachy-coding-agent-claude:latest --help`/`--version`/a real `-p "say hi"
--output-format stream-json` call with a deliberately invalid API key, no
real cost incurred) to confirm the exact CLI flags and JSONL output shape
rather than guessing from documentation. Confirmed live at claude-code
2.1.197: `claude`'s own `--session-id <uuid>` flag lets the provider assign
and know the session id immediately at start, instead of parsing it out of
output; `--output-format stream-json` prints one JSON object per line,
ending in a `{"type":"result",...}` line whose `is_error`/`usage`/
`total_cost_usd` drive completion/failure/usage; and a bad credential
produces repeated `{"type":"system","subtype":"api_retry",...}` lines
while the CLI retries for minutes rather than failing fast, which is why
`start_session` only starts the container and assigns the session id — it
does not block waiting for completion. `inspect_session` (exposed as the
new `POST /sessions/{id}/refresh` route) is what a caller polls later.
`--dangerously-skip-permissions` is never passed, matching AGENTS.md's
stance that the LLM has no authority to bypass its own action gate either.
A `collect_usage` using the parsed `usage`/`total_cost_usd` and an
opportunistic `RATE_LIMITED` status on a `429` retry line are also wired.
Verified end to end against the real image and real Docker daemon with an
intentionally invalid key (`services/coding-agent-service/tests/
test_claude_provider_docker.py`, opt-in via `CODING_AGENT_DOCKER_TEST=1`):
real container starts, real session id tracked, real stdout parsed, real
stop. **Completing an actual task against the real Anthropic API needs the
owner's own `claude-code` credential entered in the operator UI — that has
not happened and was not exercised by any automated test**, since it would
cost real money.

Two follow-up fixes/additions after 29.3 landed, both same-session:

1. **Bug found and fixed:** `ClaudeCodeProvider` originally sent every
   stored credential as `ANTHROPIC_API_KEY` regardless of its
   `CredentialKind` — an owner who picked "OAuth token" (a Claude Pro/Max
   subscription) in the operator UI would have had it silently fail to
   authenticate. Confirmed by grepping the real installed `claude.exe`
   binary for its actual env-var names: a subscription's long-lived token
   (from `claude setup-token`, run interactively elsewhere — this
   container cannot do that sign-in itself) belongs in
   `CLAUDE_CODE_OAUTH_TOKEN`, a different variable. `_credential` now
   reads the stored kind and routes to the right one; the operator UI card
   got an explanatory note on how to get a subscription token.
2. **Hard guardrail for a real subscription credential, owner request
   2026-10-01, revised same day.** First pass restricted the real
   container to read-only/limited tools; the owner clarified the actual
   intent was narrower and more direct: don't let a real Claude Pro/Max
   subscription spend credits at all yet, regardless of file/tool access —
   only allow reading existing projects/session status. Rebuilt
   accordingly: `start_session`/`resume_session`/`send_input` now raise
   `ProviderInvocationBlockedError` (routes.py maps it to HTTP 403) before
   touching Docker, the project store, or even decrypting the secret, for
   any `CLAUDE_CODE_OAUTH_TOKEN` credential. No container is created at
   all — confirmed via `runtime.list_by_session()` returning empty after a
   blocked call, both in the fixture suite and against the real Docker
   daemon. Listing/reading projects, sessions, events and usage is
   completely unaffected, since those never call this adapter's invoking
   methods. The original read-only layer (`ContainerSpec.read_only_mount`
   → a real `:ro` bind mount, confirmed twice by an actual blocked write
   including via `docker exec` into a live `claude` container; a
   `--disallowedTools` list — confirmed live to be what actually restricts
   tools, since `--allowedTools` alone did **not** restrict anything in the
   same test, despite its help text implying it should; `--permission-mode
   plan`) is kept in `_build`, not deleted, as dormant defense-in-depth for
   whenever the invocation block is deliberately lifted — it is currently
   unreachable in practice since the block above stops a subscription
   credential before `_build` ever runs, and a dedicated test exercises it
   directly against a real container so that dormant path stays proven.
   None of this is a runtime toggle; lifting the invocation block needs a
   deliberate future code change once the integration has actually
   completed a real task successfully with an API key. A pay-per-use API
   key session is unaffected throughout. See `claude_provider.py`'s module
   docstring for the full reasoning and exactly what was tested vs.
   assumed.

Nothing wires coding-agent-service's *session* lifecycle into
companion-core or reachy-hub yet (29.6/29.7 — only the credential routes
reach the browser so far), there is no hook-based mid-task
`WAITING_FOR_INPUT`/`WAITING_FOR_PERMISSION` detection (29.4), and it is
not in `deploy/homelab/docker-compose.yml` — all deliberately deferred to
their own stages per
[docs/phase-29.md](docs/phase-29.md#2929--implementation-sequence).
44 coding-agent-service tests exist (39 pass by default; the 5 real-Docker
ones are opt-in via `CODING_AGENT_DOCKER_TEST=1` and all pass given the
built image, including the guardrail checks above), plus 4 reachy-hub
tests (`test_coding_agent_credentials.py`) and one Playwright test
(`coding_agents.test.cjs`, run externally — Playwright/Chromium is not
installed in a default dev shell). Full `services shared` suite (996
passed; one unrelated `test_wake.py` flake reproduced as a pass on rerun,
not a regression) and `ruff check .` both still pass. See
[service reference](docs/reference/services.md#coding-agent-service-phase-29-planned)
for the exact route/behavior surface.

Meeting UI wording/layout cleanup is implemented locally, not deployed.
Rows separate title/status/date/actions; ALIGNING displays “Processing
paused” with the missing speaker-alignment feature explained. Raw errors
are collapsed in detail, and phase numbers are removed from user copy.
The reported metadata_errors row is the historical failure documented in
foundation verification; its dependency fix already exists. No records
were deleted or retried. Chromium with fixture data passed mobile layout,
literal text, paused wording, collapsed errors, detail reset and cancel
routing; JS syntax and Ruff passed. This is not live pipeline acceptance.
See [operator guide](docs/operator-guide.md#meeting-recordings).

Long-meeting transport fixes implemented: spooled Hub uploads, bounded
Core disk copies, file-backed worker inference requests, configurable
six-hour inference response waits and sidecar busy rejection. No schema
change. Existing live containers remain untouched; verification used a
separate `reachy-long-meeting-check` Compose project with read-only model
caches and the updated server source mounted into existing images.
See [long-audio verification](docs/verification/phase-27-long-audio-2026-09-30.md)
for exact checks and remaining limits, and
[operations](docs/deployment.md#long-meeting-recordings) for settings.
No representative human meeting recording was supplied.

The deployed pipeline stores raw speech results and waits at ALIGNING.
The live run built transcription and reused the owner's standalone
diarization container; it did not build the repository diarization image.
See the [verification record](docs/verification/phase-27-foundation-2026-09-30.md)
for dated evidence, dependency fixes and remaining acceptance. Four test
meetings remain in the database/audio volume; no delete endpoint exists.

## Next session

**Phase 37 (shadow router) is independent of the Phase 30-36 order.** The trial is collecting; the next steps are the evaluation chain in [shadow-router](docs/shadow-router.md#trial-procedure) (extract offline against the shared vLLM when idle, blind sheet, owner or designated grader labels, report with voice and text reported separately, then destroy every recorded file). Nothing moves past shadow without an owner decision per stage; see [phase-37](docs/phase-37.md).

**Roadmap re-sequenced 2026-10-02.** Remaining work now follows the
[forward roadmap](docs/plan.md#forward-roadmap-phases-30) (Phases 30–36);
Phases 0–29 are the historical ledger and keep their IDs. The numbered list
below is older and maps as: items 7–8 and the wake check → Phase 30; items 1–3
→ Phase 31; items 4–6 → Phase 32; Phase 29 is closed and its leftovers are
Phase 35 (optional). Immediate order: (a) the owner recreates
`reachy-embodiment` on the Nano from the confidence-gated build and collects wake
scores for calibration; (b) occupied-room wake check and the
visible-false-activations/hour metric; (c) then Phase 31 meeting acceptance.
[docs/phase-30.md](docs/phase-30.md) (written 2026-10-02) holds the Phase 30
sequence, the metric definition and the closure triage; no Phase 30 code or
physical step has been done, and waiving old acceptance rows needs the owner.

0. Phase 29 is now live on the homelab (see Current work) —
   `CODING_AGENT_SECRET_KEY_FILE` is already set, so a credential entered
   through the operator UI now survives a restart. The actual next step is
   the owner logging in and using the Settings · Accounts · Coding agent
   credentials card for real: the subscription credential is already
   registered and invokes read-only sessions (the "cannot invoke" note that stood
   here was superseded 2026-10-01; an API key is optional, see the phase-29
   revision), and registering a project against a real test repository, since nothing in
   this codebase has a route to create a `CodingProject` from the operator
   UI yet — only `POST /projects` on coding-agent-service directly (no hub
   proxy for project/session management exists, just credentials). That
   gap — an operator-UI or at least a documented curl path to register a
   project and start/poll a session — is probably the most useful next
   build step, ahead of 29.4 (Claude hooks) or a 29.14 poller. The Postgres store (29.27)
   is built but needs deploying with migration 013 (see Current work).
1. Roll out the long-audio changes to Core, Hub and both sidecars, including
   the standalone diarization server (do not create a competing instance).
   Coordinate speech-token activation with that restart. Representative
   human speech/resource acceptance remains open despite synthetic
   65-minute infrastructure checks.
1. The pipeline reached ALIGNING with a short synthetic clip
   (upload → transcribe → diarize → wait at ALIGNING, ~2s); alignment
   itself is not implemented. Still owed: open
   the operator-ui Meetings tab in an actual browser (upload, record via
   `meeting-record-start`/`-stop`, and confirm the detail view renders
   `transcript_segments`/`diarization_segments` correctly — everything so
   far was exercised via curl, not a real browser); run a real 30–60
   minute multi-speaker meeting through it and record duration/RTF/CPU/
   RAM per the 27.2/27.3 exit criteria; decide what to do with the four
   leftover test meetings in the real database (no delete endpoint
   exists yet); decide whether to enable `SPEECH_SERVICE_TOKEN` (would
   need rebuilding/restarting the existing diarization container — see
   below); and confirm a meeting's row/audio file survive
   `docker compose restart companion-core`. See
   [the verification record](docs/verification/phase-27-foundation-2026-09-30.md)'s
   live-deployment addendum for exactly what's proven vs. still open.
2. 27.4 (alignment): once 1 above confirms both sidecars actually work,
   the next real gap is that `transcript_segments` and
   `diarization_segments` sit on the `Meeting` row unmerged — no
   canonical speaker-attributed `TranscriptSegment` exists yet, and
   `MeetingWorker` runs TRANSCRIBING/DIARIZING strictly sequentially
   rather than concurrently (ADR 0025 allows parallel; not done). Decide
   whether to tackle the parallelism and the alignment reducer together
   or separately.
3. 27.6 (meeting analysis): the Meetings detail view currently shows raw
   segments and says explicitly that minutes/decisions/actions don't
   exist — that's the next user-visible gap once 27.4 lands.
4. Verify Settings · Accounts → Owner recognition in a real browser:
   opt-in, microphone recording, face capture, sample sizes, delete and
   export. Previous enrollment checks were backend-only; browser tooling
   availability must be rechecked rather than assumed.
5. Collect consenting owner/non-owner audio, including a separate dataset
   through the real Reachy microphone with noise/distance/orientation variation.
   Benchmark ECAPA and select thresholds from FAR/FRR before implementing its
   production adapter; measure concurrent Whisper + ECAPA on the homelab.
   The [existing smoke test](docs/verification/phase-25a1-voice-benchmark-2026-09-28.md)
   used public model-card clips only. Keep the sensitivity gate off pending
   the explicit owner decision described in the [plan](docs/phase-25.md#implementation-sequence).
6. Implement and evaluate the second-stage sensitivity classifier before
   enabling the gate; speaker verification alone cannot resolve UNKNOWN.
   Then proceed to 25b.1 DoA/orientation and face-model comparison. Full
   production gate prerequisites are in the
   [implementation sequence](docs/phase-25.md#implementation-sequence).
   AASIST benchmarking remains a separate pass.
7. Resume the owner-deferred 24g held-out run when requested: use the
   [scenario list](docs/phase-24g.md#acceptance-requirements) and
   [agreed targets](docs/phase-24g.md#agreed-numeric-targets-owner-2026-09-27),
   with conversational motion off. Include 3–5 immediate-question,
   3–5 natural-pause, and a few wait-for-acknowledgement attempts (user
   pauses to watch the alert pose, then speaks) — the doc's acceptance
   requirements were extended 2026-09-28 to cover this third interaction
   style and to require that speech is never lost to the animation. Record
   fresh evidence; the
   [previous held-out attempt](docs/verification/phase-24g-physical-2026-09-27.md#admission-fix-and-calibration-follow-up)
   failed before the timeout increased to 6 s.
   `WakeMonitor._listen_and_capture` (`services/reachy-embodiment/src/reachy_embodiment/wake.py`)
   already fires the alert-pose goto without awaiting it before starting
   capture, matching that requirement, but no test currently asserts the
   timing (only move ordering); consider adding one with a slow fake
   `rest_move` before relying on it further.
8. Check the shortened privacy carry-forward window on the robot (calendar
   question, then 7–8 unrelated turns), the Trusted mode UI, and palm stop
   after the next authorized standby/wake. These live checks remain open.

## Last-reported machine state

These are previous session observations, not health checks performed during
this documentation pass. Recheck state before relying on them.

- **Nano:** booted 2026-09-27 06:47 WIB (motor supply was off on the first
  boot; the once-per-boot recovery restarted the daemon once and stopped,
  as designed). The daemon runs as PID 7340 and was `running` at 09:33Z.
  - **Checkout/image:** `c579cc8` was physically verified at 10:57:45Z;
    the later `bab441e` latency-logging build was also reported deployed.
    Inspect the actual running revision before relying on either report.
    "Hey Reachy" was armed; the arm persists in the hub database.
  - **Rollback:** `:0880b1b` (`15ba2797`), then `:b62a023` (`ebfffcef`),
    then `:6f6eb24` (`0ab5ebdf`); roll the checkout back with it.
  - **Motion:** 24f gestures and wobble were switched **on** by the owner
    at about 10:48Z; they reset to off on any embodiment restart.
  - **Access:** sudo on the Nano needs a password, so the owner runs
    `systemctl` steps and container recreates. This dev box has key SSH
    as `Reachy-Mini-Jetson`.
  - **Tools:** the system `python3` is too old for `voice-timing.py`: use
    `~/reachy-venv/bin/python`, and pass `--session N` when a log holds
    several voice sessions. There is no MediaPipe on the Nano (palm stop is
    hub-side). `opencv-python-headless` for the 24f tools is in
    `~/24f-tools` only (use `PYTHONPATH`).
  - **Logs:** `~/24f-logs` and `~/24d-logs`; the 24g image build logs are
    in `~/24g-logs`.
  - **Units:** `reachy-embodiment.service` and
    `reachy-daemon-recovery.service` are enabled, and the container has no
    Docker restart policy.
  - **Network:** embodiment is host-networked on 8100, and the daemon is on
    loopback 8000.

- **Homelab:** hub/core rebuilt and recreated 2026-09-30 for Phase 27
  speech inference (this session, real deployment — see Current work);
  schema is now `011_meeting_speech_results`. The `transcription` profile
  is running (`reachy-homelab-transcription-1`); `diarization` is
  **not** a `reachy-homelab`-managed container — it's the owner's
  pre-existing standalone `diarization` container (separate Compose
  project, `docker ps` shows it un-prefixed), joined to the
  `reachy-homelab_default` network by `docker network connect` so the
  `diarization` hostname resolves for companion-core; don't `docker
  compose -p reachy-homelab --profile diarization up` without first
  deciding whether to keep both or replace the standalone one (see the
  verification record). `STT_MODEL=small.en`, `PALM_STOP_ENABLED=true`
  and `VOICE_CONTINUATION_WINDOW_MS=3000` are in the private `.env`
  (unrelated to the new `MEETING_STT_MODEL=small.en` for the
  transcription sidecar, a separate model instance). The latest
  pre-deploy backup is
  `~/reachy-backups/reachy-before-phase27-speech-deploy-20260930T143344.dump`
  (backups are 0600). Use the [homelab launcher](docs/deployment.md#homelab).
  The hub's in-memory turn records (`GET /hub/robot-voice` with the
  `REMOTE_UI_TOKEN` bearer) give per-turn STT/LLM/TTS timings. They also
  contain transcripts, so extract only what a record needs. Piper
  `en_US-lessac-medium`; search policy Auto, Brave/Exa/Tavily rotation,
  then SearXNG.
- **Local inference:** an unrelated `ovms` container serves
  `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` on localhost:8000. Leave
  unrelated services alone.
- Hosted credentials are in gitignored `deploy/homelab/.env.local`.
  Check presence and ignore rules without printing values. No Google OAuth
  client file or live helper run has been supplied.
- Nano Tailscale endpoints to the homelab have switched between
  10.180.1.23, .54 and .254. Network cleanup remains the owner's call.

## Immediate cautions and continuation

Use [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
before daemon starts or motion; launcher `--check` stays read-only. Keep
conversational motion off for Phase 25 until deferred 24f acceptance passes.
Hardware work previously involved a separate Nano-side session; verify raw
device identity before accepting remote reports.

Disposable Nano scratch: `~/24g-bench`, `~/24g-src`; acceptance logs under
`/tmp/.../scratchpad/24g-acceptance/` were session-scoped, not durable.
A recreated hub downloaded small.en again (112 s before voice worked);
this was noticed but not investigated.
