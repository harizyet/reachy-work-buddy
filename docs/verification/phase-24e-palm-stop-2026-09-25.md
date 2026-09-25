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

## Still open

- aarch64 image build on the Nano, and the probe on its Cortex-A57.
- Live frames through the LOCAL camera path during daemon playback, the
  Nano's time per frame, and whether audio stutters.
- Every [item 5 physical row](../phase-24e.md#5-open-palm-stop).
- The `start-reachy.sh` pass-through has only had `bash -n`; `--check` exits
  before it.
