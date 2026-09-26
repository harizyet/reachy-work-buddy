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

## Step 2, block 2: stop and expiry (03:22–03:25Z)

A new session for each item, motion off. Owner: "it all went as
expected".

| Item | Result | Evidence |
|---|---|---|
| Stop while still speaking | PASS | Sessions `_XZq` and `E1t1`: stop received with no utterance cut and no reply |
| Stop during inference | PASS | Session `xOQi`: cut at 03:24:14.712, stop at 03:24:16.671. No reply logged and no playback later |
| Stop during playback | **PASS, 31 ms** | Session `dZh2`: playback started 03:24:37.638. Stop received 03:24:38.369, daemon `stop_sound` 200 at 03:24:38.398 (29 ms), "daemon audio stop returned" at .400. The owner heard it stop promptly |
| Logout while listening | PASS | Session `fMlh`: stop received 3.48 s after start. Hub stop reason "Owner logged out" |

**Stop and expiry row: PASS.** The software stop tail was 31 ms against
the 1 s budget, confirmed by ear. The daemon journal and embodiment log
had no warnings or errors.

## Step 2, block 3: privacy (2026-09-26)

**First attempt, 03:26–03:36Z, in web chat: invalid, and found a defect.**
The owner ran the items by typing in web chat, where a reply always
returns to the chat, so it could not show whether the robot speaker was
withheld. The hub audit log showed Office → phone and Silent → web as
intended. At 03:34:31Z a typed question in Desk mode was classified
work-private. Core carried that label for the whole in-memory
conversation, so every later reply, including the Desk control
"Hello there." by voice, was routed to web. It would have stayed that
way until core restarted.

