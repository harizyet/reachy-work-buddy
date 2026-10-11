# Privacy remediation deployment and SearXNG credential rotation (2026-10-11)

Owner-approved, in two parts. **Part A: core-only deployment of commit `41a81a0`** ([engineering record](task-privacy-named-note-2026-10-11.md)). **Part B: rotation of the exposed SearXNG secret** ([procedure](../deployment.md#the-bundled-searxng-secret-format-consumers-and-rotation)). No migration, no database change, no flag change. **Result: both succeeded.** No task, note, reminder, meeting, alarm or provenance row changed. No secret value, task title or note content appears in this record, in the logs, or in the commands' output.

## Part A: core deployment

| | |
|---|---|
| Commit / image built | `41a81a0` = `origin/main`; image `260eab85da2b` built from a clean `git worktree` (0 modified files); the four frozen Phase 48 capture files inside it match the trial log's hashes; schema head 029; flag default false |
| Replaced | image `ef80ad3c7c77` (`router-d7eee35`), started 12:28:34 UTC, 0 restarts |
| Schema / flags (all preserved) | `029_notepad_processing`; `INTENT_ROUTER_ENABLED=true`, `NOTEPAD_PROCESSING_ENABLED=true` (concurrency 1), `KNOWLEDGE_INDEXING/RETRIEVAL/SELECTIVE_SHADOW=true`, `MEMORY_CANDIDATES` and `_CAPTURE=true`, `SHADOW_ROUTER_ENABLED=true`; selective answering absent |
| Quiet window | no alarm or reminder due in 5 minutes, no meeting processing |
| Downtime | graceful `docker stop -t 30` at 12:59:15 (exit 0, not OOM-killed); `compose up -d --no-build --no-deps companion-core`; `/health` 200 at 12:59:23. **About 8 s.** Compose interpolation was validated with `config --quiet` before the stop |
| Phase 48 boundary 5 | cohort E (12:28:36 to 12:59:16 UTC, image `ef80ad3c7c77`) closed; read before the stop `{"attempted":16,"excluded_channel":16}` (all probes, no real owner turn). Cohort F opens 12:59:20 UTC (image `260eab85da2b`); its first 20 attempts are probes (channel `probe-privacy`), subtracted. Shadow telemetry flushed at the stop and copied to `~/reachy-backups/privacy-rollout-20261011/`. Do not merge E and F |
| Rollback assets | `reachy-rollback/companion-core:pre-privacy-fix` = `ef80ad3c7c77` (verified equal to the running image before the stop). **It contains the label defect**: the legacy task replies are labelled from the question and the `tasks.*` handlers ignore the channel ceiling (task titles can be labelled public). Restoring it needs the owner's explicit decision. `pre-router` (`1c3290c4d993`) has the same defect. Baseline hashes and counters are in `~/reachy-backups/privacy-rollout-20261011/` |

## Privacy and routing results (production, text and voice probes on channel `probe-privacy`; booleans and labels only)

| Check | Result |
|---|---|
| Authorised private channel: `What are my tasks?` | lists both existing tasks (`tasks.inquiry`), label work-private |
| `tasks.search`, `reminders.read`, `notes.read` on text | answer normally, label work-private; notes list shows the stored notes |
| `tasks.complete` with a phrase that matches no task | label work-private, nothing completed |
| Shared speaker (voice) for `tasks.inquiry`, `tasks.search`, `reminders.read`, `notes.read` | each returns the restriction message; no task title and no note title in the reply; label work-private. `tasks.complete` on voice: label not public. Router memory path on voice: no task or note text, label not public |
| `What did I write in My Task for next week?` (text) | handler `records.reference`: the note read verbatim, header and body present, no task-list marker, label work-private |
| Same question on a shared speaker | discloses neither the note nor any task |
| Hybrid router | `router.memory.recall` and `router.records.find` handlers ran; the contact question invents nothing; the ClickHouse question quotes the stored note; both work-private |
| 44H and mixed requests | `action_boundary.unclaimed` for `delete my tasks`; `action_boundary.mixed` for a read plus "mark them all done"; ordinary chat (`generic_chat`) answered and public |
| Brain | `/brain/summary` total 6, edges 2 |
| Records | all 13 counts identical; tasks (id, text hash, status, sensitivity, created_at), notes, provenance, meetings, reminders and alarms row hashes identical to the saved baseline; revision 029 |
| Core | image `260eab85da2b`, 0 restarts, 0 error lines, flags as above; capture counters after verification `{"attempted":20,"excluded_channel":20}` (probes only); four frozen capture files match inside the running container; hub, PostgreSQL, PgBouncer, vLLM, Caddy, coding-agent and SearXNG (until Part B) not restarted |

One check in my first run reported a failure that was a flaw in the check: one task's title also appears inside the named note's own body, so "the reply contains no task title" is the wrong test. Re-run with precise criteria (the reply starts with the note header, contains the body, has no task-list marker, and the task that is not part of the note is absent) it passed.

**Not exercised in production.** `tasks.capture` and a matching `tasks.complete` would create or change a task, which was not authorised; the legacy `tasks.read` path is not reached while note processing is on (the inquiry answers first); production holds no sensitive-level task, note or reminder, and none was created. The ceiling and label rules for these cases are covered by the 20 regression tests (text, voice, public, work-private, sensitive), which fail on the previous source.

## Part B: SearXNG secret rotation

* Executed the documented procedure with tracing off. A new 64-hex value was generated into a new `0600` file, compared with the old one by `cmp` (differs), kept the bare-value format (mode 600, owner `hariz`, 65 bytes), installed atomically by `mv`, and only the `searxng` container was recreated (`--no-deps --force-recreate`). The value was loaded only inside a subshell from the file; nothing displayed it.
* Verified by hashes, not values: the container's `SEARXNG_SECRET` equals the installed file and no longer equals the previous value. `searxng` is running, 0 restarts, started 13:00:41 UTC (previous start 2026-09-28). `/healthz` from companion-core returned 200 once SearXNG finished starting (my first probe ran a few seconds too early and was repeated). An internal search through the container returned status 200 and 10 results; 2 upstream engines were unresponsive (Google and Brave decline automated requests, as before; unrelated to the rotation). Search was unavailable for the few seconds the container restarted.
* No other container restarted (image id and start time of core, hub, PostgreSQL, PgBouncer, vLLM, Caddy and coding-agent compared before and after).
* The previous value was retired with `shred -u`; the temporary snapshot (container ids and times) was removed; `.env.searxng-secret` remains the only file, `0600`, ignored by git. The previous credential is **revoked**. Past transcripts that contain it were not touched, as instructed.

## Outstanding operational risks

1. **Rollback images hold the disclosure defect** (above). Prefer a forward fix to restoring `pre-privacy-fix` or `pre-router`.
2. `~/reachy-backups/router-rollout-20261011/env.before` is a `0600` copy of the deployment `.env` (it holds credentials, not the SearXNG secret). Keep it only as long as the router rollout needs a rollback reference, then shred it.
3. Past session transcripts and terminal logs contain the old SearXNG value; it is now useless, but treat those files as sensitive for other reasons.
4. The creation and completion ceilings (`tasks.capture`, matched `tasks.complete`) are verified by tests only, not in production, by design.
5. SearXNG's Google and Brave engines throttle; web search quality is as before the rotation.
6. Follow-ups already recorded and not blockers: substring search, titles containing write verbs, unmarked work-knowledge questions.
