# Phase 24g wake-detector and acoustic-filter cost on the Nano (2026-09-27)

**Scope:** the target-hardware measurement that
[Phase 24g](../phase-24g.md#decisions-resolved-2026-09-27) requires
before choosing a wake detector and acoustic-event filter. It is a
file-driven benchmark: no microphone, daemon, hub or motion took part, and
it says nothing about detection accuracy in the room. The tool is
[`wake-bench.py`](../../deploy/reachy/wake-bench.py). It ran in a throwaway
`--rm --network none` container of the deployed embodiment image, with the
bench directory mounted read-only, alongside the running daemon and
embodiment.

## Setup

| Item | Value |
|---|---|
| Host | nano-1, Jetson Nano (L4T R32.7.1), 4× Cortex-A57, 3.9 GB RAM; about 72% CPU idle before the run |
| Runtime | `reachy-embodiment:local` (`0ab5ebdf`), Python 3.13, onnxruntime 1.27.0 CPU, one inference thread per stage |
| Wake candidate | openWakeWord 0.6.0, ONNX: `melspectrogram.onnx` (`ba2b0e0f`), `embedding_model.onnx` (`70d16429`) from release v0.5.1. The pretrained `hey_jarvis_v0.1.onnx` (`94a13cfe`) stands in for a custom "Hey Reachy" head; the architecture and cost are the same |
| Event filter candidate | YAMNet, Qualcomm AI Hub ONNX float export v0.63.0 (`d4459cb7`, weights `0b4de0b1`), AudioSet's 521 classes. The log-mel front end is computed in NumPy with YAMNet's published parameters |
| Clips | 16 clips at 16 kHz: 12 from ESC-50 (3 each of cough, sneeze, laughter, breathing; CC BY-NC, used locally, not committed) and 4 Piper `en_US-lessac-medium` phrases. Each clip was streamed 3 times |

## Results

| Stage | Call | p50 | p95 | max | CPU |
|---|---|---|---|---|---|
| Wake, continuous | one 80 ms chunk | 18.9 ms | 20.6 ms | 27.2 ms | 23.3% of one core (≈6% of the Nano), all the time while armed |
| Event filter, per candidate | one 0.96 s patch (0.48 s hop) | 29.2 ms | 30.2 ms | 34.5 ms | 12.3% of one core over the audio classified; log-mel 5–34 ms per clip |

Memory: loading the wake models added about 36 MB of peak RSS. The whole
bench process peaked at 239 MB, most of it the openWakeWord package's
scipy/scikit-learn imports. On the dev box, YAMNet added 27 MB. The Nano's
peak-RSS reading could not isolate YAMNet's share.

**Wiring check** (the scores matched the dev box exactly):
- The "Hey Jarvis" head scored 0.997 and 0.998 on the two "Hey Jarvis …"
  phrases.
- It scored 0.000 on "Hey Reachy …" and on unrelated speech.
- It scored at most 0.287 on the laughter, sneeze, cough and breathing
  clips.

YAMNet ranked Speech first on every TTS phrase. It put Breathing, Gasp or
Snort in the top three for the breathing clips, and Cough or Sneeze in the
top three for five of the six cough and sneeze clips. Laughter clips mostly
came out as Speech or Chuckle.

## Edge Impulse "Hey Reachy" model

The owner pointed to a community "Hey Reachy" model: the Hugging Face
Space [`luisomoreau/hey_reachy_wake_word_detection`](https://huggingface.co/spaces/luisomoreau/hey_reachy_wake_word_detection)
(revision `3b667074`). It is an Edge Impulse `.eim`, a native runner
executable driven over a Unix socket. Its source project is
[public on Edge Impulse](https://studio.edgeimpulse.com/public/855375/latest)
under BSD-3-Clause-Clear, and its data items are CC0. The author reports
about 2.5 h of synthetic Kyutai TTS training data and says it is not
product-grade.

The aarch64 build (`9861b8d4`, 13.6 MB, needs glibc ≤ 2.27) ran in the
same kind of throwaway container, with `--network none`. It has three
labels, `hey_reachy`, `noise` and `other`. It classifies a 2 s window at
24 kHz, stepped by 0.5 s, as the Edge Impulse SDK does.

| Measure | Value |
|---|---|
| Runner-reported DSP + classification | 14 ms per call |
| Round trip with JSON over the socket | 41–43 ms p50, 45–49 ms p95 |
| Runner CPU | 2–4% of one core |
| Runner peak RSS | 42 MB |
| Negatives (the 16 clips above) | `hey_reachy` at most 0.43, a sneeze; 0.000 on "Hey Jarvis" phrases |
| "Hey Reachy" recall, 15 Piper clips (5 voices × 3 phrasings), 16 kHz path | 4 of 15 at or above the demo's 0.7 threshold (two voices); 5 of 15 at 0.5 |
| Same clips resampled straight to 24 kHz | Scores similar; the 16 kHz band limit is not the main loss |

The robot's microphone path is 16 kHz (`dsnoop` and the voice contract), so
the 16 kHz row is the realistic one. Synthetic Piper voices are not human
speakers, so this recall says nothing definite about the owner's voice. It
does show the model generalises poorly beyond the TTS voices it was trained
on. The JSON socket protocol accounts for most of the round trip.
Driving it through the Edge Impulse SDK would use shared memory instead,
but that SDK imports pyaudio.

## Live microphone session with the owner

On 2026-09-27, 06:18–06:25Z, the owner spoke to nano-1 while `wake-bench.py
--listen` scored the robot microphone. The tool read the shared
`reachymini_audio_src` dsnoop device through a record-only GStreamer
pipeline, at 16 kHz. It ran in a throwaway container with no network, and
it kept no audio. Nothing moved or played, and the daemon reported
`stopped` throughout. The thresholds were 0.5 for both models. YAMNet
labelled sounds above −32 dBFS.

| Stretch (UTC) | What the microphone heard | Detections |
|---|---|---|
| 06:18:05–06:22:55 | Continuous speech (YAMNet Speech about 50 times per 30 s) | Edge Impulse `hey_reachy` 7 times, 0.51–0.96 |
| 06:23:14–06:23:18 | Speech | `hey_reachy` twice (0.64, 1.00) |
| 06:23:31–06:23:40 | The owner's "Hey Jarvis" control | openWakeWord `hey_jarvis` 3 of 3 (bursts 0.64–0.99, peak 0.996) |
| 06:23:50–06:24:40 | Speech | `hey_reachy` 10 times, mostly 0.76–1.00 |
| 06:24:40–06:25:15 | Cough, sneeze, quiet | none; YAMNet labelled the cough and sneeze |

- The control passed, so the live microphone path is valid.
- `hey_jarvis` stayed at 0.04 or below apart from the control attempts, and
  "Hey Reachy" never triggered it.
- Nothing triggered `hey_reachy` except during speech.
- The owner did not say which of the first stretch's 7 detections were
  their own attempts. They are **unattributed**, not counted as hits or
  as false wakes.
- The listener used about 52% of one core, plus 5% for the Edge Impulse
  runner. That is with all three models and with OpenBLAS pinned to one
  thread. Unpinned, it used about 110%.

**Owner decision (2026-09-27):** the owner judged the detection
acceptable. The Edge Impulse "Hey Reachy" model is 24g's initial wake
detector. False wakes per hour and recall at distance are still measured
formally at [24g acceptance](../phase-24g.md#verification-and-exit-criteria),
behind the admission gate.

## Interpretation

- **Continuous wake monitoring fits.** At 80 ms per step, 19 ms of work uses
  about a quarter of one A57 core. That leaves most of the Nano free, but
  it is a standing cost whenever monitoring is armed.
- **The event filter adds little latency if it runs while the candidate is
  still being captured.** Each 0.96 s patch costs 30 ms, and a new patch
  becomes available every 0.48 s. After the segment is cut, only the last
  patch remains, adding about 30 ms. Classifying a 10 s candidate only after
  the cut would add about 0.6 s.
- **Laughter is weak in YAMNet's ranking** (mostly Speech or Chuckle), and
  one sneeze came out as Cough. Relying on YAMNet's top class alone would
  admit some laughter. Thresholds for the Speech score against the
  non-speech classes need calibration on room audio from the robot's
  microphone.

## Limitations and open items

- The Edge Impulse model's recall on synthetic voices is low. The live
  session is the relevant evidence for real voices, but it is a single
  informal session. The openWakeWord pretrained head
  does not respond to the phrase (0.000), so openWakeWord needs a head
  trained on synthetic speech. Porcupine was not measured: it needs a
  Picovoice access key from the owner.
- Only file-based cost and wiring. Room detection accuracy, the false
  wakes per hour and the microphone path (dsnoop via the SDK) are not
  tested.
- ESC-50 clips are clean recordings, and the TTS phrases are synthetic,
  not the owner's voice.
