# Phase 32A.V: owner-approved calibration of live owner verification (2026-10-15)

**Decision.** After reading the interim evidence ([record](phase-32a-gv-interim-2026-10-15.md)), the owner accepted it as sufficient without the remaining tests ("we will adjust accordingly if it's not accurate later"). The thresholds below were chosen by the assistant from that evidence and applied on the owner's acceptance; they are provisional and reversible.

| | |
|---|---|
| Accept (shown as "Owner voice verified") | **0.50** cosine similarity to the owner's template |
| Inconclusive band | 0.35 up to 0.50 ("Owner match: inconclusive") |
| Not verified | below 0.35 |
| Applied | 2026-10-15 15:57 UTC: `.env` (backup `env-before-calibration`), hub recreated alone (same image `964b2618039d`; core, speaker and coding-agent untouched; the Phase 48 segment continues) |
| Revert | remove the two threshold lines from `.env` and recreate the hub (`up -d --no-deps --no-build reachy-hub`): the app returns to "unverified" for every result |

**Why these numbers.** The highest non-owner score seen was 0.235 (130 windows from about ten people in two recordings); the owner's lowest scores were 0.446 on a meeting microphone and 0.754 on the phone. 0.50 sits about 0.27 above the highest non-owner and about 0.25 below the lowest phone clip, leaving room for noise and day-to-day drift (synthetic tests showed noise and reverberation lowering a score by 0.1 to 0.3 before it flips); 0.35 sits 0.12 above the highest non-owner, so a score that merely resembles a voice is called inconclusive, not not-verified. On the collected data this pair verifies all 11 phone clips, 16 of 22 meeting-mic windows, and none of the 275 non-owner or machine-generated windows; it classifies no non-owner as inconclusive.

**What was accepted without evidence.** No consenting second person recorded on the phone (the non-owner evidence is two meetings, about ten people); no replay or synthetic-owner probes; one noisy-room clip; no next-day owner clips. Expect, and watch for: owner clips on another day or in noise scoring lower and showing as inconclusive more often (the first adjustment would be lowering the accept value toward 0.40); a similar voice scoring higher than anything seen (raising the inconclusive floor); and a replay or synthetic voice of the owner verifying, which this threshold cannot prevent.

**Unchanged by this decision.** A voice result is display-only identity evidence for one utterance: it lets nothing happen, does not change the privacy ceiling for spoken requests, does not replace a typed confirmation, and never ends a login. Meeting speaker identification (32A.M), server-side per-device sessions (32A.1) and every robot feature remain off and unbuilt. Merging the branch remains a separate approval. Meeting-room identification will need its own threshold (the same voice scored about 0.2 lower on the meeting microphone).

**Verification.** After the recreate: the hub reports calibrated with accept 0.5 and uncertain 0.35, healthy, voice providers ready in 20 s; hub read baseline identical to before; core and speaker uptimes unchanged; hub environment differs from before only in the two threshold values. Not verified: the app showing "Owner voice verified" on the phone (the owner's next voice turn will show it).
