# Home dashboard verification (2026-10-13)

Branch `feature/home-dashboard`, local only. [ADR 0036](../adr/0036-home-dashboard.md), [Phase 51](../phase-51.md). Mock, in-process, real-chain and emulator evidence are labelled separately; **no physical phone, no production stack, no real Open-Meteo call and no real local model were used.**

## Starting state confirmed
Production runs core `0e962d744772` and hub `b8a5eab5220e` (calendar sync, `69bb9f7`); APK 0.18.0 is built but not installed; `feature/ics-calendar-meeting-reminders` is not merged. The branch point `087f695` adds Android 0.18.1. No migration involved.

## Acceptance table

| # | Criterion | Evidence | Kind |
|---|---|---|---|
| 1 | Home is the default in Web and Android | web `app.test`/`session.test`/e2e `web.spec` land on Home; Android `NavigationTest` default is Home; emulator sign-in lands on Home ([screenshot](home-dashboard-2026-10-13/android-home-top.png)) | unit, browser against real hub+core, emulator |
| 2 | Calendar change visible after the revision updates | `test_home_over_http_follows_the_calendar_revision_and_redacts_busy_events` (generation rises, titles change after a feed refresh) | in-process with the real feed service |
| 3 | Leave and Busy-only classified and redacted | `test_leave_and_busy_only_events_...` (no title, location or detail of a hidden event anywhere in the JSON); web/Android render tests; emulator "Busy" for a CLASS:PRIVATE event with a location | unit, emulator |
| 4 | Open tasks and planner reminders | `test_open_tasks_...`, `test_reminders_split_...` (owner timezone, local-midnight case) | unit |
| 5 | Pending proposals not counted as tasks | `test_pending_proposals_are_counted_as_suggestions_never_as_tasks`; web test; brief lines say "not tasks" | unit |
| 6 | Accepted meeting actions not shown twice | `test_a_confirmed_meeting_action_is_one_task_...`; emulator shows the task once with "From meeting", the pending item once | unit, emulator |
| 7 | Restricted data and counts not exposed | `test_records_above_the_ceiling_...`, `test_a_public_context_gets_no_content_and_no_counts...`, route test with the ceiling header, hub test (sensitive task absent); web "restricted" test | unit, in-process |
| 8 | Weather failure does not affect others | `test_weather_failing_does_not_touch_any_other_section`; emulator with the provider answering 503 showed the stale weather note and every other card intact ([screenshot](home-dashboard-2026-10-13/android-weather-stale.png)) | unit, emulator (scripted provider) |
| 9 | Empty and partial states accurate | `test_one_failing_source_...`, `test_one_review_queue_failing_is_partial_not_a_zero`, `test_features_that_are_off...`, web empty/partial/stale tests | unit |
| 10 | Narrow, regular and unfolded layouts | emulator 720x1440@320dpi (narrow, [shot](home-dashboard-2026-10-13/android-narrow-home.png)), 1080x2400, and 2208x1840@380dpi with the rail and two columns ([shot](home-dashboard-2026-10-13/android-fold-home.png)); web e2e mobile project: no horizontal overflow | emulator, browser |
| 11 | Recording continues through Home | emulator: recording bar and the Meetings badge stay while on Home ([shot](home-dashboard-2026-10-13/android-recording-on-home.png)); structurally the bar and `RecordingService` are outside the navigation | emulator (short check) |
| 12 | Phase 18 endpoints compatible | `test_the_existing_briefing_route_is_unchanged`, `test_phase_18_briefing_is_unchanged_without_home`, existing `test_briefing.py` | unit |

Also checked: the brief route (deterministic, narrative accepted, narrative rejected for an unverifiable time or count, model down, public ceiling never calls the model); hub proxy refused without login, with only a bearer token, or without CSRF on the POST; a core outage is a fixed 502; hostile text renders literally.

## Results
- Core `test_home.py` 40, hub `test_home_hub.py` 6; full `pytest services shared`: 3433 passed, 158 skipped, **4 failed, all known and unrelated** (`test_knowledge_index` reconcile, `test_knowledge_retrieval` historical mode, `test_robot_voice` spoken command, `test_web_client` chat sample). Ruff clean.
- Web: vitest 328 passed (15 new for Home, existing landing tests updated: the status page is now `#/system`), `tsc` clean, Playwright `web.spec` and `brain.spec` 62 passed against the real in-process hub and core on both mounts and desktop and mobile viewports (one new Home test).
- Android: JVM 126 passed (28 new: navigation, Home parsing/merge/state wording/offline line/brief headline, mock-hub `GET /home`, `POST /home/brief`); debug build passes.
- Emulator (Pixel image, API 34) against `clients/android/e2e/android_home_hub_server.py`: a real hub and core with in-memory stores, a loopback ICS feed, a scripted weather provider and seeded tasks, reminders, a sensitive task, a pending note proposal and meeting action. Seen: Home as the landing screen, every card, the brief (plain, no model), tap-through to Reminders, the stale-weather note, the saved copy with its age when the hub stopped, five-item bar and rail.

## Findings
- **Unrelated to this change, present at `087f695`:** on this emulator the bottom navigation bar never appears (also with the unmodified 0.18.1 build) because the 0.18.1 "hide while the keyboard is open" condition (`!imeOpen` in `Shell.kt`) stays true although no keyboard shows. I verified navigation with the condition removed temporarily and **restored it**; the check on a physical phone should confirm the bar is visible, and if not that guard needs another look.
- The legacy Reminders screen counts all open tasks including a sensitive one (3 against Home's 2); it predates this work and was not changed.
- A cold start with the hub unreachable signs the app out (existing `resume()` behaviour), so the offline Home copy applies when the hub drops while the app is open.
- The local model's wording was only exercised with scripted answers.

## Not done
No deployment, APK release or physical-phone check. Weather uses the persona location, which production may not have set yet (the card then says so).
