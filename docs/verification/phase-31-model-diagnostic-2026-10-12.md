# Phase 31 extraction diagnostic: model, prompt or transcription? (2026-10-12)

Question: are the weak extraction results of the [Phase 31 audit](phase-31-meeting-analysis-2026-10-12.md#audit-of-the-real-recording-output-single-reader-no-independent-review) mostly model capability, prompt design or speech-to-text quality? Nothing was deployed, migrated, enabled or merged. Prompts, schema and validator were **not** changed: the production analysis service ran unchanged against both models. Recording, transcript and model outputs stayed in the session scratchpad (`0600`), not in Git; this record has counts only.

## Method

- Input: the owner's 24-minute test recording (349 STT segments, 4 diarization labels, 19,089 characters, 5 chunks), already through the live sidecars.
- Models through the existing model manager (ADR 0031), both served as `reachy-local`, context 8,192, temperature 0, Qwen3 thinking off as configured: **Qwen2.5-7B-Instruct-AWQ** (fast tier, normal) and **Qwen3-14B-AWQ** (Deep Local, one `run --lease` window holding the deep tier for all three 14B arms; the manager restored the 7B itself and reported `ready_t1`, healthy, no error).
- Arms per model: the original transcript (twice, to see variance) and a corrected transcript. Correction = three systematic, high-confidence term fixes applied through the existing `transcript_corrections` overlay on 12 segments ("data leak" to "data lake", "Stahub/Starhub" to "StarHub", "Ookar/Ooklar" to "Ookla"); nothing else was edited.
- Cloud: **not run**. No explicit authorization to send this recording out, and no sanitized equivalent was made.
- Judging: one reader (me), no independent review. Each item was marked S (the quote supports the item as that kind of finding), P (related but the item adds or changes something) or N (not supported, or the wrong kind). Reference commitments: 12 explicit ones identified by reading the sentences around every commitment-worded segment (9 strong, 3 weak); an action "catches" one if its evidence lies within two segments of it, and "with support" if it is also S or P.

## Measured results

| | Qwen2.5-7B | Qwen3-14B |
|---|---|---|
| Wall time, 5 chunks | 53 to 57 s | 170 to 181 s (3.2 times) |
| Completion tokens | 2,226 | 3,238 |
| Items (actions / decisions / questions) | 18 (13 / 1 / 4) | 44 (11 / 14 / 19) |
| Same input twice | identical | identical |
| Labelled `stated` / `uncertain` | 4 / 14 | 9 / 35 |
| Judged S / P / N | 4 / 3 / 11 | 10 / 8 / 26 |
| Share S, share S+P | 22%, 39% | 23%, 41% |
| Strong commitments (of 9) caught with support | 3 | 6 |
| Strong commitments missed | 6 | 3 |
| Unsupported because the quote is about something else (approximate, by reading) | about 6 of 11 N | about 3 of 26 N |
| Unsupported because the kind is wrong (an idea as an action, an answered or non-question as a question, a statement as a decision) (approximate) | about 5 of 11 N | about 23 of 26 N |
| Duplicates after the validator | 0 | 1 (same sentence as an action and as a question) |
| Items whose wording starts with a speaker label despite the instruction (counted by program) | 0 | 14 |
| Items shown if only `stated` ones are listed | 4 (3 S, 1 P, 0 N) | 9 (2 S, 1 P, 6 N) |

Deep Local overhead on top of the run: 75 s to load the 14B and 127 s to restore the 7B; Reachy's local model was unavailable for about 14 minutes in this session (the three 14B arms plus the swaps).

Corrected transcript: 7B kept 13 of 18 items by position and kind, 14B 39 of 44; judged quality did not change (7B 4 S / 2 P / 11 N of 17; 14B within one or two items either way). The fixes changed the words in the items ("data lake" instead of "data leak") and nothing else.

## Reading of the evidence

- **Model capability** explains the 7B's characteristic failure: in about 6 of its 11 unsupported items the quote is real but is about something else (it cites a neighbouring or earlier sentence for a conclusion drawn elsewhere). The 14B's quotes almost always match its items (3 of 26). The 14B also finds twice as many well-supported commitments (6 of 9 against 3 of 9). Capability is the reason the 7B misses commitments; it is not the reason for most of the noise.
- **Prompt and schema design** explain the 14B's noise and part of the 7B's: both models list ideas as actions; the 14B lists plain statements as "decisions" (14, almost none agreed) and chat fragments as "open questions" (19, mostly junk), and ignores "do not start with a speaker label". The `?` rule in the question label lets 6 junk questions through as `stated`. The `support` label is well calibrated for the 7B and poorly for the 14B.
- **Speech-to-text quality** is a minor factor: fixing the three systematic term errors did not change factual support for either model. Garbled sentences remain (a person's name, "shine"), which no term fix reaches, and they affect a handful of items.
- Both models are deterministic here at temperature 0, so the audit numbers are repeatable.

## Decision

**Improve the extraction workflow first; keep the 7B as the default; do not add a cloud fallback; offer Deep Local only as an explicit, owner-chosen re-run once the workflow change is in.**

Why not the others: switching to the 14B alone buys recall but multiplies the review burden (44 items, 26 unsupported, 3.2 times slower, plus the fixed swap cost and about two minutes during which Reachy's model is not available) at the same share of supported items. A cloud fallback has no evidence in its favour (not measured, and the recording is local-only data under ADR 0030/0032) and the problems seen are not ones a larger model alone removes.

Smallest changes the data supports (none made here; each needs your approval and a re-measure on the same transcript):

1. Prompt: say that a decision requires explicit agreement and a question must be one still open after the speaker's own answer; forbid speaker labels in the wording (the 14B violated this 14 times).
2. Validator/UI, no model call: show only `stated` items by default with the others collapsed under "weaker suggestions", and make the question label require a real question (more than a short fragment and an interrogative, not just a `?`). On this recording that alone turns the 7B's list into 4 items with no unsupported one, at the cost of recall.
3. Then, for recall, an explicit "analyse with Deep Local" option reusing the existing deep-job flow and warning, if the owner wants it; the 14B plus the same two filters is the combination worth measuring next.

## Limits

One recording, one reader, one set of reference commitments chosen by that reader, a 24-minute meeting (not the 30 to 60 minutes of the acceptance criterion), and a correction set of only three term families. Differences of one or two items are within the reader's noise. The 14B was run with thinking off as the manager configures it; a thinking mode was not tried. No cloud model, no second reader, and no re-measure after the proposed changes.
