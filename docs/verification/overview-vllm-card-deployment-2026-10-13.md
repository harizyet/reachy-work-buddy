# Overview vLLM card, MS-01 deployment record (2026-10-13)

Owner authorization (2026-10-13): "Build and deploy". Commit `913c46e`: core `GET /llm/local-stats` (`companion_core/llm/local_stats.py`), hub proxy, web Overview card "Local model server (vLLM)". No migration, compose or env change.

## What was deployed

| | Before | After |
|---|---|---|
| core image | `df320da58e2f` | `3f792ddf4d35` (tag `vllmcard-913c46e`) |
| hub image | `ca1dd34bcede` | `bb72e8f83964` (tag `vllmcard-913c46e`) |

Built from a clean worktree of `913c46e`. Core was stopped gracefully (`docker stop -t 30`, exit 0, not OOM-killed), then core and hub were recreated with `up -d --no-build --no-deps`. vLLM, Postgres, document-worker, coding-agent and the schema were not touched. Downtime was not timed (well under a minute).

## Phase 48 boundary

The previous segment (core process start 2026-10-12 14:27:44 UTC, Phase 31 trial) ended with counters `{}`; saved in `~/reachy-backups/phase48-boundary-vllm-card/segment-before-vllm-card.txt`. A new segment starts at this restart. No conversation turns were made during the deployment.

## Verification

* Core and hub `/health` 200; no error in core's logs.
* Core `/llm/local-stats` (service token) against the real vLLM: `status ok`, model `reachy-local`, `max_model_len` 8192, 15 finished requests, 30,080 input and 4,103 output tokens, 0 running or waiting.
* Hub `/llm/local-stats` without a login: 401.
* Before deploy: web 293 tests, new core and hub tests, ruff clean (mocked vLLM).

**Not verified:** the card in the owner's browser; the Android app is unaffected.

## Rollback assets (keep until the owner accepts)

`reachy-rollback/companion-core:pre-vllm-card` and `reachy-rollback/reachy-hub:pre-vllm-card`. Rollback: tag each back as `reachy-homelab-companion-core:latest` / `reachy-homelab-reachy-hub:latest`, then `up -d --no-build --no-deps` for those two services (with `SEARXNG_SECRET_KEY` exported from its file).
