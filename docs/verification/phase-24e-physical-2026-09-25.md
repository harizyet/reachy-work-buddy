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

## Step 2, block 1: turn handling (2026-09-26, 02:59–03:03Z)

Session `RxDc…`, motion off, hub at `9b84d93` with the model warm.

| Item | Result | Evidence (hub records, embodiment log) |
|---|---|---|
| 20 s of silence | PASS | No turn |
| 15 s of TV, no speech | **FAIL (known limit)** | Turn 1 "I'm off." and turn 2, a 30.0 s capture (the `max_utterance_seconds` cap) of TV dialogue, were both answered. TV speech is speech to the VAD; nothing tells the owner's voice from another until Phase 25's speaker attribution. The owner decided on 2026-09-26 to record this as a known limit deferred to Phase 25, and to retest with non-speech noise |
| Long utterance, ~1.5 s pauses | **FAIL** | "I was wondering..." was correctly held (`continue`), but finalized because no speech resumed within the 1.5 s window, about 2.2 s of real pause after the 0.7 s cut. It was answered "Of course, shoot." "if you could tell me" was spoken during that playback with the mic closed, and was lost. "About the history of..." was held and finalized the same way. "The Eiffel Tower." was answered on its own |
| Short story played to the end | PASS | 20.3 s reply; no turn followed, so no self-hearing |

The cough "Ahem." became turn 3. Fix: the continuation window is now an
owner setting in the hub environment (`da93df9`). The owner chose
**3.0 s** (about 3.7 s of real pause), and the hub was redeployed at
03:13Z with `VOICE_CONTINUATION_WINDOW_MS=3000`. Only trailing-off turns
pay the wait.

### Block 1 retest with the 3.0 s window (03:19–03:22Z)

Session `QOEh…`, hub `da93df9`.

| Item | Result | Evidence |
|---|---|---|
| Non-speech noise, no speech | PASS | No turn in the 54 s before the first question |
| Long utterance, natural ~2 s pauses | **PASS** | One turn from **4 segments**: "I was wondering... If you could tell me... About the history of... The Eiffel Tower." Three were held (`continue`); the fourth was answered directly. Gaps between cuts were 2.56, 3.58 and 2.59 s. First audio came 6.43 s after the last cut, about 7.1 s after the end of speech (LLM 4.67 s on the merged question). No window wait was added after the last segment |
| Short story | PASS | 19.5 s reply, no self-hearing |

**Turn handling row:** PASS for silence, non-speech noise, long paused
utterances and self-hearing. TV speech FAILs as a recorded known limit,
deferred to Phase 25.

## Step 2: deferred 24d rows (not run)

The owner stopped for the day on 2026-09-25 at about 13:50Z, before step 2
started. Nothing in this section has evidence yet. The planned order, with
motion and palm stop off, is:

- **Turn handling, one session:** 20 s of silence (no reply); 15 s of
  background music or TV with no speech (no reply); a long utterance with
  pauses of about 1.5 s ("I was wondering… if you could tell me… about the
  history of… the Eiffel Tower"), expecting one reply built from two or
  more hub segments, which exercises hold and continue; a short story played
  to the end with no self-hearing.
- **Stop and expiry, a new session each:** Stop pressed while the owner is
  still speaking; Stop during inference; Stop during playback, with the
  audible tail measured (≤ 1 s) from `voice stop received` → `daemon audio
  stop returned` in the embodiment log and `stop_sound` in
  `journalctl -u reachy-mini-daemon -o short-iso-precise`; logging out of
  the UI while Reachy listens ends capture.
- **Privacy, one question each, then back to Desk:** Office (not spoken;
  reply to phone or Telegram), Silent (not spoken; reply in web), Desk with
  DND (not spoken), Desk with meeting context if the UI offers it.
- **Consent:** voice cannot confirm a drafted email ("Yes, send it" must not
  send), and a spoken "Reachy standby" must not actuate.

The Session continuity, Recovery and 30-minute rows from
[scope item 3](../phase-24e.md#3-deferred-24d-acceptance-rows) come after
these. Record the UTC time of each action; the hub turn records give the
per-session details.
