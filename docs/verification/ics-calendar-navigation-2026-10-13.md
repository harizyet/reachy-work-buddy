# Android navigation: four destinations (2026-10-13)

Branch `feature/ics-calendar-meeting-reminders`. The seven bottom tabs (Talk, Reminders, Notes, Meetings, Calendar, Docs, Alarms) became four primary destinations: **Talk**, **Planner** (Calendar, Reminders, Alarms), **Meetings**, **Library** (Notes, Documents). **Local only: nothing deployed, no APK released.** The calendar synchronisation backend, Phase 48 and meeting-analysis extraction are untouched (only Android UI files changed: `ui/Shell.kt`, `data/Navigation.kt`, tests, README).

## Design

* `data/Navigation.kt` (pure): `Primary`, `Section`, `NavState` (the primary destination plus the last screen chosen in each group), `open(section)` for deep links, a string encoding for `rememberSaveable`. No new library: the existing Compose state is enough for a two-level hierarchy.
* `ui/Shell.kt`: Material 3 `NavigationBar` (compact) or `NavigationRail` (width of at least 600 dp, the existing `isWide()`); a `TabRow` of text tabs for Planner and Library, with a content description ("Planner sections"); `rememberSaveableStateHolder` keeps each screen's saved state while another is shown.
* Kept as they were: the activity-scoped `AppViewModel` (so recording state, calendar state and drafts held there are never recreated by navigation), the recording status bar and Deep review / Tailscale banners above every screen, the chat-history drawer (Talk only, gesture only on Talk), each screen's own `BackHandler` and commit-on-leave behaviour, the top-bar menu, the notification, alarm and reminder code.

## Evidence

Emulator (Pixel image, API 34, throwaway hub; sizes set with `wm size`/`wm density`). Screenshots in [ics-calendar-navigation-2026-10-13/](ics-calendar-navigation-2026-10-13/).

| Layout | Size | Result |
|---|---|---|
| Normal phone | 1080x2400 | bar with Talk, Planner, Meetings, Library; Planner shows Calendar, Reminders, Alarms tabs; every screen reached ([planner](ics-calendar-navigation-2026-10-13/normal-planner-calendar.png)) |
| Narrow phone | 720x1280 at 320 dpi (360x640 dp) | four labelled items and three tabs fit without truncation; Planner reopened on the last screen used (Alarms) ([reminders](ics-calendar-navigation-2026-10-13/narrow-planner-reminders.png), [library](ics-calendar-navigation-2026-10-13/narrow-library-documents.png)) |
| Unfolded Pixel Fold | 2208x1840 at 380 dpi | rail on the left, tabs on top, Reminders in its two-pane layout ([reminders](ics-calendar-navigation-2026-10-13/fold-planner-reminders.png), [notes](ics-calendar-navigation-2026-10-13/fold-library-notes.png)) |

Behaviour checks (accessibility tree via uiautomator, as noted):
* Recording kept running while moving Planner, Library, Talk and back to Meetings: the "Recording in progress" bar was present on every screen and the recording service stayed up; Stop and save then uploaded it ([bar on Library](ics-calendar-navigation-2026-10-13/rec-library.png)).
* A note typed but not closed was saved when moving to Planner and back (the existing commit-on-leave); the note appeared in the list.
* The chat-history drawer opens from Talk's history icon on a phone.
* Deep link: the notification's "Start recording" intent while standing in Library, and from a cold start, both landed on Meetings with the meeting prepared and "Nothing is recorded until you tap Record"; no recording service started ([screenshot](ics-calendar-navigation-2026-10-13/deeplink-running.png)).
* Group memory: after Library/Documents and Planner/Alarms, returning to each group opened the same screen.
* JVM: 113 tests, 5 new for the hierarchy (every screen reachable exactly once, secondary navigation only for the two groups, last-screen memory, deep link target and positions kept, save/restore and corrupt state).

## Limits

* Moving between destinations still disposes the screen being left (as the old tabs did; Notes and others rely on that to commit), so a screen's non-saveable local state (a half-typed reminder in a sheet, for instance) is not kept; saved state, the view model and recording are. Making every screen keep unsaved local state would need each to move its drafts out of `remember`, which was not done.
* Back on a primary destination does not return to Talk (unchanged); Back inside a screen behaves as before.
* Not run on a physical phone or a real Fold. Screenshot of the unfolded layout is the emulator's 2208x1840 mode; folding/unfolding live (configuration change) was not exercised.
* Earlier note: an `adb am start` check needs nested quoting for titles with spaces; the first deep-link attempt failed for that reason, not the app.

## Addendum: no obsolete reminder notification after a sync (release criterion)

A notification already showing for a meeting that was later moved, cancelled, declined or removed is now taken down when the phone synchronises (`staleNotifications`: compares what each shown notification announced with the hub's current set; an unchanged meeting's notification is left alone). Before this, only the *pending alarm* was cancelled and a notification already in the shade stayed.
Emulator, throwaway hub: two meetings 6 and 7 minutes out, both notifications showing; one moved 34 minutes later and one cancelled in the calendar. With the app open on the Calendar tab both notifications were gone within about 20 seconds and the moved one was re-armed (21:24). With the app on another screen and in the background, nothing changed until the background check (forced here with `cmd jobscheduler run`; in normal use it runs about every 15 minutes), after which both were gone and the moved meeting's alarm was re-armed. 114 JVM tests (1 new).
