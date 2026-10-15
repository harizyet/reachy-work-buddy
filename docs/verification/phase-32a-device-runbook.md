# Phase 32A.V: installing the 0.20.0 debug APK and running enrolment and GV on a phone

The homelab side is deployed and waiting ([deployment record](phase-32a-deployment-2026-10-15.md)). No phone has been touched: no device was attached to the build machine, and the APK has not been installed anywhere. You install it yourself.

## 1. The files (build machine, `~/reachy-releases/`)

| File | Use |
|---|---|
| `reachy-companion-0.20.0-voice-identity-aa3e38b-debug.apk` | **Install this.** Built from the clean commit `aa3e38b8de87f71f49c83ef92667231d3bd51508`. sha256 `fc257508042ebe429af8458ceb9b69f1c334ddd71d595eeadf010a92a046ca22` |
| `reachy-companion-0.19.0-tier-tags-debug.apk` | Rollback (the build you accepted). sha256 `9491e5e0f566e9d44abe70a580972771de9e2059c7f9271a3c04c3294c8c3d27` |
| `reachy-companion-0.20.0-voice-identity-debug.apk` | **Superseded; do not use.** It was built from a working tree that also held an unreviewed change to the "start recording" voice-command pattern. The two APKs differ only in two code files (`classes4.dex`, `classes5.dex`), and only the superseded one contains that pattern |

Both 0.20.0 builds are version code 5; Android treats them as the same version, so to switch between them uninstall first (or use `adb install -r -d`). Installing 0.20.0 over 0.19.0 keeps the sign-in; going back to 0.19.0 needs an uninstall or `-d`. Neither adds an Android permission.

## 2. Install

1. Check the file: `sha256sum reachy-companion-0.20.0-voice-identity-aa3e38b-debug.apk` must print the value above.
2. Over USB with debugging enabled and the phone authorised: `adb devices` must list exactly your phone, then `adb -s <serial> install -r reachy-companion-0.20.0-voice-identity-aa3e38b-debug.apk`. Or copy the file to the phone and open it (allow "install unknown apps" for the file manager once).
3. Open the app. If you were signed in under 0.19.0 you still are; if not, enter the hub address (the Tailscale address, `http://100.x.y.z:8080/hub`), your username and password. Tailscale must be connected: this is plain HTTP, and the voice audio travels the same way (outside the tailnet it can be read by others on the network).
4. Rollback: `adb install -r -d reachy-companion-0.19.0-tier-tags-debug.apk` (or uninstall, then install it).

## 3. First checks (two minutes)

Menu (three dots) → **Voice identity**. Expect "Speaker service ready. Not yet calibrated: every result shows as unverified or inconclusive." and "No voice profile yet." If it says the feature is switched off, tell me: the hub flag is on, so the app is probably still talking to a different hub address.

## 4. Enrol your voice

Follow B1 to B10 of the [UAT checklist](phase-32a-uat-checklist.md): record at least five clear clips (read the phrase shown, quiet room), delete any "not usable" clip, tick the consent statement, type your password, **Save voice profile**. **Test my voice** then shows "Owner match: unverified" (never "verified" while uncalibrated). The enrolment and the test clip are the *real* owner profile on the production hub, encrypted; delete it any time from the same screen.

## 5. Voice chat and the other UAT rows

Do sections A, C and D of the checklist (voice mode, the match line, private questions behaving as before, a spoken "send an email" still refused, speaker service down, hub down, the phone-recogniser switch, mic busy during a meeting recording, delete). For Bluetooth, repeat C2 with the phone's audio routed to a headset. For network loss, switch Tailscale off in voice mode: the turn must fail with a message and the mic stops; Unmute after reconnecting. To time the response end to end, say a short question and note the seconds from the end of your sentence to the first word of Reachy's reply (repeat five times; three typical, one long, one with Tailscale on a phone data connection).

To make the speaker service fail on purpose, on the homelab: `docker stop reachy-homelab-speaker-1` (voice chat must continue; the line reads "Voice check unavailable"), then `docker start reachy-homelab-speaker-1`.

## 6. GV collection (separate approval to collect; follow the [protocol](phase-32a-gv-protocol.md))

1. Menu → Voice identity → **Open voice evaluation** → type your password → **Switch on evaluation recording**. The hub stores clips encrypted in `/data/owner-recognition-captures` (a persistent volume).
2. Record each block: 8 enrolment clips, 10 owner quiet, 10 owner noisy, 10 owner **on a later day**, 10 from a **consenting** second person (tick their consent box, alias only), 6 replay probes (play a recording of yourself from another device near the phone), 6 synthetic probes (text-to-speech or voice-converted speech played near the phone). The counters show progress.
3. Run the evaluation on the homelab host (the speaker service has no published port, so use a throwaway container on the Compose network; the password comes from the environment, not the command line):

```bash
cd /home/hariz/reachy-work-buddy-deploy-32a   # or any checkout that has tools/voice_identity_benchmark.py
read -rs REACHY_PASSWORD && export REACHY_PASSWORD
docker run --rm --network reachy-homelab_default -e REACHY_PASSWORD -e PYTHONPATH=/app/services/reachy-hub/src:/app \
  -v "$PWD/tools:/tools:ro" --entrypoint /app/.venv/bin/python reachy-homelab-reachy-hub:p32a-aa3e38b \
  /tools/voice_identity_benchmark.py --fetch http://reachy-hub:8000 --username <your-username> --url http://speaker:8012 > gv-report.json
```

It prints threshold *candidates* with their observed error rates and intervals, and selects nothing. Send me the report (it contains scores, not audio) and I will write it up; the threshold decision is yours.
4. When finished: the evaluation screen → password → **Delete all evaluation clips and switch recording off**, then confirm `GET /owner-recognition/status` shows no voice samples. Delete your voice profile too if you do not want it kept.
