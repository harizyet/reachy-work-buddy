# Calendar screens and immediate synchronisation: implementation and verification (2026-10-13)

Branch `feature/ics-calendar-meeting-reminders` (the feature branch deployed on 2026-10-13, [record](ics-calendar-deployment-2026-10-13.md); **not merged to main**). Design: [ADR 0035 addendum](../adr/0035-read-only-ics-calendar-and-meeting-reminders.md#addendum-2026-10-13-calendar-screens-and-immediate-synchronisation). **Built and verified locally. Not deployed to production; no APK released.** The running contract was inspected first: schema `033_calendar_feed`, core/hub images `22b26023e1c7`/`5ada81bd1f98`, routes under `/calendar-feed`; this work extends them and adds no second calendar or source of truth.

## What changed

* Core (`calendar/feed.py`, `feed_store.py`, `routes.py`): one publish path (validate whole, atomic store write, epoch, then revision), `generation` revision, `upload`, `set_url` that validates before storing, single-flight refresh and uploads, epoch guard against an older refresh, `GET /calendar/schedule` (events and status from one state), `PUT /calendar/feed/upload`. **No migration** (the upload is kept in the existing encrypted secret store; revision and source kind live in the existing `status` JSON).
* Hub: owner-session `PUT /calendar-feed/upload` (10 MB cap, raw body, never logged) and `GET /calendar-feed/schedule`.
* Web: Planner > Calendar page, ICS upload in Settings > Accounts, 20-second revision polling.
* Android: Calendar tab (`ui/CalendarScreen.kt`, `data/CalendarScreen.kt`, `CalendarCache.kt`), reconcile on revision change, re-arm stored reminders when the app opens.

## Acceptance cases

| # | Case | Evidence |
|---|---|---|
| 1 | Upload five events, all appear without polling | `test_calendar_sync::test_1`, API test; emulator: upload via the hub, phone showed 5 events, revision 1 and armed 4 reminders (the dentist is not a meeting) within one poll |
| 2 | Replace with three, two disappear | `test_2`; emulator: 3 events, 2 alarms |
| 3 | Move 10:00 to 11:00, reminder rescheduled | `test_3` (same key, +1 h); emulator: alarm moved from 20:18 to 21:18 |
| 4 | Cancel, reminder cancelled | `test_4`; emulator: Sprint planning's alarm removed |
| 5 | Malformed ICS keeps the last snapshot with an error | `test_5`, API test (400 `not_calendar`, nothing echoed), Web test; emulator: state "Last refresh failed; showing the last good copy (cached)", the same 2 events and alarm, error line shown |
| 6 | Valid empty calendar clears events and notifications | `test_6`, API test; emulator: 0 alarms, state ok, no error |
| 7 | Multi-day leave shown correctly, no reminders | `test_7`, Android and Web logic tests (days 19 to 21, not 22); emulator: three marked days (14 to 16) and no leave alarm |
| 8 | Busy-only shows its times and nothing hidden | `test_8`, API, Web and Android tests (title "Busy", interval, no location, no hidden text anywhere in status, schedule, reminders); emulator screenshot: "Busy 19:24–20:24, No reminder: details hidden" |
| 9 | Web and Android converge on one revision | `test_9`; real hub: the web schedule, the status and the phone's reminders all returned generation 7 and fingerprint `d58fa62cc3467012` |
| 10 | Restart, app reopening, duplicates, concurrency, network failure | `test_10a` to `10f` (restart keeps revision and events, the stored upload is re-read; the same upload twice is one revision; identical concurrent uploads share one parse and different ones end as one whole calendar; an older refresh cannot overwrite a newer upload; concurrent refreshes share one download; a network failure keeps everything and recovery does not move the revision); PostgreSQL test (upload stored encrypted, survives a restart); emulator: reopening after a force-stop **found a defect** (force-stop clears every alarm and the phone believed they were still armed): fixed by re-arming stored reminders when the app opens, re-verified (4 alarms back); the hub made unreachable showed "Up to date (cached)", "Not reachable; showing the copy saved on this phone" and the saved events; the phone was cut off, the calendar changed on the hub, and after reconnecting the phone's alarms matched the new calendar; five concurrent refreshes plus three identical uploads against the live hub ended as one calendar and one revision step |

## Suites

Python calendar suites 226 passed (classification 37, fetch 75, feed 30, API 25, **sync 19 new**, intent 12, hub 22, PostgreSQL 7 on a disposable `pgvector` container), ruff clean. Web 313 passed (14 new for the Calendar page and upload), `tsc` clean. Android JVM 108 passed (10 new, including parsing of the real schedule payload). Earlier tests whose meaning changed were updated: a link is now stored only after it downloads and validates.

## Not verified / limits

* A physical phone, and the Web page in a real browser (jsdom only). Emulator checks used the throwaway hub (`clients/android/e2e/android_calendar_hub_server.py`) with the local-fixture switch; the real calendar URL was not used.
* No push: the phone follows within about 20 seconds only while its Calendar tab is open, otherwise at app open, restart and the 15-minute job. A cold start with the hub unreachable still shows the sign-in screen (existing behaviour); the saved calendar appears when the hub drops while the app is open.
* Android cannot upload a file (the Web can). Several tabs now make the bottom bar tight on narrow screens (seven items).
* **Production is unchanged** (core `22b26023e1c7`, hub `5ada81bd1f98`, schema 033). Deploying this needs core and hub images only (no migration) and a new Phase 48 cohort boundary, on separate owner approval; the APK needs a release approval.
