# Note folder tags deployment: migration 030 and coordinated cutover (2026-10-11)

Owner authorization: "deploy" / "i approve and give permission" (2026-10-11), migration `030_note_tags` and the note-folder feature only. Code: commit `db40560`, images built from a clean `git worktree` (`../reachy-work-buddy-deploy-030`, 0 modified files). Feature record: [operator guide, Notes](../operator-guide.md#to-do-reminders-and-notes). **Result: deployed; schema, row counts and health verified; no existing note changed (all 3 untagged).**

| | Before | After |
|---|---|---|
| Schema revision | `029_notepad_processing` | `030_note_tags` (`notes.tag` nullable) |
| core | `260eab85da2b` | `60c024410173` (`notetags-db40560`, started 13:53:26 UTC) |
| hub | `c84eb9aab1e3` | `a3da63b4f497` |
| coding-agent | `3d48b066b1bf` | `197350dbcb4d` |
| migrate | core image | the new core image |
| Row counts (notes 3, tasks 2, reminders 0, meetings 1, memories 1, alarms 9, receipts 13, knowledge_items 85, candidates 0) | stop snapshot | identical (diff-checked) |

Untouched: PostgreSQL, PgBouncer, vLLM, Caddy, SearXNG, router, transcription, diarization, model manager, robot. All Phase 48 and 49 flags unchanged.

## Timeline (UTC, 2026-10-11)

Preflight 13:46 (no scheduled alarm: all 9 cancelled; 0 pending reminders; the one meeting `complete`; 176 GB free). Rollback tags `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-030` verified equal to the running images. **13:47:15 core stopped gracefully** (`docker stop -t 30`: exit 0, not OOM-killed), then hub and coding-agent. Dump with writers stopped, restored into a throwaway container with no network (revision 029, counts equal, container removed). Waited for PgBouncer's idle connections to close (to 13:52:16; PgBouncer not restarted). Migrate ran (`SEARXNG_SECRET_KEY` exported from its 0600 file, never printed): 030 applied. **13:53:25 `up -d --no-build --no-deps`; core and hub answered `/health` at once.** Downtime about 6 min 10 s, of which about 5 min was the PgBouncer wait; no alarm or reminder was affected.

## Phase 48 boundary

New segment ("cohort E") from the core start 13:53:26 UTC. The previous process ran 12:59:20 to 13:47:15 with capture counters `{"attempted":22,"excluded_channel":20,"excluded_handled":2}` (read before the stop; the 20 `excluded_channel` are the earlier probe turns). Selective-shadow file copy at the stop: `~/reachy-backups/phase48-boundary-049/selective-shadow.cohortD-end.jsonl` (3,316 bytes, 0600). The new counters start at `{}`. Code under the frozen capture and knowledge paths is unchanged by this commit.

## Backup and rollback

| Item | Value |
|---|---|
| Dump | `~/reachy-backups/reachy-before-notetags-20261011-214716.dump`, 312,370 bytes, 0600, sha256 prefix `3609ee5b65661a39`, 49 table-data entries, restore verified. Keep until the owner accepts. |
| Row counts | `~/reachy-backups/rowcounts-before-030.txt` |
| Images | `reachy-rollback/*:pre-030` |
| Schema rollback | `deploy/homelab/rollback-030.sql` (drops `notes.tag`; tags are lost, nothing else). Stop core, hub and coding-agent, run it, then start the `pre-030` images. |

## Verification and limits

Verified live: revision `030_note_tags`, column present, counts identical, all three services healthy and on the new image ids, no errors or tracebacks in five minutes of core and hub logs, `GET /notes` returns `tag: null` for the three existing notes, the new web bundle (contains the folder UI) is in the hub image.

**Not verified live:** a write with a tag on the production database (the probe was blocked by the permission classifier and not retried; the write path is covered by the Postgres test on a disposable pgvector database and the route tests); the web UI in a browser; the Android app (needs a new build and install, **not built or delivered**: the phone keeps the old app, which still works because an edit without a tag leaves a note's folder alone). Deployment is not yet accepted.
