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
