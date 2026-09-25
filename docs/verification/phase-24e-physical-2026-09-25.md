# Phase 24e physical run (2026-09-25)

**Scope:** the [physical run](../phase-24e.md#implementation-sequence) on
the real robot (nano-1) with the owner speaking, and the Nano-side session
collecting logs. It covers the Normal conversation and Timing rows after
the item 1–2 turn-path changes, the [deferred 24d rows](../phase-24e.md#3-deferred-24d-acceptance-rows)
and the [item 5](../phase-24e.md#5-open-palm-stop) rows. Timing sources are
the ones agreed in 24d ([record](phase-24d-conversation-2026-09-24.md#tts-change-before-the-timed-run)),
computed by [`deploy/reachy/voice-timing.py`](../../deploy/reachy/voice-timing.py).

## Deployed versions

| Component | Version |
|---|---|
| Homelab hub and core | `1e04061` at 13:20Z. Hub `540413e` from 13:46Z (STT/TTS warm-up, below). Schema `008_assistant_context`. Backup `reachy-before-24f-deploy-20260925T131937.dump` |
| Nano embodiment image | `7ecc81f5`, built on the Nano at `d940e27` (13:30Z). No MediaPipe; motion switches off; voice on |
| Daemon | `reachy-mini` 1.8.4, untouched |
| STT / TTS | faster-whisper `base.en` int8 (hub CPU) / Piper `en_US-lessac-medium` |

## Step 1: Normal conversation and Timing (13:35–13:41Z)

Session `mY6s…`: a 15-line script, started and stopped from the UI. Motion
and palm stop were off, and no behaviours were played. The hub recorded
17 turns: the script, plus a misheard repeat and a laugh.

| Turn | Transcript (hub) | Outcome | Utterance end → first audio (s) | STT / LLM / TTS (ms) |
|---|---|---|---|---|
| 1 | Hello Reachy. | spoken | **34.78** | **26524** / 5741 / 1091 |
| 2 | My code word is pineapple. | spoken | 2.29 | 404 / 667 / 184 |
| 3 | I have 3 red blocks and 2 blue blocks. | spoken | 3.35 | 406 / 1468 / 269 |
| 4 | My fictional project is called Zephyr. | spoken | 3.24 | 442 / 1237 / 355 |
| 5 | What's a good way to start the morning? | **withheld** | – | 362 / 1235 / – |
| 6 | What was my court would? (misheard) | spoken | 3.38 | 390 / 1444 / 297 |
| 7 | What was my code word? | spoken ("pineapple") | 3.33 | 355 / 1322 / 361 |
| 8 | How many blocks did I have? | spoken (3 red and 2 blue) | 5.23 | 384 / 1366 / 334 |
| 9 | I was wondering if you could tell me what the difference is between a coil and the flue. | spoken, 1 segment | 6.03 | 509 / 3273 / 697 |
| 10 | What was the project called? | spoken ("Zephyr") | 2.07 | 369 / 357 / 67 |
| 11 | Tell me about a fun thing about octopuses. | spoken | 5.08 | 424 / 2211 / 563 |
| 12 | What's the weather in Jakarta today? | spoken, **searched** | 8.63 | 352 / 6481 / 444 |
| 13 | Thanks. | spoken | 3.27 | 380 / 1644 / 131 |
| 14 | What time is it in Tokyo now? | spoken, no search | 2.87 | 409 / 1019 / 310 |
| 15 | Hahaha. | spoken | 3.26 | 357 / 1834 / 99 |
| 16 | Can you summarize what we talked about? | spoken | 4.22 | 407 / 1778 / 666 |
| 17 | Goodbye for now. | spoken, no search | 1.80 | 405 / 279 / 65 |

- **Timing: FAIL as run.** Non-search, 15 spoken turns: p50 3.33 s, p95
  34.78 s (nearest rank). Turn 1's 34.8 s is a cold start: STT took 26.5 s
  because the hub had been redeployed minutes earlier, and the Whisper model
  downloads and loads on first use. 24d pre-loaded the model before its
  timed run. Without turn 1, the 14 turns give p50 3.27 s and p95 6.03 s,
  within the budget, but that is not a pass. The only search turn took
  8.63 s (budget 20 s, PASS). Fix: `540413e`. The production hub now warms
  STT and TTS in the background at startup; after its redeploy the model
  was on disk before any turn. Timing is measured again in the 24f
  motion-off baseline.
- **Normal conversation: PASS on context, with notes.** Code word
  (after the owner repeated a misheard question), block count and project
  name were all correct. Replies were intelligible; no echo or dropped
  turns. The owner found it "definitely usable", apart from STT hearing
  "cold and the flu" as "coil and the flue".
- **Long utterance:** one reply, but in **one segment**. The pauses were
  shorter than the 700 ms cut, so the hold-and-continue path was not
  exercised. Step 2 tests it with longer pauses.
- **Search rules:** only the weather question searched. "Goodbye for now"
  and "Thanks" did not search ✓. "What time is it in Tokyo now?" did not
  search and got "no real-time data". Under the 24e rules a bare "now"
  is not a freshness cue, so a time question needs an owner decision (24a
  quality, not a gate). The weather query was sent as "What's the weather
  in Jakarta today? in Singapore": a location suffix was appended.
- **Privacy false positive (turn 5):** the question classified as public,
  but the model's reply mentioned "reviewing your schedule". The keyword
  `schedule` labelled the reply work-private, so routing sent it to web and
  the robot stayed silent for that turn. This fails closed as ADR 0006
  intends. Whether reply wording should be able to silence a public
  question is an owner decision.
- **Auth negatives** (checked from the homelab, no robot needed): voice
  start, stop and overview with no token or a wrong token all return 401,
  and a robot upload with a wrong robot token returns 401.
- The hub process logs no `reachy_hub` INFO lines (only uvicorn's). This
  is pre-existing. Hub timings come from its turn records.
