# Phase 24d physical conversation acceptance — 2026-09-24

Supervised physical acceptance of [Phase 24d](../phase-24cd.md#phase-24d--physical-end-to-end-acceptance),
following the [24d hardware procedure](../phase-24cd.md#phase-24d-hardware-procedure).
The owner was physically present. Two Claude Code sessions coordinated: one on
the homelab host and one running locally on nano-1. **In progress.**

## Topology and versions

| Item | Value |
|---|---|
| Hub/core host | Homelab, Compose project `reachy-homelab`, Caddy on `:8080`, commit `40ae760` plus the launcher fix below |
| Schema | `006_search_config`, upgraded from `004_persona` after a `pg_dump` backup |
| Robot | nano-1 (`reachy-mini`, Jetson Nano, Tegra 4.9.253), WSS over the tailnet to `http://<homelab>.ts.net:8080/hub` |
| Daemon | `reachy-mini-daemon` 1.8.4, systemd-enabled, running since 13:20:45 UTC, `simulation_enabled=false`; not restarted for this test |
| STT | faster-whisper `base.en`, int8, CPU, in reachy-hub; model pre-loaded before the first timed turn (40 s cold load) |
| TTS | espeak-ng `en-us` in reachy-hub |
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

## Latency budget (agreed before any timed turn)

Utterance end → first audible reply, over the live turns:
**p50 ≤ 4 s, p95 ≤ 8 s.** Agreed with the owner on 2026-09-24 before step 3.

## Results

| Scenario | Result | Evidence |
|---|---|---|
| Normal conversation | — | |
| Turn handling | — | |
| Session continuity | — | |
| Privacy | — | |
| Consent and auth | — | |
| Stop and expiry | — | |
| Recovery | — | |
| Coexistence and sustained use | — | |
| Timing and quality | — | |
