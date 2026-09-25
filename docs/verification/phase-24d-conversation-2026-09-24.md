# Phase 24d physical conversation acceptance — 2026-09-24

Supervised physical acceptance of [Phase 24d](../phase-24cd.md#phase-24d--physical-end-to-end-acceptance),
following the [24d hardware procedure](../phase-24cd.md#phase-24d-hardware-procedure).
The owner was physically present. Two Claude Code sessions coordinated: one on
the homelab host and one running locally on nano-1. **In progress.**

## Topology and versions

| Item | Value |
|---|---|
| Hub/core host | Homelab, Compose project `reachy-homelab`, Caddy on `:8080`. Initial run: commit `40ae760` plus the launcher fix below; later `af27338`, then `0144209` plus uncommitted 24a search follow-ups (2026-09-25) |
| Schema | Initial run: `006_search_config`, upgraded from `004_persona` after a `pg_dump` backup. 2026-09-25: `007_search_providers`, then `008_assistant_context`, each after a `pg_dump` |
| Robot | nano-1 (`reachy-mini`, Jetson Nano, Tegra 4.9.253), WSS over the tailnet to `http://<homelab>.ts.net:8080/hub` |
| Daemon | `reachy-mini-daemon` 1.8.4, systemd-enabled, running since 13:20:45 UTC, `simulation_enabled=false`; not restarted for this test |
| STT | faster-whisper `base.en`, int8, CPU, in reachy-hub; model pre-loaded before the first timed turn (40 s cold load) |
| TTS | Piper `en_US-lessac-medium` in reachy-hub from `4037b4a` (espeak-ng `en-us` for the smoke turns before it) |
| LLM | OVMS `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` (local), routing `local_with_cloud_fallback` to Together `zai-org/GLM-5.3` |

## Preflight (step 1, read-only)

`scripts/start-reachy.sh --check` on nano-1 exited 0: daemon active,
simulation flags false, nothing started. The embodiment container was
`reachy-embodiment:local` `sha256:cc4ad130…`, built from `fefd7f4`
(pre-24c), so step 2 pulled `40ae760` first.

The homelab stack's running images predated 24a–24c and were upgraded first.
The first start through `scripts/start-homelab.sh` crash-looped the hub:
the launcher sourced `.env` with `set -a`, bash quote removal turned the
documented `ROBOT_TOKENS={"nano-1":"…"}` JSON into `{nano-1:…}`, and the
exported variable overrode Compose's own `--env-file` parse. The launcher
now reads `.env` without exporting it (`read_env_file` in
`scripts/lib/common.sh`). After that, the hub started and nano-1 re-registered
over WSS.

## Enable (step 2) and image defect

nano-1 pulled `f5a44a8`, set `VOICE_CONVERSATION_ENABLED=true`, removed the
container and ran `start-reachy.sh --build`. The daemon's main PID was
unchanged throughout. The launcher logged "voice conversation enabled".
The container ran as `1000:1000` (the daemon user), `IpcMode=host`,
`HOME=/tmp/reachy-voice-home`, with `.asoundrc` read-only and the camera
socket mounted. The robot re-registered over WSS.

- The legacy builder rejected the Dockerfile's `RUN --mount` after the old
  container was already removed. `start-reachy.sh --build` now sets
  `DOCKER_BUILDKIT=1`.
- **Defect:** `GET /camera/frame` returned 500:
  `Namespace GstApp not available`. The image installed only the core `Gst`
  typelib, so the SDK's LOCAL media client (used by both the camera and the
  24c microphone) could never start in the container. The pre-24c image had
  no typelibs at all, so the Phase 22c LOCAL camera refactor had never run
  on the Nano either. The Dockerfile now adds `gir1.2-gst-plugins-base-1.0`
  (GstApp, GstPbutils) and `gstreamer1.0-alsa` (`alsasrc`/`alsasink`).
  Checked in a locally built image as UID 1000 with no network:
  reachy-mini 1.8.4, GStreamer 1.26.2, all three namespaces load, and every
  element the LOCAL camera/audio clients create is present. The Nano rebuild
  is the live check.
- **Second defect (arm64 only):** with the typelibs present, the first
  `GET /camera/frame` on nano-1 (image `48868a20…`) killed the embodiment
  process with SIGILL during `Gst.init()`. The external plugin scanner
  failed, so GStreamer loaded plugins in process.
  `GST_DEBUG=GST_PLUGIN_LOADING:6` showed the last plugin was
  plugins-bad's `libgstonnx.so`. The Nano's Cortex-A57 is ARMv8.0 (no LSE
  atomics or dot product). Removing that plugin in a throwaway container
  let `Gst.init()` succeed with all needed elements present. The Dockerfile
  now deletes it after installing the packages. The amd64 build could not
  have caught this.
- **Verified on nano-1 at `101091e`** (image `6870ae7a…`): in a throwaway
  container (UID 1000, no network), `Gst.init()` loaded all 256 plugins in
  process and exited 0. After the container swap, two `GET /camera/frame`
  calls returned 200 with valid 1920x1080 JPEGs (≈400 KB each): 11.4 s cold,
  0.056 s warm. `RestartCount` stayed 0, the daemon PID was unchanged, and
  the hub reported nano-1 `voice_capable: true`. This is also the first real
  run of the Phase 22c LOCAL camera path on the Nano. It is not 22c's
  scene-change acceptance.
- **Known limitation, accepted for now:** GStreamer's external plugin scanner
  cannot start in the container. Docker 20.10.7's default seccomp profile
  returns EPERM (not ENOSYS) for `close_range`, so GLib 2.84's spawn aborts
  instead of falling back. The A/B test against `seccomp=unconfined` confirmed
  this. Plugins therefore load in process: the first media call after a
  container start costs ≈11 s, and a crashing plugin kills the process
  instead of being blacklisted. The fix options are a narrow seccomp
  profile or a newer Docker on the Nano. Neither was done during 24d.
- nano-1's `.asoundrc`: `reachymini_audio_sink` is `dmix` and
  `reachymini_audio_src` is `dsnoop`, both on the Pollen USB audio card, and
  the daemon uses the same aliases. So the SDK client's playback chain shares
  dmix with the daemon instead of taking the device. `pcm.!default` is raw
  `hw` on the same card, so anything that ignores the aliases would conflict.

## First live turns (smoke, not the timed run)

The owner started listening from the operator UI before the coexistence
step, and spoke three turns (hub session `gnsw…`). All three were `spoken`
and heard in the room. The owner stopped the session. The daemon journal
showed one sound upload and `play_sound` per turn through
`reachymini_audio_sink`, with no `stop_sound`, no ALSA/xrun warnings and no
embodiment restart. `/proc/asound/card2` showed capture and playback
held by the daemon's PID, so the container reached the hardware only
through dsnoop/dmix. This was the first microphone → hub → speaker round
trip on real hardware.

Neither side produced per-turn timestamps. The embodiment logged nothing
below WARNING, because uvicorn configures only its own loggers. `1970e85`
added stage durations to the hub's turn records and INFO timing lines to
the robot loop, before the timed run.

## TTS change before the timed run

After the smoke turns, the owner said espeak-ng sounded robotic. Before any
timed turn, and with the owner's agreement, the hub switched to Piper
`en_US-lessac-medium` (`4037b4a`). The voice is baked into the hub image,
pinned to piper-voices commit `c10ece1a` and sha256-checked. espeak-ng
remains the fallback when `PIPER_VOICE_MODEL` is unset. In the built image
with no network, the voice loaded in 1.2 s and synthesized a 2.7 s
sentence in 0.1 s. A slow test round-trips Piper output through
Whisper `tiny.en`. The matrix below therefore measures Piper, not espeak.

Timing sources, agreed instead of a phone recording:
- Utterance end is the robot's "utterance cut" log time minus the 0.7 s
  end-of-speech window.
- First audible is "voice playback started", when the daemon accepted
  `play_sound`. This is a lower bound: the daemon's GStreamer/dmix start-up
  latency is unmeasured.
- Playback end is start plus WAV duration. The logged "done" line includes a
  0.3 s margin, and the 0.4 s tail guard counts toward readiness for the
  next utterance.
- Stop tail runs from the robot's "voice stop received" to the daemon's
  `stop_sound`, taken from `journalctl -o short-iso-precise`, with the
  owner's ear as the check.

## Step 3: device coexistence

Voice session `UdLC…` was already listening when the Nano session triggered
`POST /behaviour/acknowledgement` (recorded `yes1` nod, 3.95 s sound through
dmix). About 1 s later, `GET /camera/frame` returned 200 (412 KB JPEG,
0.084 s) during the move and sound. Capture continued throughout. There were
no ALSA/shm/GStreamer errors, no daemon EBUSY/xrun and no `stop_sound`, and
`RestartCount` stayed 0. The next turn's transcript was the owner's words,
not the behaviour sound. Other observations:

- The daemon's HTTP API stalled for about 2 s while the recorded move
  started. The embodiment's status check timed out and briefly reported the
  backend disconnected, and the behaviour POST took 2.56 s.
- The daemon logged a single "IK error: Collision detected or head pose not
  achievable" mid-nod. This is consistent with the known head offset from
  Phase 22b.
- A 1.15 s pre-behaviour segment transcribed to nothing (`no_speech`).

**Result: PASS**, pending the owner's confirmation that the sound played
fully.

## Conversation privacy carry-over fix

In the same session, a general question about 5G was withheld from the
speaker and routed to web. Every later turn was withheld too. Core's
placeholder keyword classifier matched "medical" in the model's reply,
labelled it sensitive, and the conversation kept its strongest label for
every later reply until core restarted. The owner chose to carry a label
forward only for private data kept in the history:
- deterministic calendar, email, memory and account results;
- the owner's own words matching a sensitive keyword.

A keyword only in the model's wording now labels that reply alone. See
`test_conversation_privacy.py`: the 5G case fails on the old code. The
calendar and own-statement carry-over cases pass on both.

## WS watchdog false positive

At 14:55:58.556 the hub logged "heartbeat watchdog expired" and closed nano-1's
socket (close 4408). That ended voice session `UdLC…` as "Robot disconnected".
The robot's stop ran in 21 ms, and it re-registered at 14:56:06.9. Capture
did not resume on its own, which is correct. The robot's event loop was not
blocked: it served every hub HTTP heartbeat through the window (largest
gap 2.58 s), and its daemon polling was unbroken. The only correlate was a
Tailscale disco path re-validation to the hub at 14:55:58.095. The robot →
hub WS stream most likely sat in TCP retransmit for more than 5 s. That is
inference: there are no packet captures. Host load was moderate (load ~2.3,
781 MB swapped on 4 GB). dmesg showed no USB audio or link events.

The hub's WS watchdog was raised from 5 s to 15 s (ADR 0019 addendum).
The Tailscale endpoint to the hub switches between three LAN addresses every
few minutes. That is a network matter for the owner and was left unchanged.

## Answer quality: web search and the local model

The first attempt at the timed run (session `CnPL…`, 3 turns, stopped by the
owner) gave out-of-date or invented answers: a former US president, a Prime
Minister named as Singapore's President, and "created by Microsoft". Web
search had not run. Migration `006` defaults the policy to `off`, so SearXNG
received no requests. Answers came only from the local
`Qwen2.5-1.5B-Instruct`.

The owner set the policy to **Always** (bundled SearXNG) and kept the local
model. SearXNG's default engine set took ~3 s per query, waiting on Wikidata
timeouts and DuckDuckGo CAPTCHAs. The bundled config now keeps only Google,
Bing and Brave, with Google and Bing enabled (the image disables them), and a
1.5 s per-engine timeout. Six queries then took 0.56–0.86 s and returned
16–20 results each.

End to end through core, with a service-authenticated throwaway session:
- The US question was answered correctly.
- The Singapore question was answered correctly on one run and wrongly on
  another, with results in context.
- Core time was 2.1–4.8 s per turn.
- "Who are you?" was labelled work-private, because the persona prompt's
  "calendar/email" wording is echoed into the reply. It is withheld for that
  reply only.

With grounding, the 1.5B model's accuracy is still inconsistent.

## Search fails from the homelab address; Brave API and spoken form

The owner's first timed attempt (session `Q_UR…`, 5 turns, all spoken)
with policy Always still gave wrong answers: the former US president, and an
invented President of Singapore. Probing SearXNG per engine explained it.
Google and Brave were suspended after CAPTCHAs and rate limits, some of it
probably triggered by this session's own test queries. Bing returned
unrelated pages (dictionary entries for "current"; Netlify sign-up pages
for a telecoms question). The model received junk as grounding and answered
from memory or invented.

Turn 5 generated a long markdown list: 16 s of LLM time, 7 s of synthesis
and 232 s of audio, which the owner stopped after 12.4 s. On the robot, the
stop took **32 ms** from "voice stop received" to the daemon's `stop_sound`.
An earlier stop in session `CnPL…` took 36 ms.

Owner decisions and changes:
- A hosted **Brave Search API** provider (ADR 0022 addendum), with the key
  entered by the owner in the UI.
- VOICE turns now carry a short-plain-reply instruction.
- The hub strips `[S…]` citations and markdown before synthesis.

Verified with fixture transports (request shape, normalization, safe errors,
key masking, core grounding, voice-only instruction), unit tests for
`spoken_text` and the Chromium Web search card. Live Brave calls wait for
the owner's key.

**Motor and reboot incident.** From 15:02:34, `stewart_5` reported
"Overheating Error" continuously while the head held a strained pose (roll
≈25°, yaw ≈−26°). The owner rebooted the Nano, and the daemon reset the
motor on start with no further errors. The reboot exposed a boot-order race:
Docker's `unless-stopped` policy started `reachy-embodiment` before the
daemon, creating `/tmp/reachymini_camera_socket` as a root-owned directory.
The container failed ("not a directory") and the daemon could not start
its media server (`EPERM`). Recovery needs the owner (sudo, then a
supervised daemon restart). A durable launcher fix needs a real reboot to
verify.

## Search-assisted answer quality moved to 24a (2026-09-25)

Hosted search rotation, follow-up search and owner-context work, and the live
multi-turn search check, are 24a follow-up work. Their evidence is in the
[24a record](phase-24a-search-assisted-2026-09-24.md#addendum--hosted-provider-rotation-and-multi-turn-check-2026-09-25).
The 24d formal run uses deterministic context turns plus one or two separate
search-assisted turns, and does not gate on answer accuracy
([rule](../phase-24cd.md#phase-24d--physical-end-to-end-acceptance)).

## Boot-race fix on the Nano (2026-09-25)

Run on the Nano by the Jetson session. The owner ran the sudo, recovery and
daemon steps in person. The Nano's launcher went from `2c332f2` to `6ec05d5`,
then `02f9538`.

**Before (read-only).** The last boot had hit the race again:
`/tmp/reachymini_camera_socket` was an empty `drwxr-xr-x root:root`
directory, and the daemon logged `Failed to initialize media server: [Errno 1]
Operation not permitted`. The container had exited 127 on "not a directory".
It still had the `unless-stopped` policy and a `-v` camera-socket bind.
`start-reachy.sh --check` reported all three and started nothing. The daemon
journal (one volatile boot) had no `stewart_5` overheating error.

**Recovery and install.** In order: `rmdir` the directory, install and enable
`reachy-embodiment.service`, `docker rm -f reachy-embodiment`, then restart
the daemon and run `start-reachy.sh`. Results:

- Socket `srwxr-xr-x reachy reachy`. The daemon started its media server with
  no `EPERM`.
- Container: RestartPolicy `no`. The camera socket is a `--mount` bind
  (`HostConfig.Mounts`); only the voice `.asoundrc` remains in
  `HostConfig.Binds`.
- Both units enabled and active. Daemon active 08:46:12, embodiment 08:46:31
  (WIB). While the container was absent, the unit started twice and failed
  with `No such container`, as expected. It stayed up once `start-reachy.sh`
  had created the container. Embodiment registered with the hub as `nano-1`.
- `GET /camera/frame`: first frame 11.85 s (a 1920×1080 JPEG), after a single
  GStreamer "External plugin loader failed" warning. The next three took
  0.048–0.051 s, so the delay is first-frame warm-up.

**Launcher bug found and fixed (`02f9538`).** With voice enabled, the
`.asoundrc` `-v` bind made `len .HostConfig.Binds` 1. The launcher then took
every container for a pre-fix leftover and recreated it on every run, which
would cut off a live voice session. Only a restart policy or a `-v` bind of the
camera socket counts now. Checked against disposable containers on the homelab
(four cases). On the Nano, `--check` prints `pre-fix (reboot race) container:
no`. A second `start-reachy.sh` run printed "already running" and left the
container ID, `StartedAt` and daemon PID unchanged, with no sudo.

**Cold reboot (owner present): race fixed, but the daemon's wake-up failed.**
Boot at 08:50:00 WIB. After the reboot `timedatectl` showed the RTC and NTP
in agreement (Asia/Jakarta, synchronized; timesyncd synced 08:50:33). The
journal is volatile, so the earlier 23:09 journal-clock skew can't be
examined again.

- Socket `srwxr-xr-x reachy reachy`. The daemon unit started at 08:50:15. The
  embodiment unit waited in `wait-media-socket.sh` and started at 08:50:25.
  The container was reused, not recreated, and started at 08:50:27:
  RestartPolicy `no`, `--mount` socket, `nano-1` generation 2. There was no
  `EPERM` and no manual sudo step.
- Camera: first frame 0.87 s, second 0.052 s. Voice worked with no manual
  step. Turn 11: the hub replied 3.18 s after the cut and playback ended at
  6.01 s. A later `voice_stop` cancelled cleanly. No overheating errors this
  boot.
- **Failure.** `08:50:25 Waking up Reachy Mini...`, then `08:50:27 ERROR -
  Error while waking up Reachy Mini: time value is out of range [0,1]`. The
  daemon status then showed `state: error` and `backend_status.ready: false`.
  In reachy_mini 1.8.4, `time_trajectory` raises this, and the goto loop reads
  the wall clock twice
  (`while time.time()-t0 < duration: t = time.time()-t0`). A preemption
  between the reads can push `t/duration` past 1. The error came about 2 s
  into a wake-up whose first goto is sized at about 2 s, while the embodiment
  container was starting. **Hypothesis, not proven:** an upstream daemon
  timing race made likelier by boot load. The manual restart at 08:46 woke
  normally. On error, `daemon.py` returns before it sets `RUNNING`.
- Minor: `audio-setup.sh` (ExecStartPre, `User=reachy`) falls back to
  `sudo -n alsactl restore` by design, which leaves a "password is required"
  line in the auth log. Voice was unaffected.

**Pose after the failed wake-up.** `/api/state/full` at 02:04:47Z: roll
0.431 rad; x/y/z, pitch and yaw ≈ 0; antennas at home. Home in 1.8.4 is
`INIT_HEAD_POSE = np.eye(4)`, so the first goto had finished. The head was
left in the wake-up's 20°-roll step. No overheating that boot.

**Daemon restart (step 5, owner present).** `sudo systemctl restart
reachy-mini-daemon` at 09:05:32. The embodiment unit waited, then started at
09:05:41. `BindsTo` restarted the same container (new `StartedAt`). Socket
correct. `09:05:40 Waking up...` → `09:05:41 Daemon started successfully.`
State `running`, `nb_error 0`, about 50 Hz. Camera: first frame 6.46 s,
second 0.046 s. `nano-1` generation 3. `backend_status.ready: false` and
`last_alive: null` are not faults: in 1.8.4 `robot/backend.py` sets those
`_status` fields once at startup and never updates them.

**Head does not reach home; mapped nod makes it worse (stopped).** After the
clean wake-up the head settled at roll 0.169, pitch 0.104. Head joints (body
yaw, stewart 1–6): `[0.0015, 0.686, -0.597, 0.624, -0.647, 0.420, -0.514]`.
In 1.8.4 the target pose is not readable over HTTP: the `with_target_*`
parameters are accepted but dropped. The mapped `acknowledgement` behaviour
(`POST /behaviour/acknowledgement`, 02:07:40Z) returned 200. The daemon then
logged `IK error: Collision detected or head pose not achievable!` twice and
settled holding roll 0.307, pitch 0.120, yaw −0.229. Joints:
`[0.0, 1.313, -1.285, 1.127, -1.132, 0.621, -1.083]`.
**`stewart_5` lags the other five Stewart joints each time.** It is the same
motor that overheated on 09-24. A mechanical bind, a stuck or weak
`stewart_5`, or a calibration fault is suspected, not a timing race. The
failed boot wake-up may be a symptom. All motion stopped. Load-off is the
owner's decision:

- torque off (`/api/motors/set_mode/disabled`);
- gravity compensation;
- **not** `systemctl stop`, because its default `goto_sleep_on_stop` makes an
  active move first.

Robot-side 24d work was paused until the hardware was understood.

**Owner assessment: robot physically fine; finding closed.** The owner
checked the robot and found nothing physically wrong. They consider the
pose and IK readings possible false positives, so no load-off was needed
(motors stayed enabled; no overheating at 02:08:55Z). The readings stay
unexplained, not a confirmed fault. **Watch item:** if `stewart_5` lags or
overheats again, recheck the pose readings against the physical head.

**Automatic recovery (owner decision, 2026-09-25).** The daemon stays up in
`state: error` after a failed wake-up, so the owner approved a restart
**at most once per boot**. A second error in the same boot is logged at
`crit`, and the daemon is left alone. Implemented as
`reachy-daemon-recovery.service` +
`deploy/reachy/daemon-error-recovery.sh`
([deployment](../deployment.md#production-unattended-boot-start-owner-accepted-risk-2026-09-23),
AGENTS.md). Homelab test against a fake status server and a stub
`systemctl`, four cases: error → one restart; error again in the same boot
→ no restart, exit 1 plus a `crit` journal line; a restart that errors
again → exactly one restart, then exit 1; an unreachable daemon → nothing.
**Installed on the Nano** at `00a5e68` (09:17:39 WIB). Its `python3` is
3.6.9; the script's status check read `running` from the live daemon.
`enable --now` left the daemon PID (9751) unchanged. The recovery unit is
active with no journal entries and no marker. `--check` reports it
installed, enabled and active. The restart and second-error paths remain
fake-tested only: `state: error` cannot be forced, so the first real proof
will be a boot where the wake-up fails.

## Formal run, attempt 1 (2026-09-25): budget failed, `stewart_5` overheat

**Session A** (`4PQh…`, 02:20:08–02:25:02Z, started and stopped from the
UI). 11 spoken turns and no manual per-turn steps. The embodiment logged no
errors, dropped turns or `no_speech`. The web-search log shows no searches,
so every turn counts as non-search. The script was not fully followed: the
hub records show the Zephyr statement and question were never spoken. Two
deterministic context checks were answered correctly (code word; blocks,
"total of 5"), so **the third check is still owed**. The owner reported
every reply intelligible. They also described off-topic content ("Python
code" for the code word, a blocks tangent); answer quality is out of 24d
scope.

| Turn | Cut (s) | Hub replied after cut (s) | Reply audio (s) | STT / LLM / TTS (ms) |
|---|---|---|---|---|
| 1 | 2.27 | 3.51 | 2.44 | 382 / 2854 / 90 |
| 2 | 1.22 | 1.07 | 1.92 | 369 / 374 / 77 |
| 3 | 2.66 | 1.38 | 3.89 | 379 / 593 / 142 |
| 4 | 2.75 | 10.47 | 59.34 | 389 / 6069 / 1923 |
| 5 | 4.10 | 10.91 | 39.01 | 419 / 8035 / 1143 |
| 6 | 2.43 | 4.81 | 1.56 | 383 / 4152 / 52 |
| 7 | 2.75 | 5.22 | 5.12 | 387 / 4333 / 173 |
| 8 | 3.74 | 5.31 | 7.07 | 411 / 4367 / 224 |
| 9 | 4.29 | 5.16 | 6.20 | 419 / 4146 / 183 |
| 10 | 1.70 | 4.53 | 3.67 | 381 / 3786 / 130 |
| 11 | 3.62 | 11.16 | 47.60 (stopped) | 396 / 7816 / 1516 |

The "hub replied" column is measured from the cut. It has p50 5.16 s and
p95 ≈ 11 s, before adding the 0.7 s VAD tail, so the **non-search budget
fails**. Cause: on turns 4, 5 and 11 the local model ignored the spoken
1–3-sentence instruction (121–162 words, markdown). Those long replies then
stayed in the history and slowed the later short turns (LLM about 4 s,
against 0.4–0.6 s for turns 2–3).

**Fix (`4035e50`, `f353b90`).** Voice turns send `max_tokens=100`, and core
drops a trailing partial sentence (not counting a numbered-list marker)
before the reply is recorded, so generation, speech and history are all
bounded. Typed turns are unchanged. Checked directly against live OVMS: a
long request fell from 9.94 s / 311 words to 2.33 s / 80 words
(`finish_reason: length`). After a redeploy, eight voice turns through the
live core, the deterministic script included, took 0.31–2.49 s. The
longest reply was 61 words, all three context answers were correct, and
every reply ended on a whole sentence. This was a core-only check: robot
playback of the capped replies is not yet measured.

**`stewart_5` overheat.** The daemon logged `Motor 'stewart_5' hardware
errors: ['Overheating Error']` about once a second from 02:20:08Z, the
moment Session A started. Between 02:07 and 02:26 the head drifted (yaw
−0.229 → −0.414, pitch 0.12 → 0.22) with no move command found in the
embodiment or daemon access logs. `stewart_5` was again the outlier joint.
At 02:26:29Z the owner chose torque off
(`/api/motors/set_mode/disabled`). The head stayed where it was, within
0.06 rad per joint, which points to friction or binding rather than sag.
The flag was still reported 3 min later; it may be the servo's latched
error status. Daemon 1.8.4 has no HTTP endpoint for motor temperature or
error registers. `/api/motors/status` returns only the mode, and
`POST /health-check` only resets a keepalive watchdog. The serial port
belongs to the daemon, so the flag can't be read directly while it runs.
Clearing it needs a motor reboot or power cycle, which is the owner's call. This reverses the earlier "physically fine" reading. **Robot
work is paused until the owner has inspected `stewart_5`**, and the formal
run must be repeated: all three context checks, plus Session B.

## Latency budget (agreed before any timed turn)

Utterance end → first audible reply, over the live turns:
**p50 ≤ 4 s, p95 ≤ 8 s.** Agreed with the owner on 2026-09-24 before step 3.
As of 2026-09-25 this budget applies to **non-search** turns. Search-assisted
turns get their own budget: **each search-assisted turn ≤ 20 s** utterance
end → first audible reply. Agreed with the owner on 2026-09-25 before the
formal run. It is a per-turn cap rather than p50/p95 because the run has
only one or two search turns.

## Preliminary timings (not the formal timed run)

Utterance end = robot "utterance cut" − 0.7 s. First audio = robot "voice
playback started" (daemon accepted `play_sound`; a lower bound). Hub stage
times come from the turn records.

| Session / turn | Search | Utterance end → first audio | STT / LLM / TTS (ms) | Reply audio |
|---|---|---|---|---|
| `CnPL` 1 | off | 3.59 s | 419 / 1294 / 385 | 12.2 s |
| `CnPL` 2 | off | 2.51 s | 436 / 767 / 189 | 5.5 s |
| `Q_UR` 1 | Always, SearXNG | 8.29 s | 345 / 4612 / 1042 | 34.2 s |
| `Q_UR` 2 | Always, SearXNG | 6.60 s | 490 / 2957 / 241 | 7.1 s |
| `Q_UR` 3 | Always, SearXNG | 5.86 s | 388 / 2784 / 190 | 5.5 s |
| `Q_UR` 4 | Always, SearXNG | 11.13 s | 345 / 5438 / 1279 | 42.5 s |
| `Q_UR` 5 | Always, SearXNG | 46.13 s | 415 / 16014 / 6983 | 232.5 s (stopped) |

Upload → daemon `play_sound` was 40–47 ms on every turn. The hub received
each upload 114–237 ms after the cut, with one 1.16 s outlier. Most of the
time goes to the LLM, and it grows with reply length. These runs came
before `af27338` (short spoken replies, Brave provider), so they don't count
against the budget.

## Results

Status on 2026-09-25. The formal run still needs ≥10 robot turns with
three deterministic context follow-ups, plus separate search-assisted turns,
and a Nano cold-reboot recovery check after the boot-race fix.

| Scenario | Result | Evidence |
|---|---|---|
| Normal conversation | OPEN | Attempt 1: 11 consecutive spoken turns, UI start and stop, no manual steps, all intelligible; two of three context checks run and correct. Must be repeated after the reply cap and the `stewart_5` fix ([attempt 1](#formal-run-attempt-1-2026-09-25-budget-failed-stewart_5-overheat)) |
| Turn handling | OPEN | Short and long utterances and a `no_speech` segment were handled; no self-hearing seen. Silence, noise and echo not yet exercised deliberately |
| Session continuity | OPEN | Not yet exercised on the robot (the web handoff was only in the 24c simulated run) |
| Privacy | OPEN | Live withholding observed (routing to web). Carry-over fix `c65c9cd`. Modes, DND and private call not yet exercised on the robot |
| Consent and auth | OPEN | Covered off the robot in 24c tests; not yet on the robot |
| Stop and expiry | PARTIAL | Stop during playback: 32 ms and 36 ms from stop receipt to daemon `stop_sound` (the robot-side stop marker came from `1a66f01`). Capture and inference cancellation, logout and expiry not yet run |
| Recovery | PARTIAL | An unplanned WS drop (tailnet stall) ended the session cleanly, with no auto-reactivation and re-registration in 8 s. Hub restarts were recovered by reconnect. The Nano reboot exposed the camera-socket boot race: fix installed on the Nano 2026-09-25 and a live recovery passed ([details](#boot-race-fix-on-the-nano-2026-09-25)); cold reboot and daemon restart pass for the race and container lifecycle, but the head does not reach home, `stewart_5` lags and a mapped nod produced IK errors ([details](#boot-race-fix-on-the-nano-2026-09-25)). The owner found the robot physically fine: finding closed, `stewart_5` on watch. Once-per-boot auto-restart on `state: error` approved, installed on the Nano (restart path fake-tested only) |
| Coexistence and sustained use | PARTIAL | Step 3 coexistence PASS. The 30-minute session is not yet run |
| Timing and quality | FAIL (attempt 1) | Budgets agreed: non-search p50 ≤ 4 s, p95 ≤ 8 s; each search-assisted turn ≤ 20 s. Attempt 1 failed (p50 5.2 s, p95 ≈ 11 s from the cut) on uncapped replies; fixed in `4035e50`/`f353b90`, rerun pending. Preliminary timings above; the formal run is pending |
