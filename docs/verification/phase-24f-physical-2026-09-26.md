# Phase 24f physical run (2026-09-26)

**Scope:** the [item 4 acceptance rows](../phase-24f.md#4-verification-and-acceptance)
on nano-1, with the owner present and speaking. It follows the accepted
24e baseline ([24e physical record](phase-24e-physical-2026-09-25.md)).
Motion is switched per feature from the portal (Settings · Accounts →
Conversational animations, `5c9679d`). Recorded gestures are full
animations, so every motion step here had the owner present, per
AGENTS.md. Timing comes from
[`deploy/reachy/voice-timing.py`](../../deploy/reachy/voice-timing.py).
The robot-side overhead is "voice playback started" minus "hub replied",
the only part that motion can affect.

## Versions

| Component | Version |
|---|---|
| Hub and core | `c383370` (STT/TTS warm-up, 3.0 s continuation window, palm stop on) |
| Nano embodiment | Image `eb1e92e9`, built at `67bfc5f` (10:33Z), with runtime motion settings |
| Daemon | `reachy-mini` 1.8.4, PID unchanged through the run |

## Step B: motion-off baseline (10:36–10:42Z)

This is the 24e warm timing re-run; see the
[24e record](phase-24e-physical-2026-09-25.md#timing-again-warm-24f-step-b-1036-1042z).
The run was 22 fixed short questions, all spoken. Non-search p50 3.63 s,
p95 5.22 s. Robot-side overhead per turn: median 98 ms, max 454 ms
(turn 1, the first `play_sound` of the session).

## Step C: listening and thinking gestures on, wobble off (10:44–10:52Z)

Gestures were switched on in the **portal**. The embodiment logged
`GET` then `PUT /settings/motion` 200 from the hub, which confirms the
portal → hub → robot path. The same 22 questions were used.

| Measure | Result |
|---|---|
| Utterance end → first audio | p50 4.29 s, p95 6.56 s (+660 ms p50 against step B). **Confounded:** replies were much longer this time (turn 18: 32.9 s of audio against 1.95 s in step B), so hub LLM/TTS time grew. This is not a motion effect |
| Robot-side overhead | Median 117.5 ms (+19.5 ms against step B), mean 161 ms. Outliers of 611 ms (turn 2) and 512 ms (turn 11) came during failing daemon calls |
| Gesture delivery | **FAIL.** 31 `play_behaviour` and 3 `goto_home` calls failed: 27 `Connection reset by peer`, 7 `Server disconnected without sending a response`, 1 timeout. The daemon logged 44 `POST /api/move/stop` 500s (`KeyError: Running move with UUID … not found`) |
| Safety | No IK or overheat lines. The head ended at home, and nothing was left running |

Not run: stop during a thinking gesture, and the explicit-behaviour 409
check. The owner switched gestures off again in the portal after the run.

**Cause, reproduced against a 1.8.4 mockup daemon:** stopping a move that
has already finished raises an unhandled `KeyError` in the daemon (500),
and uvicorn drops that connection. The embodiment's pooled HTTP client
then reused the dropped connection for the next gesture or home move,
which failed with "Connection reset by peer". Short gestures usually end
before the next conversation state, so almost every transition hit it.
The Nano session had suggested an idle keep-alive expiry; the mockup
ruled that out (idle gaps of 1–8 s were all fine) and showed that the 500
triggers it.

**Fix (`b36736d`):** the backend stops a move only if `/move/running`
still lists it, and sends the stop with `Connection: close` in case it
finishes in between. Against the mockup: 16 finished and preempted
gesture/home moves with 0 request failures and 0 daemon `KeyError`s.
Embodiment 130 passed. Step C is to be rerun with the rebuilt image.
