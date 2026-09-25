# Phase 24e open-palm stop: build and in-process checks (2026-09-25)

**Scope:** [item 5](../phase-24e.md#5-open-palm-stop). These checks ran on the
x86_64 development machine only: unit and in-process chain tests, the real
MediaPipe model on two still photos, and the embodiment image built for
amd64. Nothing ran on the Nano or the robot. The aarch64 build, the
Cortex-A57 probe, live camera frames and every physical row are open.

## Choices checked

- **MediaPipe 1.0.1** has a `py3-none` `manylinux_2_28_aarch64` wheel,
  which suits the image's Python 3.13 on Debian trixie. Its gesture
  recognizer has an `Open_Palm` class, so no model training is needed.
- **OpenCV.** MediaPipe requires `opencv-contrib-python`, which installs the
  same `cv2` module as the workspace's `opencv-python-headless`. A root uv
  override drops it. The recognizer gave the same results on the headless
  build. The lock change is additive, and torch stays `2.9.1+cpu`.
- **Model.** `gesture_recognizer.task` from the versioned `float16/1` URL,
  SHA-256 `97952348…2b0482`, the same file as `latest` on this date. It is
  checked at image build.

## Results

| Check | Result |
|---|---|
| Embodiment tests (`pytest services/reachy-embodiment`) | 95 passed, 6 skipped |
| Palm-stop voice tests through the real hub and core (fake watcher) | Reply stopped within 1 s of the palm; next turn answered in the same session; watcher cancelled when a reply ends or a voice stop arrives; unavailable or failing watcher leaves replies playing |
| Watcher unit tests (scripted camera and detector) | Two consecutive hits required; a miss resets; camera errors count as misses; failed probe or load disables it once; detector closed once |
| Crash probe | A child killed by SIGILL, or a missing model, returns False; the parent survives |
| Real model, still photos (`slow` test, not committed) | Wikimedia "Left-palm.jpg" (CC BY-SA 4.0): `Open_Palm` 0.70 → stop. MediaPipe's sample `victory.jpg`: no stop |
| Isolated `uv sync --package reachy-embodiment` | Imports and detects; no contrib OpenCV installed |
| amd64 image build, `--network none` run | First build: probe **failed**, `libGLESv2.so.2` missing. The service stayed up. Added `libgles2`; rebuilt: probe passes, palm detected, victory rejected, 24.9 ms per frame including JPEG decode |

One close-up photo of fingers ("Open Palm of the Left Hand, Fingers") was
classified `None`: the recognizer needs the hand framed, not filling the
image. Distance and framing belong in the physical stop row.

## Detection moved to the hub (same day)

At the owner's direction, detection moved from the Nano to the hub, so the
robot image carries no MediaPipe
([ADR 0023 addendum](../adr/0023-robot-voice-conversation.md#addendum-open-palm-stop-2026-09-25-phase-24e)).
The robot uploads 640 px frames to `ROBOT_PALM_FRAME` during playback,
and the hub answers `stop`. The earlier sections describe the robot-side
version and are kept as history. These checks ran on the x86_64
development machine only.

| Check | Result |
|---|---|
| Hub tests (`pytest services/reachy-hub`) | 204 passed, 10 skipped. Includes the route's refusals: wrong credential 401, other session or generation 409, a turn not playing 409, 257 KB 413, and palm stop off 404. None of these frames is classified. Also covers the stop answer after two consecutive palms, the turn record note, refusal once the robot reports listening, and `voice_start.palm_stop` |
| Embodiment tests | 124 passed, 5 skipped. Includes the robot's uploader over the real hub route in process: stop within 1 s of the palm, then the next turn answered in the same session. No camera reads when the hub has palm stop off. Also covers the 1920 → 640 px downscale |
| Hub image, amd64, `--network none` | First build: the model failed to load, `libEGL.so.1` missing. The embodiment image had it through GStreamer. Added `libegl1`, and `ldd` then reported nothing missing. Pinned model, 640 px palm photo: open palm detected, a blank frame rejected, 25.1 ms per frame including JPEG decode. Frame size 47 KB |
| Embodiment image, amd64 | Builds without MediaPipe, `libgles2` or the model; `mediapipe` not importable; gesture and voice modules import |
| Isolated `uv sync --package reachy-embodiment` | No `mediapipe` in the environment |
| Decoder change (OpenCV → PIL on the hub) | Same results on three photos after the 0.6 threshold. One scores 0.52 either way, below the threshold |

Image sizes: the hub grew from 1.18 GB to 1.92 GB, and the embodiment image
is back to its size before item 5 (3.46 GB, amd64).

## Still open

- Deploying both images: the hub on the homelab, and embodiment rebuilt on
  the Nano without MediaPipe.
- Live frames through the LOCAL camera path during daemon playback, the
  frame round trip, and whether audio stutters. The Lite head camera's
  frames are dark by default (mean about 33/255 in a lit room, 24f
  conformance run), which may affect detection. Pollen's troubleshooting
  suggests enabling auto-exposure priority.
- Every [item 5 physical row](../phase-24e.md#5-open-palm-stop).
- The launcher no longer passes a palm setting; the hub's
  `PALM_STOP_ENABLED` (homelab compose) replaces it.