**Fix:** the owner decided that a carried label expires once its
message leaves the model's 39-message context
([ADR 0006 amendment](../adr/0006-response-routing.md#carried-privacy-expires-with-the-models-context-2026-09-26),
`52fefdb`; core 381 passed). Deployed at 03:41Z; the core restart also
cleared the stuck label.

**Redone by voice, 09:28–09:33Z:** a robot voice session per item, with
the question "What's the capital of France?". Mode and DND were set in the
portal's Session controls card. Meeting context was set and cleared
through `PATCH /sessions/default-user/privacy-context`, since the portal
has no control for it.

| Item | Result | Evidence |
|---|---|---|
| Office | PASS | Session `ainm`: withheld. Audit: office, public, → phone. The owner received it on Telegram |
| Silent | PASS | Session `mPIx`: withheld. Audit: silent → web. Shown in web chat |
| Desk + DND | PASS | Session `44MM`: withheld. Audit: desk → reachy, withheld by DND |
| Desk + meeting context | PASS | Session `VniH`: withheld |
| Desk, normal (control) | PASS | Session `GqLW`: spoken. The question arrived as two segments (a short mid-question pause), held once, with first audio 5.07 s after the last cut |

**Privacy row: PASS** after the carry-over fix. The private-call part of
the row was not exercised. The control turn shows that the 3.0 s window
also holds a short question with a pause in it. That turn was answered
once the second segment arrived, with no window wait; latency is watched
in the 24f timing baseline. Daemon journal: no warnings.

## Step 2, block 4: consent (2026-09-26)

**First run, 09:39–09:41Z (session `gBQE…`): no actuation, but false
claims.** The transcripts were "Drop an email to testanexample.com saying
hello." (STT heard "draft" as "drop"), "Yes, send it.", "Reachy standby."
and "Delete all my emails.". No action ran: core held 0 drafts and 0
received emails, read with the service credential. No mail path is
configured (Gmail not connected, SMTP unset). The daemon stayed `running`
with its motors enabled. Standby got the text-command pointer "Use /reachy
standby." But none of the requests matched core's rigid email intents, so
the model answered them and claimed "Your email has been sent
successfully." and "I'll delete all your emails now." "email" in the
first request marked the conversation work-private, so all four replies
were withheld and appeared only in web chat.

**Fix** (the owner's choice, `c383370`, [ADR 0011 addendum](../adr/0011-destructive-action-consent.md#addendum-no-false-action-claims-2026-09-26-24e-physical-run)):
a deterministic refusal for natural email actions ahead of the model,
spoken as public fixed text. Every generated turn is also told the model
has no tools and must not claim actions. Core 397 passed. The correctness
set has no case the guard catches.

**Rerun, session `kZKo…`:**

| Item | Result | Evidence |
|---|---|---|
| "Yes, send it." | PASS | Fixed refusal, **spoken**; core 7 ms (no model call) |
| "Delete all my emails." | PASS | Fixed refusal, spoken; nothing deleted |
| "Send an email to Bob saying hi." | PASS | Fixed refusal, spoken |
| "How do I send an email?" | PASS | Normal model answer; withheld to web because "email" marks it work-private, as expected |
| "Reachy standby." (first run) | PASS | No actuation; daemon `running`, motors enabled |

Core still held 0 drafts afterwards. **Consent and auth row: PASS**,
including the 401 checks in step 1.

## Step 2, block 5: session continuity (09:54–09:56Z)

Core was restarted at 09:54:08Z, before the first step, to clear a
work-private label carried from block 4. Owner: "all worked as expected".

| Step | Channel | Result | Audit (hub) |
|---|---|---|---|
| "My favourite colour is teal." | Robot voice | Spoken ack | 09:54:50 reachy, public, session `a81c2e86` |
| "What's my favourite colour?" | Web chat | "teal" | 09:55:15 web, same session |
| "And what colour did I say?" | Telegram (bound chat) | "teal" | 09:55:31 telegram, same session |
| "Which colour did I mention earlier?" | Robot voice, new session | "teal", **spoken** | 09:55:50 reachy, same session |

**Session continuity row: PASS.**

## Step 2, block 6: recovery (10:01–10:11Z)

Each item ran against a listening voice session mid-conversation. The
checks were: the session ends with a bounded stop, nothing replays, capture
does not restart by itself, and a new owner-started session works. Clocks
agree: the homelab and the Nano matched within 0.1 s once my own misquoted
times were corrected. Homelab times come from command output and
`docker inspect`; robot times from the embodiment log.

| Item | Result | Evidence |
|---|---|---|
| Hub restart | PASS | Restart issued 10:02:11.5Z. The robot saw WS close 1012 at 10:02:11.588, and voice stopped 26 ms later. It re-registered at 10:02:40.561, about 26 s after the hub was healthy (client reconnect backoff). No capture after reconnect. New session `q8QW` answered |
| Network path (Caddy restart) | PASS | Restart issued 10:04:50.798Z. The robot stopped at 10:04:50.848, and the hub recorded "Robot disconnected". It re-registered 1.3 s later. No capture after reconnect. New session `tHyh` answered |
| Embodiment process restart | PASS | `systemctl restart reachy-embodiment` during `tHyh`. The voice stop came 17 ms into shutdown, and the hub recorded "Robot disconnected". The daemon PID was unchanged. It re-registered at 10:06:20 (about 6 s container stop, then 23.5 s). No capture after. New session `HJwq` answered |
| Microphone/speaker failure | **Not injected (test design error)** | `POST /api/media/release` does not affect voice: the robot's microphone (dsnoop `reachymini_audio_src`) and the daemon's `play_sound` (ALSA `reachymini_audio_sink`) bypass the released media server. Turns kept working. A physical microphone or speaker fault was not injected. The in-process path is covered: a failing microphone ends the hub session with "Microphone unavailable" (`test_voice.py`) |

**Side effect found:** releasing and reacquiring daemon media deletes and
recreates the camera socket. The embodiment container's bind still points
at the old inode, so `/camera/frame` returned 500 ("camera not initialized
yet") after reacquire until embodiment was restarted. Any SDK client using
`no_media` (as the Testbench does) will break the embodiment camera this
way. This follows the known socket-bind behaviour, and a camera
reopen-on-failure would be a robustness improvement. It is not a 24e gate.

**Recovery row: PASS** for hub, network and process interruption. The
physical microphone/speaker fault is **not tested**, with in-process
coverage only. The owner decided on 2026-09-26 to record it this way rather
than unplug the robot's USB, which also carries the motors and camera. The
camera was restored by an embodiment restart (10:14:20, frame 200).

## Step 2: still open

The owner ended testing for the day after block 3 (09:33Z). Not yet run:

- **Palm stop** (item 5, hub `PALM_STOP_ENABLED`), then the 24f motion
  steps, and the 30-minute session last. The 24f steps first need the hub
  and Nano rebuilt with `5c9679d` (portal motion settings).
- **Timing** is still to be measured again with a warm model, in the 24f
  motion-off baseline.
