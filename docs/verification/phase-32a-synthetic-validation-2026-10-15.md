# Phase 32A.V automated synthetic-audio validation (2026-10-15)

Branch `feature/phase-32a-voice-identity`. **Nothing deployed, merged or activated; the homelab database, key files and every real voice profile were not touched; no threshold is selected.** This stage runs before any physical-phone UAT.

## Read this first: what this evidence is and is not

| | |
|---|---|
| **Functional results** (sections 2 to 6) | The pipeline behaves: it transcribes, embeds, matches, fails safe, survives bad input and an outage. These are pass/fail. |
| **Synthetic measurements** (sections 3, 4, 7) | Similarity scores and error rates *on machine-generated voices*. The generated voices are **not independent human speakers** (11 of the 12 come from one formant synthesiser; there is one neural voice), there is no microphone, handling, room or phone, and replay is a digital file re-submission. **None of these numbers is a real-world FAR or FRR and none should be quoted as one.** |
| Thresholds | Fixed before the run and used **test-only** (accept 0.60, uncertain 0.40) only so the "verified" branch could be exercised in a throw-away app instance. Not a proposal. The hub under test ran uncalibrated first and reported `unavailable / not_calibrated`, as designed. |

## 1. Method and isolation

- **TTS reused, none deployed.** `tools/voice_identity_synthetic_corpus.py` runs the hub's own `reachy_hub.tts` (`PiperTTS` with the deployed `en_US-lessac-medium` voice, and `EspeakTTS`) inside a throw-away `--network none` container from the existing hub image. 12 voices x 21 phrases = **252 clips**: Piper lessac; espeak-ng `en-us`, `en-gb-x-rp`, `en-gb-scotland`, `en-029` and variants `+m3 +m7 +f2 +f4 +adam +Alicia`, `rp+f3`. Phrases: 8 enrolment phrases (the app's), 5 short (0.8 to 1.5 s), 5 medium, 3 long (up to 10 s). Clips are 22.05 kHz and are converted to the phone's mono 16 kHz PCM16 before use.
- **Real pipeline.** Hub STT `FasterWhisperSTT` `small.en` (the hub's `STT_MODEL`, CPU); the real speaker service code (SpeechBrain ECAPA, `0f99f2d0`, CPU, 4 threads); the hub's real `/voice-identity/*` routes in-process with a real encrypted `PostgresVoiceProfileStore`; an in-memory Companion Core for the conversation.
- **Isolation.** A separate PostgreSQL container (loopback port 55477, since removed), a database created for the run and dropped afterwards, migrated to head `038_voice_profiles` by core's own Alembic chain (`voice_profiles` empty at start), a random in-memory key, owner id `synthetic-test-owner`. The harness refuses to start against any other database port.
- **Corpus reproducibility.** The frozen corpus (252 clips, manifest SHA-256 `bd881017…da3a`) is kept outside the repository in `~/reachy-backups/phase32a-synthetic/` (0700) with the full JSON report; all 252 hashes verified before the run. **Regeneration is byte-identical for 8 of 12 voices (all espeak except `+f2`, `+Alicia`, `rp+f3`) and not for the other four** (Piper samples with noise; those three espeak variants add jitter). A regenerated Piper clip of the same text scores a median cosine of **0.89** (range 0.75 to 0.96) against the original; the three espeak variants 0.98 to 1.00. So the corpus is frozen, not re-derived, and Piper clips vary between runs the way different takes of one speaker would.
- Commands: `tools/voice_identity_synthetic_corpus.py` then `tools/voice_identity_synthetic_validation.py CORPUS --regen CORPUS2 --out report.json` (needs `SYNTH_PG_URL`, `SIDECAR_URL`, `CUDA_VISIBLE_DEVICES=""`).

## 2. Functional results

| Check | Result |
|---|---|
| Corpus integrity (252 hashes) | pass |
| Migration 038 on an isolated database: upgrade, `rollback-038.sql` (head returns to 037, table gone), upgrade again (empty table) | pass (separate check, fresh database) |
| Uncalibrated hub: a medium phrase through `/voice-identity/verify` | pass: HTTP 200, `unavailable`, reason `not_calibrated`; nothing `verified` without thresholds |
| Enrolment of three separate synthetic identities through the real routes (8 clips each, consent, reauthentication, replace and delete) | pass, profiles stored encrypted in the isolated database |
| Malformed audio, 18 cases x 3 routes (verify, enrolment sample, turn): empty, text, header only, truncated, header claiming 1 GB, junk after a header, 8-bit, stereo, 8 kHz, 44.1 kHz, 0.2 s, silence, DC, square wave, white noise, 20 s, over 2 MiB, MP3 bytes | **pass: no 5xx, no crash, nothing non-speech ever `verified`.** Statuses 200, 413 or 422 only |
| Conversation fallback: normal turn; speaker service unreachable; no profile; silent clip | **pass:** reply delivered in the first three, `unavailable` with reason `service_unavailable` / `no_profile`, the session stayed valid; silent clip answered 422 (the app keeps listening) |
| Evidence binding: evidence for an older utterance is gone after a newer turn; the current one is present | pass |
| Voice result never altered authority | not exercised here beyond the hub tests: the turn route still sends text through the ordinary path, and the earlier hub test shows a verified owner still gets core's "can't accept that confirmation by voice" |
| **Defect found and fixed by this stage** | The speaker service returned HTTP 500 for a WAV truncated mid-sample (odd byte count). The hub degraded safely (`unavailable` / 503 on enrolment) but it was a server error on user input. Fixed in `server.py` (stray byte dropped); regression test added. After the fix a truncated upload gives `uncertain` |

**Functional failures in the final run: 0.** (One earlier run showed two harness mistakes, a quality-gated probe and a valid long clip misclassified as malformed; both were corrected in the harness, not in the product.)

## 3. Transcription accuracy (hub STT, synthetic speech)

Overall word error rate **5.7%** over 2,868 words. By voice: Piper 1.3%; espeak 2.9% to 7.5%, except `+Alicia` 18% (a hard-to-understand variant). By length: short 2.8%, medium 4.8%, long 2.3%, enrolment phrases 10.2% (they include "nine green bottles stood…" and "summarise", which espeak mangles). Typical error: `Stop the music` heard as `Top the music`. Latency p50 0.98 s per clip (real-time factor 0.33). This measures the recogniser on clean synthetic speech, not on a person on a phone.

## 4. Speaker-embedding consistency and distinguishability (synthetic voices)

| Cosine similarity of embeddings | n | p05 | p25 | median | p75 | p95 | max |
|---|---|---|---|---|---|---|---|
| Same voice, different phrase | 2,520 | 0.49 | 0.66 | 0.75 | 0.82 | 0.88 | 0.96 |
| Different voice, different phrase | 27,720 | 0.04 | 0.14 | 0.23 | 0.43 | 0.78 | 0.95 |
| Same text, different voice | 1,386 | 0.05 | 0.17 | 0.28 | 0.56 | 0.90 | 0.96 |

AUC (same voice vs different voice) **0.92**, d' 2.29. Nearest-centroid identification of the generating voice from held-out phrases: **140 of 156 (90%)**; every error is between espeak voices (for example `en-us` taken for `en-gb-rp` 4 times, `+m3` for `en-us` 3 times). **Piper vs espeak is cleanly separable; espeak voices and variants are only partly separable**, which is expected because they share one synthesiser. This says the model can tell these generated voices apart to a degree. It says nothing about how well it separates people.

## 5. Identity matching through the real routes (synthetic-only)

Each identity enrolled from its 8 enrolment phrases; trials are the other 13 phrases of that voice (genuine) and all 231 clips of the other 11 voices (impostor). Test-only thresholds 0.60 / 0.40.

| Enrolled synthetic identity | Genuine states | Other generated voices | AUC | Genuine score median | Impostor score median / p95 / max |
|---|---|---|---|---|---|
| Piper lessac | 9 verified, 4 uncertain (short or lower-quality clips) | **0 of 231 verified**, 28 uncertain, 203 not verified | 1.00 | 0.81 | 0.10 / 0.30 / 0.36 |
| espeak `en-us` | 10 verified, 3 uncertain | 87 of 231 verified, 51 uncertain, 93 not verified | 0.83 | 0.86 | 0.45 / 0.89 / 0.91 |
| espeak `us+m3` | 10 verified, 3 uncertain | 79 of 231 verified, 48 uncertain, 104 not verified | 0.88 | 0.84 | 0.39 / 0.87 / 0.89 |

Reading: an identity enrolled from the **one neural voice** was never confused with any espeak voice, and its genuine scores sit well above the other voices (a gap of roughly 0.4 between impostor max and genuine median). Identities enrolled from an **espeak voice are accepted for other espeak voices** at the test thresholds (they are the same synthesiser with different settings) — 166 such cases are listed as observations in the report, none for Piper. Threshold sweep (synthetic only; FAR = other generated voices accepted, FRR = the identity's own clips rejected):

| Threshold | Piper FAR / FRR | espeak `en-us` FAR / FRR | espeak `us+m3` FAR / FRR |
|---|---|---|---|
| 0.3 | 4.3% / 0% | 58% / 0% | 58% / 0% |
| 0.4 | 0% / 0% | 54% / 0% | 49% / 0% |
| 0.5 | 0% / 7.7% | 45% / 0% | 43% / 0% |
| 0.6 | 0% / 7.7% | 43% / 0% | 39% / 0% |
| 0.7 | 0% / 15% | 35% / 0% | 35% / 0% |
| 0.8 | 0% / 46% | 28% / 38% | 21% / 31% |
| 0.9 | 0% / 100% | 2.6% / 69% | 0% / 77% |

Only 13 genuine trials per identity: an FRR step is 7.7 percentage points, and "0% FAR" over 231 trials of a handful of near-identical voices is not evidence of a 0% rate for people. These tables show the machinery works and what a confusable voice looks like; they are **not** threshold evidence for the owner.

## 6. Degradations (Piper identity; 13 genuine clips, 12 other-voice clips per condition)

Noise, room and codec are simple stand-ins (white noise, an exponentially decaying random impulse response, PyAV MP3/AAC/Opus encoders, a band-pass for telephone audio).

| Condition | Genuine (verified / uncertain / not verified) | Median genuine score change | Other voices verified | Max other-voice score | STT WER (6 clips) |
|---|---|---|---|---|---|
| none | 9 / 4 / 0 | 0 | 0 | 0.22 | 3.7% |
| white noise SNR 20 dB | 10 / 3 / 0 | -0.07 | 0 | 0.19 | 0% |
| SNR 10 dB | 8 / 3 / 2 | -0.15 | 0 | 0.17 | 0% |
| SNR 5 dB | 3 / 7 / 3 | -0.24 | 0 | 0.16 | 0% |
| SNR 0 dB | 0 / 10 / 3 | -0.33 | 0 | 0.13 | 15% |
| reverberation RT60 0.3 s | 9 / 4 / 0 | -0.11 | 0 | 0.19 | 3.7% |
| RT60 0.6 s | 9 / 2 / 2 | -0.16 | 0 | 0.19 | 18.5% |
| RT60 1.0 s | 7 / 4 / 2 | -0.19 | 0 | 0.14 | 3.7% |
| MP3 64 kbit/s | 9 / 4 / 0 | -0.01 | 0 | 0.20 | 3.7% |
| MP3 24 kbit/s | 9 / 4 / 0 | -0.17 | 0 | 0.21 | 3.7% |
| AAC 32 kbit/s | 9 / 4 / 0 | -0.03 | 0 | 0.22 | 3.7% |
| Opus 12 kbit/s | 9 / 4 / 0 | -0.06 | 0 | 0.18 | 3.7% |
| telephone band (8 kHz, 300 to 3400 Hz) | 0 / 13 / 0 | -0.24 | 0 | 0.20 | 0% |
| resample 16k to 8k to 16k | 6 / 7 / 0 | -0.22 | 0 | 0.23 | 3.7% |
| resample 16k to 44.1k to 16k, and to 22.05k | 9 / 4 / 0 | 0.00 | 0 | 0.23 | 3.7% |
| low volume (-30 dB) | 1 / 12 / 0 | 0.00 | 0 | 0.23 | 0% |
| clipping (x8 gain) | 0 / 13 / 0 | -0.27 | 0 | 0.17 | 0% |

Findings: scores fall steadily with noise and reverberation and the verdict degrades to *uncertain* (the designed fail-safe) rather than flipping to a false accept; bandwidth loss to telephone quality moves every genuine clip below the test accept level; ordinary resampling and 64 kbit/s MP3 hardly matter; a quiet or clipped clip is rejected by the quality gate before scoring. No other voice was ever verified under any condition. For **this** voice pair. Real phone microphones, real rooms and real noise remain unmeasured.

## 7. Digital replay (NOT a physical replay attack)

Previously generated WAV files re-submitted to the endpoint. Identical bytes: **13 of 13 same state, score difference 0.0**; 9 of 13 verified again, as they did the first time. A lossy MP3 re-encode of six of them: 2 verified, 4 uncertain. This confirms the documented position: **there is no replay protection** (`replay_protection: "none"`, no anti-spoof model); a clip that verifies once verifies again. The only freshness guarantee is that evidence is bound to its utterance and expires: evidence for an older utterance was not retrievable after a newer turn. No claim is made about a loudspeaker-and-microphone replay.

## 8. Latency (dev box, 20 shared CPUs, in-process hub, no phone or Tailscale in the path)

| Stage | n | p50 | p95 | max |
|---|---|---|---|---|
| TTS synthesis, Piper | 21 | 0.10 s | 0.28 s | 0.32 s |
| TTS synthesis, espeak-ng | 231 | 0.011 s | 0.023 s | 0.037 s |
| Resample to 16 kHz | 252 | 2 ms | 4 ms | 5 ms |
| STT (hub `small.en`), clip median 3.0 s, max 10.1 s | 252 | 0.98 s | 1.22 s | 1.26 s |
| Speaker embedding (service) | 284 | 0.19 s | 0.52 s | 0.62 s |
| Hub `/voice-identity/verify` end to end | 1,215 | 0.19 s | 0.54 s | 0.63 s |
| Hub `/voice-identity/turn?converse=false` (STT and speaker check concurrently) | 1 | 0.90 s | | |
| Hub `/voice-identity/turn` with conversation (no language model attached) | 2 | 0.86 s | 0.87 s | |

STT dominates a turn; the speaker check adds nothing visible because it runs concurrently with STT and is faster. The turn rows have too few samples to quote percentiles, and the conversation time excludes any real language model. The phone-to-hub network, the Android capture and endpointing delay (about one second of trailing silence) and the second `/messages` round trip are not in these numbers.

## 9. Failure cases and observations (full lists in the JSON report)

Functional failures: **none** in the final run (the speaker-service 500 on a truncated WAV was found, fixed and covered by a test). Observations, which are not faults: 15 STT clips with more than 25% word error (espeak enrolment phrases, `+Alicia`, `Top the music`); 16 voice-identification confusions, all between espeak voices; 166 cases where an espeak-identity accepted another espeak voice at the test-only threshold; enrolment accepts white noise, silence-with-noise, DC and square-wave clips as *quality-passing* samples (the energy gate cannot tell speech from loud noise; the draft's consistency check and the owner's review are the protection, and a speech detector would be a possible later hardening); a 20 s repeated-speech clip returned `uncertain`.

## 10. What still needs a physical phone and human speakers

Everything below is unmeasured by this stage and cannot be replaced by synthetic audio:

1. **`AudioRecord` on the real phone:** permission flow, the `VOICE_RECOGNITION` source's processing, sample rate and gain, microphone contention with the recogniser and with the meeting recorder, and what happens on interruption (a call, another app).
2. **Endpointing in real rooms:** the energy gate against quiet speakers, breathing, fans, TV and street noise; false triggers; clips cut short or run on.
3. **Bluetooth and speakerphone routes** for capture, and the audio route for replies.
4. **Real network behaviour:** Tailscale loss and reconnect, hub down mid-turn, upload latency, and the true end-to-end response latency a person experiences.
5. **Real human voices:** owner FRR across days, tiredness, colds, distance, hold and mic position; the consenting non-owner FAR, including siblings or same-sex similar voices; the enrolment consistency limit (0.35) and quality limits on real voices.
6. **Physical replay and real synthetic-voice attacks:** a recording played through a loudspeaker into the phone, and voice-converted or cloned *owner-like* speech. Only these can say anything about spoofing.
7. **Real phone-codec and noise effects** (the OS audio path, AGC, noise suppression) that these simulated degradations only approximate.
8. **A human acceptability pass:** the enrolment prompts, wording of "unverified / inconclusive", and the voice-mode line.
9. **The calibration itself**, and any threshold decision, use the [GV protocol](phase-32a-gv-protocol.md) recordings; the synthetic stage does not substitute for them.
