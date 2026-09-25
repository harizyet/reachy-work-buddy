# Phases 24c–24d — complete and prove Reachy conversation

Status: **24c implemented 2026-09-24** (automated, browser and real-process
checks with a simulated robot microphone; see the
[audit result](#phase-24c-audit-result-2026-09-24) and
[verification record](verification/phase-24c-conversation-2026-09-24.md)).
**24d physical acceptance in progress since 2026-09-24**: real microphone →
STT → LLM → TTS → speaker conversation has been demonstrated on the robot;
the formal acceptance matrix remains open (see the
[24d record](verification/phase-24d-conversation-2026-09-24.md)). These
phases follow Phase 24b and gate Phase 25.

24d proves the physical conversation workflow: capture, turn handling,
context, intelligible replies, handoff, privacy, cancellation, recovery and
latency. It does not accept the factual quality of the model's answers.
Search retrieval and small-model answer quality are
[Phase 24a](phase-24a.md) follow-up work, so a wrong current-affairs answer
from the local model does not fail a 24d row.

## Required workflow

The owner explicitly starts a bounded conversation from an authenticated
control, speaks into **Reachy's microphone**, hears the permitted response
from **Reachy's speaker**, and continues with follow-up turns that retain
context. The owner can stop capture/playback and continue the same conversation
in web chat or bound Telegram. No shell command or manual WAV upload is needed
for each turn. A browser microphone, uploaded recording, echo reply or remote
text-to-speech command alone does not satisfy this workflow.

Before Phase 25, this is an explicitly activated, supervised interaction in a
private test setting, disabled by default and visibly identified as lacking
owner recognition. It does not enable unattended ambient listening or claim
that push-to-talk authenticates the physical speaker. Phase 25 adds the
recognition and attribution gates before ambient use; its in-view requirement
is not waived for the eventual recognized room-voice mode.

## Current evidence and gaps

Pre-implementation baseline, inspected 2026-09-24. The
[audit result](#phase-24c-audit-result-2026-09-24) below supersedes it. Classify each
link as implemented and verified, implemented but unverified, or missing, with
code/test/evidence references. Reuse working components and fix demonstrated
gaps rather than replacing the speech stack wholesale.

| Link | Current evidence | Work required |
|---|---|---|
| Physical capture and turn boundaries | Physical mic/ALSA recording was heard; [Silero VAD](../services/reachy-embodiment/src/reachy_embodiment/audio/vad.py) explicitly is not connected to a live stream | Wire actual Reachy capture, bounded utterance framing and activation/stop lifecycle |
| Voice ingestion and reasoning | Hub [`/voice/turn`](../services/reachy-hub/src/reachy_hub/app.py) transcribes a submitted WAV, calls the shared conversation path as `VOICE`, and returns synthesized WAV | Connect robot audio to this pipeline through an authenticated network path; verify real STT, configured LLM and multi-turn context |
| Robot response delivery | [`play_audio`](../services/reachy-embodiment/src/reachy_embodiment/robot.py) uploads audio then asks the daemon to play it; its upload response shape is explicitly unverified | Verify actual daemon contract and audible completion; connect conversation output to playback |
| Privacy enforcement | `/voice/turn` currently synthesizes the reply after routing; returning WAV alone does not enforce the physical speaker destination | Enforce mode/privacy and private-channel delivery before robot playback; never blindly play every returned WAV |
| Conversation control | Text sessions, WebRTC calls and semantic presence components exist | Prove robot turn lifecycle, cancellation, echo avoidance, follow-up context and channel handoff together |

Physical audio evidence is in [Phase 22b first motion](verification/phase-22b-first-motion-2026-09-23.md)
and the [current handover](../HANDOVER.md). These are component findings,
not physical conversation acceptance. Phase 8's roadmap exit criterion remains
an intended outcome, not evidence that the complete robot path was exercised.

## Phase 24c — audit and implement the missing workflow

1. Trace capture → transport → STT → hub session → core conversation/LLM →
   routing → TTS → transport → physical playback. Inventory actual deployment
   devices, formats, dependencies, auth, timeouts and existing tests. Publish
   the gap checklist and resolve every required missing or broken link.
2. Add owner-authenticated start/stop or push-to-talk controls to the existing
   operator UI, usable at direct and proxied mounts. Bind the selected robot
   and owner session server-side. Capture only within a bounded, explicit
   interaction; stop on logout, expiry, disconnect or user cancellation.
   Define and document maximum capture duration, silence timeout, upload size
   and queue limits. VAD can delimit turns within that interaction but cannot
   grant permission to capture.
3. Wire robot-side media capture and local turn detection to hub-owned STT/TTS
   and sessions, with core retaining reasoning and consent. Use defined
   network protocols and shared contracts, preserving ADRs
   [0001](adr/0001-service-boundaries.md) and
   [0019](adr/0019-robot-initiated-hub-connectivity.md); do not assume WSS
   registration already carries microphone audio. Record any necessary
   transport/auth decision before structural changes. Verify media access
   coexists with the daemon and camera without device contention or teardown.
4. Deliver only permitted replies to the robot, enforcing
   [ADR 0006](adr/0006-response-routing.md). Private/Office/Silent/private-call
   output must use the permitted private destination or remain withheld with
   a visible reason if none is available. Preserve `InputModality.VOICE`,
   [ADR 0011](adr/0011-destructive-action-consent.md), Phase 24b's explicit
   command authorization and [ADR 0018](adr/0018-hybrid-llm-routing.md).
   Neither a transcript nor an LLM may invent authorization or promote voice
   to authenticated text.
5. Implement clear listening/thinking/speaking/idle/error states and bounded
   single-turn ordering. A half-duplex baseline is acceptable: suspend input
   during playback and visibly indicate when the next turn can begin. Prevent
   self-transcription and duplicate/late reply playback. Provide explicit
   cancellation that stops actual queued/device audio, not only HTTP work;
   barge-in and wake-word activation are not required for this baseline.
6. Retain conversation context through follow-ups and a web/Telegram handoff.
   Handle empty/noisy capture, STT/LLM/TTS failure, robot/hub disconnect and
   restart without stuck capture, duplicate actions or stale audio on recovery.
   Keep raw audio transient by default; document cleanup and show useful
   failure states without logging credentials or personal transcripts.
7. Add actual ASGI integration chains, controlled-time lifecycle tests and
   real speech-provider checks under the [development conventions](development.md#testing-conventions).
   Verify built processes/images, isolated service dependencies and browser
   controls; run Ruff for code changes. Update deployment/operator/service
   documentation to describe the actual supported workflow and limitations.

**24c exit:** every required link is implemented with automated coverage and
real-process speech verification; a repeatable hardware acceptance procedure
is ready. Fixtures and simulator checks are labelled. This does not close 24d.

### Phase 24c audit result (2026-09-24)

Transport and auth decision: [ADR 0023](adr/0023-robot-voice-conversation.md).
Evidence: [verification record](verification/phase-24c-conversation-2026-09-24.md).
Status meanings: **verified** means automated/real-process checks passed off
the robot; **unverified on robot** means the code exists but the Nano path has
not run.

| Link | Before 24c | Now | Status |
|---|---|---|---|
| Owner start/stop control | Missing | Operator UI Chat → Robot microphone; `/robot-voice/start`, `/renew`, `/stop`; owner cookie+CSRF or bearer; lease, logout, idle, max length | Verified (hub tests, Chromium) |
| Hub → robot capture control | Missing (WSS carried only heartbeats) | `voice_start`/`voice_stop` over the ADR 0019 socket, gated by the robot's `voice_conversation` capability; stopped on disconnect | Verified (in-process and real-socket tests) |
| Physical capture | Missing; VAD not wired | `ReachyMiniMicSource` via the SDK LOCAL backend (`dsnoop`); container options in `start-reachy.sh` | **Unverified on robot** |
| Turn boundaries | Silero VAD unwired | `UtteranceSegmenter`: VAD end-of-speech, pre-roll, minimum and maximum length | Verified (fixture VAD plus real Silero on synthesized speech) |
| Robot → hub transport | Missing | `POST /robot-media/voice-turn` with robot bearer, generation, session and turn; 1 MiB and WAV-format bounds | Verified |
| STT | `/voice/turn` only | Same lazy faster-whisper provider | Verified (real `tiny.en`) |
| Session/core/LLM | Shared path existed | `handle_inbound_message(channel=reachy, VOICE)`, shared with web/Telegram | Verified (real core; real local LLM in Compose run) |
| Routing and privacy before speech | Not enforced (WAV always returned) | ADR 0006 routing plus DND/meeting veto before synthesis; withheld text to the owner panel and Telegram | Verified |
| Voice consent and commands | ADR 0011 enforced; `/reachy` commands parsed from any modality | Commands parsed only from typed text | Verified (fixed in core) |
| TTS | espeak WAV had a placeholder length header | Header rewritten with the real frame count; robot measures PCM length | Verified (this bug would have stalled the robot ~13 h per reply) |
| Robot playback | Upload shape "unverified" | Upload response `path` confirmed from the pinned daemon 1.8.4 source; `stop_sound` for cancellation | **Unverified on robot** |
| Turn lifecycle / echo | Missing | Half-duplex: mic closed while thinking/speaking plus 400 ms guard; one turn in flight; late replies discarded | Verified off robot; acoustic echo **unverified** |
| Failure and recovery | Missing | STT/core/TTS failure → visible error and listening resumes; hub restart/robot disconnect → stop, no auto-restart | Verified |
| States shown | Missing | Starting/listening/thinking/speaking/off in UI; embodiment state set to match | Verified |

Deliberately not included: barge-in, wake word, continuous ambient listening,
speaker recognition (Phase 25), and gesture cues during turns. Recorded
emotion moves play sound effects the microphone would pick up.

### Phase 24d hardware procedure

Run with the owner present. Starting or recreating the embodiment container
doesn't start the daemon, but the procedure assumes the daemon is already
running normally. Don't restart it for this test.

1. **Preflight (read-only).** `scripts/start-reachy.sh --check`; confirm the
   daemon is active and not simulated. Record `git rev-parse HEAD`, the image
   ID, the daemon version, the hub STT model, the TTS engine and the LLM
   settings/model.
2. **Enable.** Set `VOICE_CONVERSATION_ENABLED=true`, run
   `docker rm -f reachy-embodiment`, then `scripts/start-reachy.sh --build`.
   Check the launcher logged "voice conversation enabled" and that the
   operator UI lists the robot without "voice not enabled".
3. **Device coexistence.** While the daemon plays a named behaviour sound and
   `GET /camera/frame` works, start listening. If the status reports
   "Microphone unavailable", check `docker logs reachy-embodiment` for ALSA
   or shm errors. That is a 24c defect: fix it and rerun.
4. **Agree the latency budgets** with the owner before any timed turn, and
   record them (the matrix requires this): one for non-search turns and a
   separate one for search-assisted turns, since a search adds a provider
   round trip and a longer prompt.
5. Run the matrix rows above in order. For timing, use hub logs (turn
   outcome timestamps) and a phone recording of the room for utterance end
   and first audible reply. Measure the stop tail from the Stop click to
   silence on that recording.
6. Clean up: stop listening, set `VOICE_CONVERSATION_ENABLED=false` again
   unless the owner keeps it, recreate the container, and delete no volumes.
   Record everything in `docs/verification/phase-24d-conversation-<date>.md`
   without raw audio or personal transcripts.

## Phase 24d — physical end-to-end acceptance

Use the deployed Nano/Reachy microphone and speaker, actual hub/core processes,
real STT/TTS and a configured real LLM. Record versions/configuration and the
network topology. No stub model, prerecorded input or browser-mic substitution
counts as the main live conversation run. Apply the existing
[deployment supervision and cleanup rules](deployment.md#upgrades-and-verification-cleanup);
daemon starts/restarts during this work require owner supervision. Do not
restart it just to run a test. Use harmless content and fixture adapters for
consequential-action probes, never real destructive writes.

| Scenario | Required evidence |
|---|---|
| Normal conversation | At least 10 consecutive live spoken turns, including three context-dependent follow-ups, starting/stopping from the UI; intelligible physical replies and no manual per-turn transport steps. Use deterministic context checks whose correct answer is known in advance ("My code word is pineapple." → "What was my code word?"; "I have three red blocks and two blue blocks." → "How many blocks did I mention?"; "My fictional project is called Zephyr." → "What is the project called?"). Run one or two search-assisted turns separately; they must complete the workflow (search, reply, playback), but their factual accuracy is 24a scope |
| Turn handling | Short and long utterances, silence and background noise; bounded capture, no duplicated/lost turns in the normal run, no speaker-to-mic self-conversation; visible half-duplex behavior if used |
| Session continuity | Speak a harmless fact, refer to it in a later spoken turn, continue in authenticated web chat and bound Telegram, then return to Reachy with the same owner/conversation context; unavailable Telegram is BLOCKED, not fixture-accepted |
| Privacy | Exercise Desk, Office, Silent, DND and private-call policy as applicable; private replies never leak through the robot; unavailable private destination does not fall back to room speech |
| Consent and auth | Voice confirmation cannot approve consequential actions; Phase 24b negative requests do not actuate; unauthenticated/mismatched-owner capture controls fail; exercise without live destructive writes |
| Stop and expiry | Cancel during capture, inference and physical playback; logout/session expiry stop further capture/delivery; measure actual audible tail and require stop within 1 second of the stop control reaching the robot |
| Recovery | Disconnect microphone/speaker or simulate their failure, interrupt hub/network and restart application processes; show bounded errors and successful new turns after recovery, with no stale replay or automatic capture reactivation. A cold reboot of the Nano must come back with the daemon owning its camera socket, embodiment started after it, and camera and voice usable, with no manual or sudo step |
| Coexistence and sustained use | A 30-minute supervised mixed conversation/idle session with camera access and normal presence activity; no audio device loss, feedback loop, stuck state or unbounded buffers |
| Timing and quality | Record utterance-end → transcript, LLM completion, first audible response and playback completion; report p50/p95 separately for non-search and search-assisted turns, failure counts and owner assessment of intelligibility/usability; agree both numerical response-latency budgets before the run and pass them, rather than choosing them after seeing results |

Record PASS/FAIL/BLOCKED per row, commands/procedure, measured results,
redacted correlation IDs and owner-observed outcomes in a dated
`docs/verification/phase-24d-conversation-<date>.md`. Do not commit raw personal
audio/transcripts. Fix live failures in 24c and rerun affected scenarios;
automated tests cannot override a failed physical run.

**24d exit:** all required scenarios pass on the real workflow and the owner
accepts conversation usability. Missing hardware/provider/channel access leaves
this phase open. Phase 25 starts only after 24c and 24d pass. Their evidence
may satisfy corresponding Phase 22b voice/channel rows, but does not close
its separate endurance/restore gates, Phase 22c camera acceptance or Phase
23's real-Google acceptance. Google access is not needed for the baseline
conversation; account-connected follow-ups retain their separate gates.

**24d closed, re-scoped by the owner (2026-09-25).** Passed on the real
robot: Normal conversation, and Timing and quality (both latency budgets),
with owner-accepted usability. The owner explicitly deferred the other
rows: turn handling, session continuity, privacy, consent/auth,
stop/expiry, recovery drills beyond the cold reboot, and the 30-minute
session. They were **not passed**. They remain follow-up acceptance, as
does answer correctness (24a). See the
[results](verification/phase-24d-conversation-2026-09-24.md#results).
