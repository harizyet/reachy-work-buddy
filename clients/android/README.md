# Reachy Android companion app

A user-centred phone client for reachy-hub (version 0.17.1): **Talk** (voice and chat, with previous
chats), **Reminders** (To Do and timed reminders), **Notes**, **Meetings** (record, review, play back, edit) and
**Documents** and **Alarms**, grouped under four destinations (below). Settings and configuration stay in the [web control panel](../operator-ui/README.md).
Decision: [ADR 0029](../../docs/adr/0029-android-companion-app.md); stages:
[Phase 40](../../docs/phase-40.md).

## Navigation

Four primary destinations: **Talk**; **Planner** (Calendar, Reminders, Alarms); **Meetings** (recording, history, analysis); **Library** (Notes, Documents). A bottom `NavigationBar` on a phone, a `NavigationRail` from 600 dp wide (an unfolded Fold, a tablet, landscape). Planner and Library show their screens as labelled text tabs under the app bar and each remembers the screen that was open when you come back to it. The structure is plain Compose state (`data/Navigation.kt`, tested on the JVM; no navigation library). Recording, its status bar, the chat-history drawer, notification actions and alarms are unaffected by moving between destinations. A meeting reminder's **Start recording** opens Meetings with the meeting prepared. Evidence: [navigation record](../../docs/verification/ics-calendar-navigation-2026-10-13.md).

## What it does

- **Talk:** type, or tap the voice button for a full-screen voice mode (an animated ball, hands-free: it listens, sends, speaks the reply, then listens again; a voice-source choice, Mute and Close buttons). Replies are streamed and read aloud in Reachy's own voice (the phone's voice if the hub cannot speak), once each.
  Chat text is selectable. A history button (a side panel when unfolded) lists saved chats to open, start or delete.
- **Reminders:** an Apple-Reminders-style home with **To Do** and **Scheduled**; round check circles, inline add and rename,
  a collapsed Completed section, swipe left to delete, and a New Reminder sheet (title, date, time). A reminder cannot be reopened.
- **Notes:** a month-grouped list with search; a note opens full screen and its first line is its title; it saves itself.
- **Meetings:** record (survives standby and other apps), a list with titles and descriptions, a transcript with a speaker per line,
  a player (tap a line to play from it), per-line Edit, a warning where the phone captured no audio, editable title and
  description (or written again from the transcript), Summary, Minutes, Use as context, deep-model reruns, delete.
- **Documents:** the owner's document library ([Phase 50](../../docs/phase-50.md)). Upload a PDF, DOCX, PNG or JPEG through Android's own file picker (the app is given only the file you choose);
  a list with status that refreshes while a document is being read; rename, classification (public, work private, sensitive), project and delete; **Ask**, **Search** and **Summaries** for one document;
  *Read more carefully* to read the original again at the next extraction level; and **Inspect**: a page at a time, a toggle between MinerU's picture of the original (with its blocks outlined, tap one for
  its type, position and MinerU's own crop) and the extracted text with tables. Chat has a document button: choose a ready document and typed messages in that chat are answered from it, with the pages
  named; **Replace** and **Remove** change it. The attachment is the hub's record of the chat, so it survives restarts and shows on the web too. A document chosen before the first message is saved with the chat before anything is sent.
  The phone never claims an owner or a privacy ceiling; the hub decides what a chat may draw on.
- **Alarms:** an Apple-Clock-style list with switches, Edit and an Add/Edit sheet (time wheels, Repeat, Label, Sound, Volume). The phone also keeps its own
  alarm for each one and rings it when Reachy was offline, found nobody in the room or could not play it, even with the app closed. Menu: **Ring on this phone if Reachy can't**.
- **Meeting reminders** ([ADR 0035](../../docs/adr/0035-read-only-ics-calendar-and-meeting-reminders.md)): a notification before each meeting from the owner's calendar feed, with **Start recording** (opens Meetings with the meeting prepared; never starts the microphone) and **Dismiss**. Scheduled on the phone, so it works offline and after a restart; the Meetings tab lists the next 3 days with the hub's classification and says what blocks delivery. Menu: **Meeting reminders**. Calendar titles are kept in app-private storage and removed on sign-out. `e2e/android_calendar_hub_server.py` is the emulator fixture.
- **Calendar** (tab): month with markers, the selected day's agenda in the phone's time zone, upcoming meetings, and a sync card showing the source's last refresh and the phone's last check of the hub separately, the event count, revision, last error and a cached indication (the last answer is kept on the phone). **Refresh** asks the hub to re-read the source and reconciles the phone's reminders straight away; the tab re-checks every 20 seconds while open. Busy-only entries show "Busy" and their interval only.
- **Pixel Fold and tablets:** at 600 dp or wider the bottom bar becomes a rail and Notes, Meetings, Reminders and Talk show two panes.
  Folding or unfolding re-lays out in place without restarting.

Permissions: microphone, notifications (Android 13+), exact alarms, boot completed (to re-schedule alarms), vibrate, and foreground services
for recording, deep review and the phone alarm. Force-stopping the app in Android settings stops its alarms until it is opened again.

## Use

Install the debug APK, enter the hub address (for example
`http://100.x.y.z:8080/hub` using the homelab's Tailscale address), the owner username and password. The password
is sent once (Tailscale encrypts the plain-HTTP hop; avoid typing it over an untrusted LAN); only the address, username and session cookie are kept on the
phone. Spoken messages are sent as voice turns, so destructive actions still
need a typed confirmation.

If Tailscale is not connected the app warns on the sign-in screen, asks before
signing in over plain HTTP, and shows a banner inside the app.

## Build

Needs JDK 17 and the Android SDK (platform 35, build-tools 35.0.0). Set
`sdk.dir` in the gitignored `local.properties`.

```bash
./gradlew :app:testDebugUnitTest   # 77 JVM tests (mock hub, pure logic)
./gradlew :app:assembleDebug       # app/build/outputs/apk/debug/app-debug.apk
```

## Checking on an emulator (documents)

`clients/android/e2e/android_hub_server.py` is a throwaway hub with a real core, a disposable real PostgreSQL and a real document worker (see its docstring); reach it with `adb reverse`.
The Documents checks of 2026-10-12 used it; see the verification record linked from [Phase 50](../../docs/phase-50.md#32-android-scope).

## Checking on an emulator

Emulator checks use a throwaway hub with in-memory stores, never the production stack. To see the unfolded layout, switch the emulator with
`adb shell wm size 2208x1840` and `adb shell wm density 380` (the Fold's inner screen) and back with `wm size reset` and `wm density reset`.
Alarm scheduling shows in `adb shell dumpsys alarm`; the emulator has no audio output, so sound is not heard there.
