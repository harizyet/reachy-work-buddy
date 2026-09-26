# STT model comparison (2026-09-26)

Why: the 24e physical run misheard "cold and the flu" as "coil and the
flue" and "code word" as "court would". The owner chose to try a larger
Whisper model and noted the robot's microphones may be the limit instead.

**Synthetic only.** Ten phrases from the run, spoken by the hub's Piper
voice (`en_US-lessac-medium`), resampled to 16 kHz and scored clean and
with white noise at 10 dB and 5 dB SNR. The models ran in throwaway
containers from the production hub image on the homelab CPU (i9-13900H),
using int8 and faster-whisper's default beam of 5. "Exact" means the
normalized transcript matched the phrase. Clean TTS doesn't reproduce the
robot microphone, room or accent, so none of this shows the physical
mishearings are fixed.

| Model | Clean | 10 dB | 5 dB | Median per clip |
|---|---|---|---|---|
| base.en (deployed) | 9–10/10 | 7/10 | 5–7/10 | 0.36–0.39 s |
| small.en | 9–10/10 | 8–10/10 | 8/10 | 0.90–0.95 s |
| distil-small.en | 9/10 | 7/10 | 3/10 | 0.81–0.84 s |
| distil-medium.en | 9/10 | not run | not run | 2.29 s |

Ranges cover two runs with different noise seeds; the first run used the
hub's own prompt with the persona name, the second only "Hello Reachy.".
medium.en and large-v3-turbo weren't run: distil-medium already costs
about 2 s per turn. For small.en, greedy decoding (beam 1) wasn't faster,
and 8 CPU threads were slower (1.2–1.4 s) than the default.

The typical base.en noise errors were "octopuses" → "Oct fuses",
"Tokyo" → "total", and "code word" → "cruel word". Most remaining small.en
misses are "a flu" for "the flu".

**Outcome:** small.en is the only candidate that hears noisy speech better,
and it adds about 0.55 s of STT to every voice turn. The 24e warm run
measured non-search p50 3.63 s against the ≤ 4 s budget, so small.en would
likely take p50 over that budget. `STT_MODEL=small.en` is set in the
homelab's private `.env` for the trial; the hub rebuild and the physical
check are still to do. Unset `STT_MODEL` to return to base.en.
