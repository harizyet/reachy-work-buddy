# Hybrid intent router: production deployment (2026-10-11)

Owner-approved, core-only, **router enabled at deployment** (the owner directed "deploy with the router enabled", replacing the earlier plan to verify with the flag OFF first). Commit `d7eee35` ([engineering record](intent-router-2026-10-11.md)). No migration, no change to PostgreSQL, hub, coding-agent, vLLM, the robot or any other service. **Result: deployed, every check passed, no record changed.** One finding about an existing handler is recorded under "Findings".

## Before

| | |
|---|---|
| Commit / build inputs | `d7eee35` = `origin/main`; image built from a clean `git worktree` (0 modified files) |
| Schema | `029_notepad_processing` (unchanged by this deployment) |
| Running core | image `1c3290c4d993` (`p49-d34ad51`), started 2026-10-11 10:08:50 UTC, 0 restarts, `/health` 200 |
| Flags (kept as they were) | `KNOWLEDGE_INDEXING/RETRIEVAL/SELECTIVE_SHADOW=true` (log `/data/shadow-router/selective-shadow.jsonl`), `MEMORY_CANDIDATES` and `_CAPTURE=true`, `NOTEPAD_PROCESSING_ENABLED=true`, concurrency 1, `SHADOW_ROUTER_ENABLED=true`; selective answering absent. Added: `INTENT_ROUTER_ENABLED=true` in `deploy/homelab/.env` (mode 600, gitignored; copy of the previous file kept in `~/reachy-backups/router-rollout-20261011/env.before`) |
| Quiet window | no alarm or reminder due in 10 minutes, no meeting processing (the one meeting is `complete`) |
| Record counts | notes 3, tasks 2, reminders 0, meetings 1, memories 1, alarms 9, action_receipts 13, knowledge_items 85, notepad jobs 2, proposals 2, provenance 2, links 0, memory_candidates 0 |
| Record hashes | tasks (id, md5 of text, status, created_at), notes (id, md5 of title and body, updated_at) and provenance rows saved before the stop in `~/reachy-backups/router-rollout-20261011/` |
| Rollback image | `reachy-rollback/companion-core:pre-router` = `1c3290c4d993` (verified equal to the running image before the stop); older rollback tags kept |
| New image | `ef80ad3c7c77` (`router-d7eee35`); the four frozen capture files inside it match the trial log's hashes (`8965cc18…`, `9ef3dec7…`, `c18e810e…`, `6b5cc7a5…`); schema head 029; with no environment the flag defaults to false |

## Phase 48 boundary 4 (cohorts kept separate)

Cohort D (2026-10-11 10:08:51 to 12:27:49 UTC, image `1c3290c4d993`) is closed and cohort E opens at 12:28:36 UTC (image `ef80ad3c7c77`). Read before the stop: capture counters `{"attempted":6,"excluded_channel":5,"no_match":1}` (five of my probes plus one real owner turn that matched no candidate rule; no candidate rows). Graceful stop at 12:27:48 (`docker stop -t 30`, exit 0, not OOM-killed); the selective-shadow telemetry flushed and was copied to `~/reachy-backups/router-rollout-20261011/selective-shadow-at-stop.jsonl` (hourly window 10:00Z: attempted 6, processed 6). Cohort E counters after verification: `{"attempted":16,"excluded_channel":16}`, all on channel `probe-router`, subtracted as deployment probes. Do not merge D and E as one uninterrupted trial.

## Deployment

Image built from the clean worktree before anything stopped; rollback tag created and verified; core stopped 12:27:48; `docker compose -p reachy-homelab --env-file .env up -d --no-build --no-deps companion-core` recreated core only; `/health` 200 at 12:28:39. **Downtime about 50 s, not the usual 7 s**: my first compose attempt failed because `.env.searxng-secret` holds the bare secret rather than a `KEY=value` line, so sourcing it did nothing and the container was not started; I exported `SEARXNG_SECRET_KEY` from the file's contents and ran it again. In diagnosing that I printed the file's first line, so **the SEARXNG secret key appeared once in the session output**. It protects a local search instance and was not sent anywhere, but rotating it is advisable if that transcript is stored or shared (not done). Hub, PostgreSQL, PgBouncer, vLLM, Caddy and coding-agent were not touched (uptimes unchanged).

