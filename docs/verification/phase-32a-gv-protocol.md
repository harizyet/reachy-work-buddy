# Phase 32A.V: GV enrolment and evaluation workflow (Android app)

Gate GV needs real recordings of the owner and, with consent, one or two other people, on the owner's own phone, measured by `tools/voice_identity_benchmark.py`. This is the practical procedure. **It selects and activates nothing**: the tool reports threshold *candidates* with observed error rates; the owner decides whether any becomes `VOICE_IDENTITY_ACCEPT_THRESHOLD` / `VOICE_IDENTITY_UNCERTAIN_THRESHOLD`. Status: written and rehearsed only on public clips ([verification record](phase-32a-android-2026-10-15.md)); **no owner data has been collected**.

## Before you start (owner, with the hub off production traffic if possible)

1. A hub with the `speaker` Compose profile running, `VOICE_IDENTITY_ENABLED=true`, the 038 migration applied, and `OWNER_RECOGNITION_CAPTURE_DIR` set on a persistent volume (otherwise clips live in memory and vanish on a hub restart). This is a deployment step and needs its own approval; use a separate Compose project or the disposable stack ([deployment](../deployment.md#shared-voice-identity-phase-32av-not-deployed)).
2. The debug APK installed on the phone (owner's decision).
3. Leave the thresholds unset. With them unset the app shows every result as unverified or inconclusive, which is correct for this stage.
4. A second device that can play audio (a laptop or another phone), and one or two people who agree to be recorded for this test.

## What the app records (Menu → Voice identity → Open voice evaluation)

The screen first asks for your password and switches on **evaluation recording** (the hub's existing benchmark mode, [Phase 26d](../phase-26.md)): raw clips are then kept encrypted on the hub until you delete them. Each clip is uploaded with a label `role=…;speaker=…;condition=…`; the phone shows no score.

| Block | Who / how | Target | Why |
|---|---|---|---|
| Enrolment clips | Owner, one phrase per clip, quiet room, normal hold | 8 | Builds the template exactly as the hub does (the tool uses the first usable ones, at least 5) |
| Owner, quiet | Owner, free speech 4 to 8 s | 10 | Genuine acceptance in good conditions |
| Owner, noisy | Owner, TV, tap or street noise | 10 | Genuine acceptance with background noise |
| Owner, another day | Owner, **at least one day after enrolment**, different time of day and distance | 10 | Held-out genuine trials: the honest estimate, since same-session clips flatter the result |
| Someone else | A consenting person, alias only (`person1`), their normal voice; tick the consent box in the app | 10 per person | False accepts for a non-owner. Use a second person if available (`person2`) |
| Replay probe | Play a recording of the owner (from the quiet block, or a different recording) on a second device near the phone; say nothing | 6 | Replay attack: counted as an attack whoever the label names |
| Synthetic probe | Play text-to-speech (any TTS) or voice-converted speech near the phone | 6 | Synthetic attack. A converted/cloned *owner-like* voice is the meaningful case; a plain TTS voice is only the easy one. Say which you used in your notes |

Protocol notes: do not coach the second person to imitate the owner unless that is the probe you are naming; keep the same phone and app version for the whole session; write down the room, the playback device, the date and the app/commit versions beside the report (the acceptance matrix needs them). Each block's target is a floor, not a statistical guarantee.

## Running the evaluation (on your computer)

```bash
# start (or point at) a speaker service: docker compose ... --profile speaker up speaker   (or run deploy/homelab/speaker/app/server.py locally)
REACHY_PASSWORD='…' python tools/voice_identity_benchmark.py \
    --fetch http://<hub>:8080/hub --username owner --url http://<speaker>:8012 > gv-report.json
# or, from an export you downloaded yourself (owner-recognition → export):
python tools/voice_identity_benchmark.py --export voice-benchmark-dataset.zip --url http://<speaker>:8012 > gv-report.json
```

The password comes from the environment, never the command line. Unlabelled clips are ignored. The report contains:

- trial counts per kind (genuine, impostor, attack) and per condition;
- `threshold_candidates`: *no observed false accept* (just above the highest impostor or attack score), *at most one observed false accept*, and the *equal-error point*, each with FAR, attack-acceptance and FRR as counts, rates and Wilson 95% intervals;
- a 49-point threshold sweep;
- latency of the embedding call and the HTTP round trip;
- with `--accept A --uncertain U` also the verified / inconclusive / not-verified matrix per condition at those two numbers. Use this to preview a pair you are considering; supplying numbers is not selecting them.

## How to read it

- Candidates are measured on the same clips used to pick them, so they are optimistic. Prefer the held-out block when comparing.
- A handful of impostor clips gives wide intervals (zero observed false accepts in 10 trials is still consistent with a true rate near 25%). Say so in any decision record.
- Replay and synthetic rows measure only the attacks you tried. They support "this attack was or was not accepted", never "spoof-resistant".
- The two thresholds mean different things: accept (shown as verified) and uncertain (below it, shown as inconclusive; below that, not verified). A wide band between them is a safe default.
- The result is identity evidence for display. Whatever numbers are chosen, nothing in Reachy uses the match to allow or deny an action.

## After the session

Delete everything from the same screen (it asks for your password and switches recording off), then confirm with `GET /owner-recognition/status` that no voice samples remain. Store the report where you keep other evidence, without the clips. If a decision to activate is made, it is a separate approval: set the two thresholds and `VOICE_IDENTITY_CALIBRATION_VERSION` in the hub environment, recreate the hub, repeat a short live check, and record it.
