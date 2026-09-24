# Phase 24c robot conversation verification — 2026-09-24

Implementation of [Phase 24c](../phase-24cd.md#phase-24c-audit-result-2026-09-24)
per [ADR 0023](../adr/0023-robot-voice-conversation.md). Everything below ran
**off the robot**. The microphone was a simulated fixture source replaying
synthesized WAVs. No Nano, daemon, physical microphone or speaker was used,
and nothing here counts towards [Phase 24d](../phase-24cd.md#phase-24d--physical-end-to-end-acceptance).
Base commit `49771dc` plus the Phase 24c working-tree changes.

## Automated suites

| Check | Result |
|---|---|
| `pytest services shared` (including `slow`, espeak on PATH) | 503 passed, 16 skipped (Postgres-gated tests without `DATABASE_URL`) |
| `ruff check services shared` | Clean |
| `node --test clients/operator-ui/tests/*.cjs` (Chromium) | chat, accounts, websearch and new voice suites pass |

New or changed tests:

- `services/reachy-hub/tests/test_robot_voice.py`:
  - Controlled-clock lifecycle: capability gate, start/idempotence, lease
    lapse, maximum duration, idle timeout, fencing, and generation-specific
    disconnect.
  - A stop during a turn discards the late reply and never synthesizes it.
  - In-process chains: robot WSS (TestClient) → owner start → robot upload →
    real companion-core. Covered: multi-turn context with a web-chat
    handoff; Office, work-private, DND and meeting withholding with no TTS
    call; spoken `/reachy standby` not actuating; 401/409/413/422 upload
    bounds; owner auth, CSRF and logout stop; robot-reported stop/error.
  - Real faster-whisper `tiny.en` plus espeak through the upload route
    (`slow`).
  - Regression test: first-use model loading must not block the event loop.
- `services/reachy-embodiment/tests/test_voice.py`:
  - Segmenter (pre-roll, click drop, maximum-length cut) and real Silero VAD
    on synthesized speech.
  - Streaming-WAV duration, simulated/SDK mic sources, and daemon
    `stop_sound`/upload shape (MockTransport).
  - The robot's real `VoiceConversation` against the real hub and core
    in process: two-turn conversation, stop during playback calling
    `stop_audio` within 1 s, a withheld reply not played, recovery after a
    hub STT failure, microphone failure, and robot-side maximum length.
  - Real sockets: uvicorn hub plus the actual `websockets` `RobotWSClient`.
    A dropped hub connection stops capture and does not restart it.
  - Full real speech chain: Silero → faster-whisper → core → espeak (`slow`).
- `services/companion-core/tests/test_app.py::test_spoken_command_text_never_actuates`:
  VOICE-modality `/reachy standby`, `/standby` and `/reachy wake` never change
  real embodiment state. Confirmed failing with the core gate removed.
- `services/reachy-hub/tests/test_tts.py`: espeak output carries a real frame
  count.
- `test_robot_voice.py::test_legacy_voice_turn_requires_the_owner_before_any_transcription`
  (added after review). The legacy `/voice/turn` refuses anonymous callers,
  robot-token callers, a non-owner `user_id`, and cookie calls without CSRF,
  all before STT runs. Confirmed failing when the route is removed from the
  middleware's gated set.
- `clients/operator-ui/tests/voice.test.cjs`: `/hub/` proxied mount, start,
  renew and stop with CSRF, literal rendering of spoken/withheld turns (HTML
  injection inert), disabled start for a non-capable robot, and polling that
  ends on stop and logout.

## Real-process Compose run

Disposable project `reachy24c-verify`: images built from this tree, real
Postgres with migrations, Caddy on `127.0.0.1:18080`, hub, core, and a
**simulated** embodiment. The embodiment had `VOICE_CONVERSATION_ENABLED=true`
and `SIM_MIC_WAVS` set to three espeak utterances. It registered over WSS
**through Caddy** at `http://caddy:8080/hub`. The LLM was the host's OVMS
`OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov`, set through `PUT /hub/settings/llm`
with `local_only` routing. The owner was driven with the `REMOTE_UI_TOKEN`
bearer.

**First attempt failed live.** The first turn triggered the hub's first-use
Whisper download. `get_stt()` was evaluated on the event loop, which blocked
it for ~40 s. The robot's WebSocket keepalive ping timed out, and the hub
ended the session as "Robot disconnected". The pre-existing `/voice/turn` and
`/robots/{id}/speak` had the same pattern. The fix builds providers inside the
worker thread, under a lock. It has a regression test, and the rebuilt image
was rerun.

The run also found that `espeak-ng --stdout` writes a placeholder length
header (≈48,700 s). The robot would have waited that long after every reply
before listening again. Two fixes: `EspeakTTS` rewrites the header, and the
robot measures the PCM itself.

Rerun (after the hub restart, the robot reconnected on its own):

| Turn | Heard (real faster-whisper) | Outcome | Reply (real LLM) |
|---|---|---|---|
| 1 | "My favorite color is green. Please remember that." | spoken | acknowledged green |
| 2 | "What is my favorite color?" | spoken | "Your favorite color is green." |
| 3 | "What is on my calendar today?" | withheld: routing → web | shown to owner only, never synthesized |

After the spoken turns, typed web chat in the same session answered "Earlier,
you mentioned your favorite color was green". Stop returned in 3 ms and
nothing restarted.

Hub state timeline, sampled at 0.5 s:

| Time (s) | State |
|---|---|
| 0.5 | listening |
| 4.5 | thinking |
| 51.4 | speaking |
| 56.4 | listening |
| 59.0 | thinking |
| 60.0 | speaking |
| 62.5 | listening |
| 65.1 | thinking |
| 66.1 | listening |

Turn 1's ~47 s was the model download. Turn 2's upload-to-reply time was about
1 s, at sampling resolution. These are fixture timings on the homelab CPU, not
24d latency evidence.

Logs of all four services contained no transcript text and no robot-token
material. The hub's per-turn INFO line is not emitted at the images' default
log level.

A later stop-during-speaking run confirmed that the owner stop reached the
simulated robot and ended the session. The simulated backend has no audio
device, so the daemon `stop_sound` call is verified only by the unit test.

The stack was removed with `down -v --rmi local` for that project only. The
running `reachy-homelab` stack and OVMS were not touched, and the temporary
env and key files were deleted.

After the Compose run, review moved robot-side microphone construction
(`open_microphone`, which connects the SDK media client on the Nano) off the
embodiment event loop, for the same reason as the hub fix. The simulated
microphone does no I/O at that point, so the Compose results are unaffected.
The suites above were rerun after this change.

## Observations

- **Sticky conversation privacy (pre-existing core rule).** With an LLM
  configured, once a conversation has produced a work-private reply, core
  labels every later generated reply in that in-memory conversation
  work-private. A second Compose run started after the calendar turn withheld
  even "What is my favorite color?". This is correct under ADR 0006, since
  generated text may repeat earlier private content. For 24d it means the
  robot stays silent for the rest of that conversation until core restarts.
  Run the privacy rows last, or expect this.
- A WSS-only simulated robot shows `embodiment_state=disconnected`: its
  presence watchdog still expects the legacy HTTP heartbeat. The Nano
  deployment also registers `ROBOT_HTTP_BASE_URL`, so this does not apply
  there. It is a pre-existing ADR 0019 gap.
- The hub downloads the Whisper model into the container on first use and
  loses it when the container is recreated. Warm STT before timed 24d turns.

## Not verified

- Anything on the Nano: capture via the SDK LOCAL backend and container
  `dsnoop`/`--ipc host`/UID sharing, ReSpeaker channel layout, daemon
  playback, `stop_sound` and its audible tail, and acoustic echo during
  half-duplex use.
- `start-reachy.sh` changes: `bash -n` only. Target-platform verification is
  the first 24d step.
- A live Telegram delivery of a withheld reply. That path is covered in
  process only, and without a bound chat it reports "Telegram is not
  available".
- Real browser microphone permission is irrelevant: the UI never captures
  browser audio.
