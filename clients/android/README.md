# Reachy Android companion app

A user-centred phone client for reachy-hub (version 0.14.0): **Talk** (voice and chat, with previous
chats), **Reminders** (To Do and timed reminders), **Notes**, **Meetings** (record, review, play back, edit) and
**Alarms**. Settings and configuration stay in the [web control panel](../operator-ui/README.md).
Decision: [ADR 0029](../../docs/adr/0029-android-companion-app.md); stages:
[Phase 40](../../docs/phase-40.md).

## What it does

- **Talk:** type or speak; replies are read aloud in Reachy's own voice (the phone's voice if the hub cannot speak), once each.
  Chat text is selectable. A history button (a side panel when unfolded) lists saved chats to open, start or delete.
- **Reminders:** an Apple-Reminders-style home with **To Do** and **Scheduled**; round check circles, inline add and rename,
  a collapsed Completed section, swipe left to delete, and a New Reminder sheet (title, date, time). A reminder cannot be reopened.
- **Notes:** a month-grouped list with search; a note opens full screen and its first line is its title; it saves itself.
- **Meetings:** record (survives standby and other apps), a list with titles and descriptions, a transcript with a speaker per line,
  a player (tap a line to play from it), per-line Edit, a warning where the phone captured no audio, editable title and
  description (or written again from the transcript), Summary, Minutes, Use as context, deep-model reruns, delete.
- **Alarms:** an Apple-Clock-style list with switches, Edit and an Add/Edit sheet (time wheels, Repeat, Label, Sound, Volume). The phone also keeps its own
  alarm for each one and rings it when Reachy was offline, found nobody in the room or could not play it, even with the app closed. Menu: **Ring on this phone if Reachy can't**.
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
./gradlew :app:testDebugUnitTest   # 55 JVM tests (mock hub, pure logic)
./gradlew :app:assembleDebug       # app/build/outputs/apk/debug/app-debug.apk
```

## Checking on an emulator

Emulator checks use a throwaway hub with in-memory stores, never the production stack. To see the unfolded layout, switch the emulator with
`adb shell wm size 2208x1840` and `adb shell wm density 380` (the Fold's inner screen) and back with `wm size reset` and `wm density reset`.
Alarm scheduling shows in `adb shell dumpsys alarm`; the emulator has no audio output, so sound is not heard there.