## Verification (production; probe turns on channel `probe-router`, no record written)

| Check | Result |
|---|---|
| Core | image `ef80ad3c7c77`, 0 restarts, 0 error or traceback lines, flags as listed above plus `INTENT_ROUTER_ENABLED=true` |
| Records | all 13 counts identical to the baseline; tasks, notes and provenance rows byte-identical to the saved hashes; "refactor clickhouse migration" and "spin up gitlab repo" still `open` and unchanged; `/brain/summary` total 6, edges 2 (equal to the provenance rows), revision `029_notepad_processing` |
| `whats my task for next week?` | `tasks.inquiry` (deterministic, no model call): both tasks, stated to be undated, no reminders next week, 1 unprocessed note flagged; privacy work-private |
| `what do I need to do next week?` | `tasks.inquiry`, same reply |
| `what did I write in My Task for next week?` | **`tasks.read`** (the older task-list handler): both tasks, undated, privacy **public**. See Findings |
| `who is my Google on-prem contact?` | `router.memory.recall`, the model's one classification: nothing remembered, then the notes and meetings searched: "I couldn't find a note or meeting that mentions “Google on-prem”." No contact invented. Voice: "I don't have anything stored about 'Google on-prem'.", work-private |
| `what did we decide about ClickHouse?` | `router.records.find`: quoted the note "My Task for next week" (09 Oct 2026) verbatim, the only note that mentions ClickHouse; no summary and no claim that a decision was made |
| `what is a task manager?` | `generic_chat`: an ordinary general answer, no router call |
| `delete my tasks` | `action_boundary.unclaimed`: "I can't perform that action here, so I haven't made any changes." The tasks are unchanged |
| Model calls | vLLM logged 3 completions across the seven questions: two router classifications (the contact and ClickHouse questions) and the one chat answer. The other four needed no model |
| Other functions | "What did I write in the note called My Task for next week?" returned the note verbatim (named-note precedence); "Do I have any reminders?", "show my notes" (GIT; My Task for next week; Reachy Project), "Which notes app is best?" (general answer, not a note list), "tell me a joke" and two voice turns (shared speaker: the tasks question got the restriction message) behave as designed; the one meeting is intact |
| 44H and mixed | "clear my reminders": the 44H reply; "What are my tasks? Also mark them all done.": the mixed refusal naming "mark", no list shown, nothing changed |
| Frozen artifacts | the four capture files match inside the running container; nothing under `benchmarks/`, `knowledge/`, `memory/` changed by this commit |

## Findings

1. **A question about a note that does not say "note" is answered by the older task-list handler, labelled public.** "what did I write in My Task for next week?" contains no word marking it as a note reference, so `record_reference` does not claim it, the 49E inquiry does not match it, and the older `tasks.read` handler lists the open tasks with `classify_privacy(turn.text)`, which labels this reply **public**, so a voice turn could read the task titles aloud. This is existing behaviour (the same path answers "show my tasks" and was live before the router), not the router. The router was not involved and no rollout heuristic was added. Suggested follow-up for a decision: label `tasks.read` replies work-private as the 49E inquiry and the router paths already do, and decide whether a bare "in <existing note title>" should resolve to the note.
2. The compose mistake and the secret echo above.

## Rollback (not needed)

Fast: set `INTENT_ROUTER_ENABLED=false` in `deploy/homelab/.env` (previous file: `~/reachy-backups/router-rollout-20261011/env.before`) and `up -d --no-build --no-deps companion-core` (another core recreate and cohort boundary). Full: `docker tag reachy-rollback/companion-core:pre-router reachy-homelab-companion-core:latest`, then the same compose command with `SEARXNG_SECRET_KEY="$(cat .env.searxng-secret)"` exported. Nothing in the database changed, so no schema step. Keep the tags until the owner accepts.

## Limits

The hub and web client paths were not exercised (core only changed; they forward to unchanged core routes). Probes were sent to core's `/conversation` route with the service token, not through a browser or the phone. Robot behaviour was not touched.
