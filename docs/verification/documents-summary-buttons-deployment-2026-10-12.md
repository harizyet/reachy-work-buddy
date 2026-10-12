# Documents summary buttons: hub-only redeploy (2026-10-12)

Owner request: "yes build and deploy" (2026-10-12) for the fix in commit `b990d6a` (branch `fix-documents-summary-buttons`, stacked on the unmerged Phase 31 branch): the style buttons in a document's Summaries choose which summary is shown and write one only when that style has none. Android 0.17.1 (`~/reachy-releases/reachy-companion-0.17.1-debug.apk`, delivered by hand) has the same fix. **Result: hub redeployed; verified; no rollback.**

| | Before | After |
|---|---|---|
| hub | `af30ec4c0a1e` | `667eb6e31709` (tag `docfix-b990d6a`, built from a clean worktree of `b990d6a`, 0 modified files) |
| core, coding-agent, PostgreSQL, schema (`032_meeting_analysis`) | | unchanged (core still `df320da58e2f` started 14:27:42) |

Rollback image: `reachy-rollback/reachy-hub:pre-docfix` (= `af30ec4c0a1e`, verified equal to the running image before the build). Preconditions 15:10 UTC: nothing due in 30 minutes, no hub traffic in the last 5 minutes, 0 analysis runs. Hub stopped gracefully 15:11:19 (exit 0, not OOM-killed), `up -d --no-build --no-deps reachy-hub`, healthy 15:11:24: about 5 seconds without the hub. No schema change, so no dump. The core was not restarted, so the Phase 48 segment (from 14:27:44 UTC, counters `{}`) is unchanged.

Verified: hub `/health` 200 and `/web/` 200; the new bundle is inside the running hub (contains "Summary style" and "No summary yet. Choose a style"); the hub environment fingerprint (31 variables) is identical before and after; no error in the logs; owner routes still answer 401 without a session; `MEETING_ANALYSIS_ENABLED=true` in core and 0 runs and 0 items. **Not verified:** the Documents screen in the owner's browser (hard-reload the page once so the browser fetches the new bundle), and the Android app until 0.17.1 is installed.

Rollback: `docker tag reachy-rollback/reachy-hub:pre-docfix reachy-homelab-reachy-hub:latest`, stop the hub, `up -d --no-build --no-deps reachy-hub`.
