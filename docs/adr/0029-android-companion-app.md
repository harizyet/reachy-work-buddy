# ADR 0029: Native Android companion app

- Status: **Accepted 2026-10-07** for [Phase 40](../phase-40.md).
- Date: 2026-10-07

## Context

The web control panel is organised around settings and configuration. The owner wants a user-centred phone client: talk to Reachy by voice or chat, keep notes and a to-do list, and record meetings. [docs/plan.md](../plan.md) listed "full mobile-native applications before the web/PWA workflow is proven" as a non-goal; the owner explicitly chose a native Android app on 2026-10-07, which supersedes that line for this client only.

## Decision

1. **A thin client of the hub's existing owner API.** `clients/android` (Kotlin, Jetpack Compose) calls the same owner routes as the control panel: `/auth/*`, `/status`, `/chats`, `/messages`, `/planner/tasks|notes`, `/meetings`. It adds no endpoints and imports nothing from services. Core stays closed to clients (ADR 0001).
2. **Same auth as the browser.** Owner login with the session cookie and the `X-Reachy-CSRF` header. The password is sent once and never stored; only the hub address, username and session cookie are kept in app-private storage. No key, note, task or transcript is persisted on the phone. The browser-login trust boundary in AGENTS.md is unchanged.
3. **Spoken turns are voice-modality turns.** The Talk button uses the phone's own speech recognizer and sends the text with `input_modality: "voice"`, so destructive-action confirmation stays text-only (ADR 0011). Typed turns join a chat record; spoken turns do not, because the hub archives typed web messages only. Replies may be read aloud with the phone's text-to-speech.
4. **Settings and configuration stay in the web control panel.** The app only signs in and chooses the hub address.
5. **Cleartext HTTP is permitted** because the homelab Caddy has no TLS yet. The intended path is Tailscale (owner decision 2026-10-07): the tailnet already encrypts the traffic with WireGuard, so `http://<tailscale-address>:8080/hub` is acceptable. On a plain LAN the password and session cookie cross the network unencrypted; prefer the tailnet address, and use `https://` if TLS is added.

6. **The app warns when Tailscale is off.** It treats Tailscale as connected when an interface that is up holds an address in 100.64.0.0/10. If not, the sign-in screen shows a warning, signing in over `http://` asks for confirmation, and a dismissible banner shows inside the app until it connects. A non-Tailscale VPN does not count.

## Consequences

- A new client with its own Gradle build and JVM unit tests; no change to services.
- Meeting recording runs in a foreground service (microphone type, partial wake lock, ongoing notification with Stop) so it survives standby and other apps. A clip whose upload fails stays in app-private storage and is retried from the Meetings tab. A phone call or another app claiming the microphone can still interrupt capture, and Android shows its microphone indicator while recording.
- Replies are plain text; no push notifications in this phase.

## Addendum 2026-10-08: scope the app grew into

The app is still a thin client of the owner API, with the same sign-in and the same private-storage rule. What it now does, and what that changes:

- **Screens:** Talk with previous chats, Reminders (To Do and Scheduled), Notes, Meetings (playback, speakers, corrections, titles, outputs) and Alarms, in the Apple Reminders, Notes and Clock styles. It adds no hub endpoint of its own: each new route (`/speech`, `/meetings/{id}/audio`, `PATCH /planner/alarms/{id}`, `PUT /meetings/{id}/title`, `POST /meetings/{id}/describe`, `DELETE /chats/{id}`) is an owner route also used by the web panel, listed in the [services reference](../reference/services.md).
- **Permissions beyond the original:** exact alarms (`USE_EXACT_ALARM`, and `SCHEDULE_EXACT_ALARM` on Android 12), boot completed, vibrate, and the media-playback foreground-service type, for the phone alarm backup of [ADR 0027](0027-alarms-and-presence-gated-delivery.md#addendum-2026-10-07-phone-backup-when-reachy-cannot-play-it). Notifications are requested once (Android 13+).
- **What is stored on the phone besides the connection details:** the ids of the alarms scheduled on the phone, a notifications-asked flag and two switches (read replies aloud, phone alarm backup). Recordings that failed to upload are kept until retried; the meeting recording being played and the last spoken reply are cached in the app's cache directory and replaced on the next use. Still no keys, notes, tasks or transcripts.
- **Background work:** besides recording and deep-review foreground services, a 15-minute job re-syncs the alarm schedule (survives reboot), and a short foreground service runs when a phone alarm fires.
- **Layout:** windows 600 dp wide or more (an unfolded Pixel Fold, a tablet, a phone in landscape) use a navigation rail and two panes; the activity handles configuration changes itself so a fold or unfold does not restart it.
- **Spoken replies** use Reachy's own voice through the hub (`POST /speech`) and fall back to the phone's voice; each reply is read once.
