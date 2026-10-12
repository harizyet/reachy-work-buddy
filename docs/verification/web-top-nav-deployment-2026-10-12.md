# Web top bar dropdowns: hub-only redeploy (2026-10-12)

Owner request: "build and deploy" for commit `b1b2856`: the web top bar is one row (Overview, Chat, Settings, plus Library, Planner and Assistant dropdowns). **Result: hub redeployed; verified over HTTP; no rollback.**

| | Before | After |
|---|---|---|
| hub | `667eb6e31709` | `ca1dd34bcede` (tag `topnav-b1b2856`, built from a clean worktree of `b1b2856`) |
| core, coding-agent, PostgreSQL, schema | | unchanged (core not restarted, so the Phase 48 segment is unchanged) |

Rollback image: `reachy-rollback/reachy-hub:pre-topnav` (= `667eb6e31709`). No hub traffic in the previous 5 minutes. Hub stopped gracefully and recreated with `up -d --no-build --no-deps reachy-hub` at about 23:00 UTC; `/health` 200 after 4 s. No schema change, so no dump.

Verified: `/health` 200, `/web/` 200, the running hub's bundle contains the new menu labels, no errors in the logs. Unit tests (290) and the build passed before deploy. **Not verified:** the bar in a real browser (hard-reload once), and the Playwright specs, which were updated but not run.

Rollback: `docker tag reachy-rollback/reachy-hub:pre-topnav reachy-homelab-reachy-hub:latest`, stop the hub, `up -d --no-build --no-deps reachy-hub`.
