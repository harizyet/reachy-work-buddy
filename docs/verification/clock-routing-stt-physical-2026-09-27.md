# Clock, reply labelling and small.en on the robot (2026-09-27)

**Scope:** the robot checks for `637fcad` (clock answers and reply
labelling) and `c2db3d2` (`STT_MODEL=small.en`), with the owner speaking
to nano-1. The session ran 04:30:20–04:35:04Z and was stopped by the
owner. The owner judged every answer as expected. Stage timings come from
the hub's in-memory turn records (`GET /hub/robot-voice`, owner bearer).
The end-to-end latency comes from
[`voice-timing.py`](../../deploy/reachy/voice-timing.py) over
`~/24f-logs/item2-checks-embodiment.log` on the Nano. No transcripts
or replies are stored here beyond the scripted questions.

## Versions

| Component | Version |
|---|---|
| Hub and core | `c2db3d2`, running since 2026-09-26 15:09Z; `STT_MODEL=small.en`. A 2026-09-27 `--build` was fully cached |
| Nano embodiment | `edb03f5` (`e9df1677`), listening/thinking poses on, wobble off |
| Daemon | `reachy-mini` 1.8.4 |

## Results

| Turn | Question (as transcribed) | Outcome | Search | STT / LLM / TTS (ms) | End of speech → first audio (s) |
|---|---|---|---|---|---|
| 1 | What time is it? | spoken, from the clock | no | 932 / 7 / 127 | 2.22 |
| 2 | What's the date today? | spoken, from the clock | no | 895 / 10 / 118 | 2.13 |
| 3 | What time is it in **2Q** now? (Tokyo misheard) | spoken | yes | 980 / 13288 / 244 | 15.73 |
| 4 | – (1.28 s fragment) | `no_speech` | – | 57 / – / – | – |
| 5 | Is it in Tokyo now? (the owner's repeat) | spoken | yes | 965 / 7029 / 378 | 10.01 |
| 6 | What's a good way to start the morning? | spoken, 66 words | no | 915 / 4034 / 646 | 7.83 |
| 7 | How do I schedule a meeting in Outlook? | spoken, 62 words | no | 933 / 4717 / 687 | 8.00 |
| 8 | My codeword is pineapple. | spoken | no | 923 / 4946 / 642 | 8.35 |
| 9 | What was my code word? | spoken | no | 929 / 4899 / 600 | 7.97 |
| 10 | – (1.22 s fragment) | `no_speech` | – | 60 / – / – | – |
| 11 | I was wondering if you could tell me what the difference is between a cold and the flu. | spoken, 54 words | no | 1064 / 5268 / 644 | 9.86 |

- **Clock (`637fcad`): PASS.** The local time and date came from the
  clock in the owner's timezone (7–10 ms without the model, about 2.2 s
  end to end). Both place-named time questions searched, and the owner
  confirmed Tokyo's time.
- **Reply labelling (`637fcad`): PASS.** "What's a good way to start the
  morning?" was spoken; on 2026-09-25 it was withheld. The Outlook
  question was spoken as public.
- **Mishearings (`c2db3d2`): PASS for the known phrases.** "code word" and
  "cold and the flu" were transcribed correctly. On 2026-09-25 they came
  through as "court would" and "coil and the flue". "Tokyo" was misheard
  as "2Q" once, and the owner's repeat was correct. Proper nouns can
  still fail.
- **small.en cost:** STT median 0.93 s per turn (range 0.90–1.06 s). The
  24e base.en turns were about 0.4 s, so about +0.5 s, which matches the
  [synthetic comparison](stt-model-comparison-2026-09-26.md). The
  2026-09-27 step C run of 22 short questions on the same stack passed at
  p50 3.75 s
  ([record](phase-24f-physical-2026-09-27.md#step-c-rerun-with-silent-poses-passed)).
- **Open-ended questions exceed the 4 s budget.** Turns 6–11 took
  7.8–9.9 s end to end. The local model spent 4.0–5.3 s writing replies of
  54–66 words, and TTS 0.6 s, before the first audio. The budget counts
  non-search turns, so this script alone would fail it (p50 8.0 s over
  its 7 non-search spoken turns). The cause is reply length on the hub,
  not STT or motion. Shorter replies or streaming the first sentence are
  options, and neither is decided.
- **Two `no_speech` fragments** (1.22–1.28 s) were rejected by the hub as
  designed. Turn 4's audio began about 0.8 s after the previous reply
  finished (04:31:05.74Z), close to when the listening pose starts. Turn
  10's began about 5 s after playback ended. The step C run had none, so the cause is open.
  They cost no reply, and the owner didn't report any problem.
