# Phase 32A.V: interim GV result from the owner's first phone recordings (2026-10-15)

**Interim and incomplete. No threshold is selected or active; nothing was changed on the hub.** Recordings: the owner's own voice on the owner's phone, uploaded by the app's evaluation screen between 15:14 and 15:18 UTC and read afterwards, read-only, by a throwaway container from the hub image (decrypted with the hub's key in memory; the clips stay encrypted on the hub). Each clip was embedded by the deployed speaker service. Scores in `~/reachy-backups/phase32a-deploy/gv-interim-scores.json` (scores only, no audio).

## What was collected against the protocol

| Block | Target | Have |
|---|---|---|
| Enrolment clips | 8 | **9** |
| Owner, quiet room | 10 | **10** |
| Owner, background noise | 10 | **1** |
| Owner, another day (held out) | 10 | 0 |
| Consenting second person | 10 per person | **0** |
| Replay probes | 6 | **0** |
| Synthetic-voice probes | 6 | **0** |

Also on the hub: a real profile (version 1, 5 clips, device: the owner's phone, enrolled 15:12:57 UTC) and 3 test or voice-turn embeddings. The hub and core logs show no errors since the deployment.

## What the clips look like (capture quality)

All 20 clips embedded without error. Length 2.9 to 6.0 s, speech 1.5 to 3.5 s, level about -28 to -33 dBFS (well above the -45 dBFS quiet gate), **no clipping**. The in-app endpointing therefore captured usable utterances in a quiet room on this phone; the 1.5 s clip is the shortest, and the hub accepts verification clips from 0.8 s of speech.

## Scores (cosine similarity to a template built from the 9 enrolment clips)

| Set | n | min | median | max |
|---|---|---|---|---|
| Owner, live trials (10 quiet + 1 noisy) | 11 | 0.754 | 0.790 | 0.862 |
| Owner enrolment clips, leave-one-out | 9 | 0.805 | 0.837 | 0.871 |
| Machine-generated voices (Piper, espeak; **not people**) | 156 | -0.08 | 0.12 | 0.32 |

The single noisy-room clip scored 0.772, within the quiet range. The owner's real-phone scores (median 0.79, floor 0.75) are close to the synthetic Piper-identity genuine scores (median 0.81, but a floor of 0.40 from short clips), i.e. the model recognises a real voice from a real phone about as well as it recognised a clean generated one. The machine voices were all far from the template, but they were never a test of discrimination between people.

## What this does and does not support

- **Supported:** the app's capture, the upload with labels, the hub's benchmark store, decryption and the speaker model all work end to end on the real phone with the real owner; the owner's live scores are tight (0.75 to 0.86) and separated from machine-generated voices by about 0.4.
- **Not supported:** any false-accept or false-reject rate, any threshold. There are **no human non-owner, replay or synthetic-owner clips**, so the impostor side of the distribution is unmeasured; the machine-generated negatives are a floor, not an estimate. One noisy clip and no next-day clips say nothing yet about noise or drift. A threshold below the lowest genuine score seen (0.754) would accept all 11 genuine trials, but where real impostors fall is unknown; real different-person scores are usually higher than the generated voices' and can overlap.
- The leave-one-out and held-out scores are from one sitting; the "another day" block will probably score lower.

## To finish the collection

Complete the noisy block (9 more), record a consenting second person (alias, 10 clips), the replay and synthetic probes (6 each), and the next-day owner clips (10). Then the full report and threshold candidates can be produced with the same tool (`tools/voice_identity_benchmark.py`). When finished, delete the clips from the evaluation screen.

## Update: the team meeting recording as a source of real non-owner voices (scores only)

**Interim, not a calibration. No threshold is selected or active.** With the owner's agreement, one team-meeting recording (made on a different device and in a different room) was scored against the owner's template by `tools/voice_identity_meeting_negatives.sh`, which the owner ran. It kept **scores only** per anonymous diarization label (no audio, embeddings, names or text; nothing written to the hub). The speakers did not individually consent; no per-person result is reported and none should be. Scores: `~/reachy-backups/phase32a-deploy/meeting-scores.json`.

**Owner label.** Of 8 labels, `speaker_4` (22 clean windows, median 0.57) is the owner by score; every other label has median at most 0.11. This is an inference from the score itself (circular); the gap is large, but the owner has not confirmed the label.

| Set | n | min | median | p95 | max |
|---|---|---|---|---|---|
| Owner, live phone clips | 11 | 0.754 | 0.790 | 0.852 | 0.862 |
| Owner inside the meeting (other mic and room) | 22 | 0.446 | 0.565 | 0.678 | 0.729 |
| **Six other people in the meeting** (windows of 2.5 to 6 s, no overlap) | 119 | -0.065 | 0.072 | 0.162 | **0.221** |
| Machine-generated voices | 156 | -0.076 | 0.115 | 0.233 | 0.319 |

(`speaker_7` had no clean window; labels `5` and `6` have 5 and 8; the six people contribute 40, 15, 40, 11, 5 and 8 windows.)

**Candidate accept thresholds with observed counts** (for reading, not choosing):

| Accept threshold | Other people accepted (of 119) | Machine voices accepted (of 156) | Owner phone clips rejected (of 11) | Owner meeting-mic windows rejected (of 22) |
|---|---|---|---|---|
| 0.20 | 3 | 19 | 0 | 0 |
| 0.25 | 0 | 5 | 0 | 0 |
| 0.30 | 0 | 1 | 0 | 0 |
| 0.35 | 0 | 0 | 0 | 0 |
| 0.40 | 0 | 0 | 0 | 0 |
| 0.45 | 0 | 0 | 0 | 1 |
| 0.50 | 0 | 0 | 0 | 6 |
| 0.60 | 0 | 0 | 0 | 15 |
| 0.75 | 0 | 0 | 0 | 22 |

The benchmark tool's candidates over the same data: *no observed false accept* at 0.32 (0 of 275 negatives accepted, Wilson 95% upper bound 1.4%; 0 of 33 owner trials rejected, upper bound 10%); *at most one* at 0.26.

**What it shows.** On this data the owner and the six other people do not overlap: the highest other-person window scores 0.22, the lowest owner window 0.45, and the phone clips never fall below 0.75. A pair such as accept 0.60 / inconclusive 0.40 would have verified 18 of 33 owner trials (all 11 phone clips, 7 meeting windows), left 15 inconclusive and verified none of the 275 negatives; accept 0.50 / 0.35 would have verified 27 of 33. **The channel matters:** the same voice scores about 0.2 lower on the meeting microphone than on the phone, which supports the plan's rule that meeting identification (32A.M) needs its own threshold, separate from live phone verification.

**What it does not show.**
- It is a handful of people: 119 windows from six speakers, strongly correlated within a speaker, so the effective number of independent impostors is about six, not 275. Zero false accepts here does not bound the rate for a sibling, a similar voice, a different language or accent, or an attacker choosing a voice.
- Windows are clean single-speaker stretches from the diarization; overlapped speech, which is harder, is excluded.
- Still unmeasured, and the main open gaps: **replay and synthetic-owner probes** (they likely score near the owner's own range, so a threshold cannot help against them and the UI must not imply it does), a **consenting second person** recorded on the phone, **noisy-room and next-day owner clips**, and the owner's label confirmation.
- Candidates are measured on the same data that picks them; held-out clips will probably score lower.
