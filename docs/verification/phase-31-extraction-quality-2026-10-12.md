# Phase 31 extraction-quality improvements and validation (2026-10-12)

Approved scope: the two bounded changes recommended by the [model diagnostic](phase-31-model-diagnostic-2026-10-12.md) (prompt, and deterministic validator plus display), then one validation on the same recording with the existing 7B. No new model, scoring framework or verification service. Phase 49 mechanisms and the Phase 48 frozen files are unchanged (`git diff` over them against `HEAD` is empty). Nothing is merged, pushed, deployed, migrated or enabled. Recording, transcript and outputs stayed in the session scratchpad (`0600`); this record has counts only. The baseline is the frozen first-round result (prompt `meeting-analysis-1`, validator before this round) on the same 24-minute recording, judged by the same single reader with the same S / P / N rule (S the quote supports the item as that kind of finding, P related but changed, N unsupported or the wrong kind).

## What changed

1. **Prompt (`meeting-analysis-2`).** States what each kind is and is not: a decision is an explicit agreement (not a proposal, opinion, fact or topic); an action is a promise or request (not an idea, a need, a general intention, something done or a description); an open question is a real question not answered in the next lines (not rhetorical, answered or small talk); everything else is ordinary discussion; the quote must be the sentence that itself makes the agreement, promise or question; no speaker labels in the wording; when unsure, leave it out.
2. **Validator (`meeting_analysis/support.py`, deterministic, transcript evidence only).**
   - Decision is `stated` only with agreement wording and no hedge or proposal wording (maybe, could, I think, what if, if we, suggest...).
   - Action is `stated` only with a promise or request aimed at someone (I'll, we will, going to, let me, can you, please, send me, give me, by Friday, I've asked ...) and no hedge or condition; a need, an idea or an offer ("I can", "if you need") is `uncertain`.
   - Open question is `stated` only if it is built as a question of at least four words (interrogative word, inverted auxiliary, or "nobody knows who ..."), **with or without a question mark**, and not answered: the reply is looked for inside the quote after its question and at the start of the next two transcript lines (yes, no, yeah, "we do", "it's not" ...). Fragments ("right?", "what about you?") are never `stated`.
   - Speaker labels ("Speaker 1", an owner-given speaker name) are removed from the wording unless the quote itself contains them ("Speaker 1 will send the report" becomes "Send the report", "Speaker 2 asks whether X" becomes "X", other mentions become "a participant"), with a note.
   - Every finding is still kept; failing a check only makes it `uncertain` with the reason in plain words. Nothing is promoted and no task is created.
3. **Display (web).** One notice states that everything is model-written from a speech-to-text transcript and unverified. `stated` findings come first; `uncertain` ones are collapsed under "Weaker suggestions (n)" in each group (actions, decisions, open questions), still readable, confirmable (actions) and dismissable; "(unverified)" on each group; "No clear promise or request was found" when only weak actions exist.
4. **Regression tests** (`test_meeting_analysis.py`, 42 core tests now): proposals and opinions listed as decisions stay `uncertain` and are kept; an answered question (inside the quote or in the next line) is not `stated`, questions without a question mark are, small talk is not; genuine commitments and requests ("I'll send you the report", "Can you send me the design by Friday", "Let me know your architecture next week", "I've asked a named colleague ...", "Then I'll work with a named colleague ... You see what we can do") are not excluded, while an offer under a condition and a bare need are `uncertain`; one segment holding a decision, an action and a question gives three findings and a shorter re-quote of one promise is not a fourth; speaker labels never remain in the text. Web: 9 unit tests (stated first, weak collapsed and still actionable, nothing confirmed by itself, wording), and the Playwright spec (weak decision collapsed, hidden until opened, still dismissable, notice shown).

A bug found by the real run and fixed in this round: "you see what **we can** do" tripped the hedge rule and demoted a clear first-person commitment ("Then I'll work with a named colleague ..."). "we can" and "you can" were removed from the hedge list; "I can" (an offer) stays. It is covered by a test.

## Validation: 7B, same recording, before and after

| | Baseline (frozen) | After |
|---|---|---|
| Wall time, 5 chunks | 53 to 57 s | 50 to 53 s (prompt tokens 12,185 to 13,175) |
| Items found | 18 (13 actions, 1 decision, 4 questions) | 17 (15 actions, 1 decision, 1 question) |
| Judged S / P / N | 4 / 3 / 11 | 3 / 5 / 9 |
| Share unsupported (N) | 61% | 53% |
| **Items in the default view (`stated`)** | 4: 3 S, 1 P, 0 N | **3: 3 S, 0 P, 0 N** |
| Strong commitments (of 10) with a supported finding anywhere (S or P) | 3 | 6 |
| Strong commitments with no supported finding | 7 | 4 |
| Genuine open questions listed | 1 | 0 (lost) |
| Genuine decisions listed | 0 | 0 (the recording has no explicit one) |
| Duplicates | 0 | 0 |
| Speaker labels in finding text | 0 | 0 |
| Output stable between runs | identical twice | 16 and 17 items in two runs after the change (prompt changed between them) |

The reference commitments are the same list as the diagnostic, with one added after this run showed it: the sentence "I'm going to ask a named colleague to do ... the survey", which the baseline only cited through an unrelated quote and which is now found with the right one.

Validator-only replay on the **frozen baseline items** (no model call): the 14B's default view goes from 9 items (2 S, 1 P, 6 N: junk questions called `stated`) to 3 items, all S; the 7B's from 4 (3 S, 1 P) to 3, all S; "Speaker N" remains in none of the 44 and 18 item texts (14 of the 14B's had it).

## Reading

- The default view is now clean on this recording for both models' items (every `stated` finding is a supported one) and the weak ones are one click away, so the main review-burden problem of the diagnostic is addressed by the validator alone.
- The prompt helped the 7B find more supported commitments (3 to 6 of 10 loosely, 2 strictly supported) and cut wrong-kind noise, but did **not** fix its characteristic grounding failure: it still often cites a neighbouring sentence (9 of 17 are N). That is the model's, not something the prompt or validator can repair.
- The stricter question rule cost the 7B its one genuine question (it now lists almost none); recall of open questions is the price of the change, and the 14B was the only run that found it.
- Differences of one or two items are inside the reader's noise; one recording, one reader.
- The 14B was **not** re-run: the 7B result is mixed rather than clearly better, and the validator effect on the 14B was measured by replay without a GPU swap.

## Verification of the change

Ruff clean; core meeting-analysis 42, PostgreSQL 7, hub 15, web 288 (9 for this feature), Playwright 2 for this feature; full results below.

Final tree: full Python suite with the disposable PostgreSQL 3,293 passed, 31 skipped, 4 failed, all four the known baseline failures (the three of the earlier records and `test_web_client` chat sample, which fails identically at `HEAD`); the timing flake in `reachy-embodiment` did not recur. Whole Playwright suite 130 passed, 2 failed, the same two as before this round (the stale `notepad.spec.ts` wording and the intermittent mobile layout check). `ruff check services shared` and `tsc --noEmit` clean.
