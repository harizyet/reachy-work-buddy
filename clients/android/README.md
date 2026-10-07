# Reachy Android companion app

A user-centred phone client for reachy-hub: **Talk** (voice and chat), **To-do**,
**Notes** and **Meetings** (record, upload, read the transcript). Settings and
configuration stay in the [web control panel](../operator-ui/README.md).
Decision: [ADR 0029](../../docs/adr/0029-android-companion-app.md); stages:
[Phase 40](../../docs/phase-40.md).

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
./gradlew :app:testDebugUnitTest   # JVM tests against a mock hub
./gradlew :app:assembleDebug       # app/build/outputs/apk/debug/app-debug.apk
```
