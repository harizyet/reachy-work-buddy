# Phases 24c–24d — complete and prove Reachy conversation

Status: planned, not implemented or accepted. These phases follow Phase 24b
and gate Phase 25. Phase 24c audits and completes the conversation workflow;
Phase 24d separately accepts it on the deployed physical robot. Existing
speech components and isolated tests do not establish that this workflow works.

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

Baseline inspected 2026-09-24; re-audit before implementation. Classify each
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
| Normal conversation | At least 10 consecutive live spoken turns, including three context-dependent follow-ups, starting/stopping from the UI; intelligible physical replies and no manual per-turn transport steps |
| Turn handling | Short and long utterances, silence and background noise; bounded capture, no duplicated/lost turns in the normal run, no speaker-to-mic self-conversation; visible half-duplex behavior if used |
| Session continuity | Speak a harmless fact, refer to it in a later spoken turn, continue in authenticated web chat and bound Telegram, then return to Reachy with the same owner/conversation context; unavailable Telegram is BLOCKED, not fixture-accepted |
| Privacy | Exercise Desk, Office, Silent, DND and private-call policy as applicable; private replies never leak through the robot; unavailable private destination does not fall back to room speech |
| Consent and auth | Voice confirmation cannot approve consequential actions; Phase 24b negative requests do not actuate; unauthenticated/mismatched-owner capture controls fail; exercise without live destructive writes |
| Stop and expiry | Cancel during capture, inference and physical playback; logout/session expiry stop further capture/delivery; measure actual audible tail and require stop within 1 second of the stop control reaching the robot |
| Recovery | Disconnect microphone/speaker or simulate their failure, interrupt hub/network and restart application processes; show bounded errors and successful new turns after recovery, with no stale replay or automatic capture reactivation |
| Coexistence and sustained use | A 30-minute supervised mixed conversation/idle session with camera access and normal presence activity; no audio device loss, feedback loop, stuck state or unbounded buffers |
| Timing and quality | Record utterance-end → transcript, LLM completion, first audible response and playback completion; report p50/p95 over the live turns, failure counts and owner assessment of intelligibility/usability; agree a numerical response-latency budget before the run and pass it, rather than choosing it after seeing results |

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
