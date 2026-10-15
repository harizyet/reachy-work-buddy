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
