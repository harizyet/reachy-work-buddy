# Phase 24e — Conversation hardening and deferred acceptance

Status: **in progress** (2026-09-25). This page states what 24e must deliver,
not what already works. Item 1 (adaptive end of turn) is implemented per the
[ADR 0023 amendment](adr/0023-robot-voice-conversation.md#addendum-adaptive-end-of-turn-2026-09-25-phase-24e),
with in-process and simulated-audio tests only; it is not deployed or
physically accepted. Item 2's search-rule fixes and STT vocabulary bias are
implemented and tested in process (see the
[note below](#implementation-notes-item-2)); the correctness set is not
started. It follows [Phase 24d](phase-24cd.md#phase-24d--physical-end-to-end-acceptance),
which the owner closed on the conversation workflow on 2026-09-25, and it
addresses what 24d found or deferred. Evidence for each issue is in the
[24d record](verification/phase-24d-conversation-2026-09-24.md). Scope was
agreed with the owner on 2026-09-25.

## Prerequisites for Phase 25

Phase 24d's re-scoped closure alone does not unlock Phase 25. Before
owner-recognition implementation starts, these 24e gates must **PASS on the
real robot**, with evidence in the dated 24e verification record:

- Adaptive end of turn, including long utterances with natural pauses and
  cancellation of a held turn.
- Deferred Turn handling, Privacy, Consent and auth, Stop and expiry,
  Recovery (including no stale replay or automatic capture reactivation),
  and Coexistence and sustained use rows from scope item 3.
- Normal conversation and Timing repeated after the turn-path changes,
  within the existing budgets, with renewed owner acceptance of usability.

BLOCKED, deferred or untested prerequisite rows do not unlock Phase 25.
The answer-quality benchmark, search heuristics, STT vocabulary tuning,
and Nano diagnostics may proceed independently and are not prerequisites.
Session continuity remains required 24e work but is not a Phase 25 start
gate. These exclusions do not remove work from 24e's full exit criteria.
If subsequent independent work changes the accepted turn path, rerun the
affected prerequisite rows before building on that changed path.

## Motivation

24d showed that the robot conversation works end to end within budget. It
also found:

- **Turn splitting.** Robot turns end after 700 ms of silence, so a long
  utterance with natural pauses became four separate turns, each answered
  on its own.
- **Answer correctness.** The owner deferred this out of 24d:
  - Off-topic replies from the local model: a statement ("My code word is
    pineapple") answered with code, and a blocks tangent.
  - Search results misused ("an issue with the system").
  - Deterministic search rules that fired on the wrong turns:
    - "Goodbye for now." searched, because "now" is a freshness word;
    - "Who are you?" merged the previous weather question as a short
      follow-up;
    - long-utterance fragments searched on "today" and "she".
  - One search turn spent 17 s in the LLM on the merged query and its
    results, close to the 20 s budget.
  - STT regularly heard "Reachy" as "Ricci" or "Richi".
- **Deferred acceptance.** Seven matrix rows were not passed.
- **Undiagnosable robot events.** An unplanned power loss could not be
  explained: the journal is volatile, and pre-NTP timestamps are wrong
  because the Nano's RTC does not keep time.

## Scope

### 1. Adaptive end of turn

End a turn quickly when the speaker has finished a thought, and wait longer
when they have trailed off mid-sentence.

- The robot keeps cutting segments at the short silence (700 ms). The hub
  transcribes each segment (STT takes about 0.4 s) and decides
  deterministically whether it looks complete. Fixed, tested rules:
  terminal punctuation, a trailing ellipsis, and a final word that is a
  function word or conjunction ("the", "about", "and", "with", "to",
  "because", …). No LLM decides. These are heuristics, not semantic
  certainty: terminal punctuation must not override a trailing incomplete
  construction. Test missing and spurious STT punctuation, including
  "I was wondering if you could tell me" both without punctuation and with
  an inserted final period, as well as complete thoughts without punctuation.
- An incomplete segment is held. The hub answers with a new `continue`
  outcome instead of a reply. The robot resumes listening at once, with no
  playback and no tail guard, and the next segment is appended to the held
  transcript.
- If nothing is heard within a continuation window (default about 1.5 s,
  hub-set in `VoiceLimits`), the robot sends a finalize request for the held
  turn and gets the reply as usual. A total utterance cap still applies:
  raise `max_utterance_seconds` for the merged turn, not per segment.
- Complete-looking turns keep today's latency. Only trailing-off turns pay
  the window.
- This changes the ADR 0023 protocol (a new outcome, a finalize upload,
  and turn numbering for a held turn). Record it as an
  [ADR 0023](adr/0023-robot-voice-conversation.md) amendment before
  implementing. Fencing, half-duplex and the one-in-flight-turn rule are
  unchanged.

### 2. Correctness: search logic, then measurement

Fix the deterministic causes first, then measure what is left against a
fixed set. Change model only if the measurement says so.

- **Search trigger rules** (`companion_core/websearch/policy.py`):
  - Closings, greetings and thanks never search. This covers "goodbye",
    "bye for now", "thanks", "hello" and similar, even when they contain a
    freshness word.
  - "now" alone is not a freshness cue. It still counts inside a
    freshness phrase ("right now in", "open now").
  - Self-identity questions ("who are you", "what can you do") are neither
    follow-ups nor searches.
  - A follow-up merges the previous query only when it refers back to that
    search's subject, not merely because a search came before. Adaptive end
    of turn removes the fragment case.
- **Statement handling.** A declarative statement with no question gets a
  short acknowledgement. Measure it in the set below before adding any
  prompt change.
- **STT vocabulary.** Bias faster-whisper toward "Reachy" and the owner's
  configured name, using an initial prompt or hotwords.
- **Correctness set.** A fixed, versioned set of voice-style turns:
  - deterministic context checks;
  - statements that should only be acknowledged;
  - closings;
  - self-identity questions;
  - search-grounded questions answered from **fixture** results, so the
    correct answer is known.

  Scoring rules are written down before the first measurement. The owner
  agrees the pass threshold **before** any result is seen, as 24d did for
  latency. Run it against the local model through core. If the local model
  fails the threshold, run the same set on the cloud model (GLM-5.3) and
  re-check the voice latency budget before switching voice turns to it.
  Switching is an owner decision.

### 3. Deferred 24d acceptance rows

Run on the real robot. The row definitions and evidence rules are the
[24d matrix](phase-24cd.md#phase-24d--physical-end-to-end-acceptance);
24e does not redefine them.

- **Turn handling:** silence, background noise, echo and self-hearing,
  plus long utterances after scope item 1.
- **Session continuity:** robot → web chat → bound Telegram → robot, with
  the same context. If Telegram is unavailable, the row is BLOCKED.
- **Privacy:** Desk, Office and Silent modes, DND, private call, and no
  fallback to room speech.
- **Consent and auth:** voice cannot confirm, 24b negatives do not
  actuate, and unauthenticated or mismatched capture controls fail. No
  live destructive writes.
- **Stop and expiry:** cancel during capture, inference and playback; the
  audible tail is within 1 s; logout and session expiry stop capture.
- **Recovery:** microphone or speaker failure, a network or hub
  interruption, and process restarts, with no stale replay or automatic
  capture reactivation. The cold-reboot part already passed in 24d.
- **Coexistence and sustained use:** a 30-minute supervised session. It
  needs `max_session_seconds` of at least 1800 (the model allows up to
  3600). Set it for the run and record the value; don't chain 10-minute
  sessions.

Repeat the Normal conversation and Timing rows after items 1 and 2 change
the turn path, with the same budgets (non-search p50 ≤ 4 s, p95 ≤ 8 s;
search ≤ 20 s each).

### 4. Nano diagnostics

Make the next unexplained robot event diagnosable. The robot host is the
designated production Nano, so changes follow the
[deployment rules](deployment.md#robot-host-and-jetson-nano) and need
target-platform verification.

- **Persistent journal:** `Storage=persistent` with a size cap, so a crash
  or power loss leaves the previous boot's log (`journalctl -b -1`).
- **Time before NTP:** find why the clock reset to "Jan 1". Check whether
  the RTC has a battery, and whether timesyncd's saved clock is used at
  boot. Fix it so pre-sync timestamps are at least monotonic with the last
  boot. Record which fix applies; a missing RTC battery is a hardware
  item for the owner.
- **Power evidence:** record the Nano's power supply arrangement, and log
  its power-monitor rails and throttling, so a future `POWER_ON_RESET` can
  be matched against supply readings. This is a small, bounded logger or
  journal entries, not a monitoring stack.
- Document the diagnosis procedure (what to collect after an unexpected
  reboot) in the deployment guide.

### Implementation notes (item 2)

- A turn is social only if nothing but closing/greeting/thanks phrases and
  filler remains, so "Thanks, what's the weather tomorrow?" still searches.
  Always still searches every turn.
- A follow-up needs a reference phrase ("what about", "tell me more"), a
  question that opens with "and" or uses a pronoun, or a short question
  with no freshness subject of its own. A bare "Any news?" therefore starts
  a new topic rather than continuing the previous one.
- STT uses a Whisper `initial_prompt` ("Hello Reachy." plus the persona
  name, read from core each turn), not `hotwords`: on espeak clips with
  `base.en`, hotwords dropped final punctuation on 2 of 5 clips, while the
  prompt kept it and recognised "Reachy" about as often. This is a synthetic
  comparison, not evidence on real speech; the physical run checks it.

## Non-goals

- **Robot health alerts** (motor hardware errors, a daemon stuck in error,
  or the recovery unit's crit alert reaching the owner by Telegram or the
  UI), and treating a daemon in `state: error` as unavailable. The owner
  kept these out of 24e.
- **`stewart_5` inspection and repair.** The owner checks the motors by
  hand, outside this phase. 24e must not send behaviours or raw moves to
  investigate them.
- A general model upgrade, streaming TTS, full-duplex barge-in, and owner
  recognition (Phase 25).
- Upgrading reachy_mini. The boot wake-up race is also present in the 1.11
  source; the once-per-boot restart stays the mitigation.

## Implementation sequence

This is a working order, not a dependency on completing every item before
physical acceptance. The [Phase 25 prerequisites](#prerequisites-for-phase-25)
can be implemented and accepted while independent work remains open.

1. ADR 0023 amendment for adaptive end of turn, then its implementation,
   with controlled-time tests for the continuation window, fencing and
   cancellation of a held turn.
2. Search-rule fixes with parametrized tests from the 24d transcripts'
   shapes (no personal content), and the STT vocabulary bias.
3. The correctness set and scoring rules. The owner agrees the threshold,
   then it is measured on the local model and, only if needed, on the cloud
   model.
4. Nano diagnostics, verified on the Nano with the owner's approval for
   any system change.
5. Physical run: repeat the Normal conversation and Timing rows, then the
   deferred rows, and the 30-minute session last.

## Exit criteria

- A long utterance with natural mid-sentence pauses is one turn on the real
  robot. Complete-sounding short turns still meet the non-search budget.
- None of the 24d misfires searches: closings, greetings, self-identity,
  and mid-utterance fragments. Genuine freshness and follow-up questions
  still search.
- The correctness set meets the threshold the owner agreed in advance, on
  the voice route that is deployed.
- Every deferred 24d row is PASS or BLOCKED with a stated reason, recorded
  in a dated `docs/verification/phase-24e-<date>.md`.
- The Normal conversation and Timing rows pass again after the turn-path
  changes.
- On the Nano, a reboot leaves the previous boot's journal readable,
  pre-NTP timestamps are sane or the hardware cause is documented, and
  power readings are captured.
- The owner accepts usability again after the changes.
