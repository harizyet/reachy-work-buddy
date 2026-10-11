# Phase 48F: selective shadow, frozen evidence window (opened 2026-10-10 14:56 UTC)

**Status: WINDOW OPEN. `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED=true` in production alongside indexing and retrieval; `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED` is not set and is not even passed by Compose. Production replies are unchanged. Nothing in the router, registry, retrieval, evidence rules or answerer may be tuned during the window unless a privacy, security or data-integrity defect is found (it would be logged here and would end the clean sample). The final report and recommendation (PROMOTE TO 48G / PROMOTE WITH NARROW CHANNEL/SCOPE / DO NOT PROMOTE) are written when the window closes: this page is completed then.**

## 1. Activation

| Item | Value |
|---|---|
| Flags in core | `KNOWLEDGE_INDEXING_ENABLED=true`, `KNOWLEDGE_RETRIEVAL_ENABLED=true`, `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED=true`, `KNOWLEDGE_SELECTIVE_SHADOW_LOG_PATH=/data/shadow-router/selective-shadow.jsonl` (the persistent volume); selective answering absent. Memory candidates review and capture unchanged |
| Compose | pass-through for the shadow flag and log path only (defaults off/empty); the answering flag is deliberately not passed |
| Image | core `027ed2d6437e` (commit `9c8214a`), recreated at 14:56:34 UTC; no code change |
| Capture trial | counters read before the restart (`{"attempted":2,"no_match":2}`: the two 48E verification probes), restart logged as a boundary in the [48B trial log](phase-48b-capture-trial-2026-10-10.md); window not restarted |
| Frozen code (first 16 hex of sha256) | `selective_answer.py` 1dbdcad5dbf74b2d, `selective_shadow.py` 2b6390484df5f1e9, `shadow_telemetry.py` e47fbcad580b817b, `retrieval.py` fc4fbfbdadc05a57, `search.py` cfff762975d37e97, `revalidate.py` d08e8794c4cfbc7f, `qualify.py` 331742adbd44bc2c, `routing.py` 03d13c6457696175, `answerability_b1/*.py` (combined) b594996c38d10771; the B-1 candidate freeze check passes ("candidate freeze intact") |
| Rollback | remove the three shadow lines from `.env` (or set the flag false) and `up -d --no-build --no-deps companion-core`; deleting the telemetry file erases everything it recorded. Indexing and retrieval stay on unless separately switched off |

## 2. What the shadow records, and what it cannot

Aggregate counters from a fixed vocabulary, one JSON line per hour, mode 0600, retention 30 days ([telemetry policy](../phase-44e-selective-shadow-telemetry-policy.md)); the only export is `python -m companion_core.knowledge.selective_shadow report <file> [--min-cell 5] [--by day]`, which hides every cell under 5 (and a complementary cell). No prompt, reply, evidence, title, id or session is written, by construction. After the ordinary reply is final, the text is classified (typed / ambiguous / untyped / ineligible) and, for typed and ambiguous turns, the deterministic path is assessed through the real retriever and revalidation under THAT turn's channel access (a spoken turn is public only) and reduced to categories.

| Requested review item | Source |
|---|---|
| total turns observed; knowledge-like admitted; typed / ambiguous / untyped / ineligible (with reasons: not knowledge, status question, attached meeting; untyped: not understood, needs structured data; anchors) | shadow `funnel`, `class`, `ineligible_reason`, `untyped_reason`, `anchor` |
| supported / unsupported / conflicted / historical / mixed / negative-supported / negative-unsupported / failed, timeout | shadow `outcome` |
| citations 0 / 1 / 2 / 3+; max sensitivity of what would be cited | shadow `citations`, `max_sensitivity` |
| production path: generic model / deterministic handler / action boundary / selective | shadow `production_path` |
| untyped personal-knowledge questions the generic model answered | shadow `record_dependent_untyped_by_path` (the `model` cell) |
| voice versus text | shadow `modality` |
| latency of the assessment | shadow `latency_ms` buckets; plus host/chat/swap observations |
| **Unsupported questions where retrieval still returned related records** | **not recorded by the shadow** (no retrieved-count in its vocabulary). Measured instead by the offline probe, section 3 |
| **Would selective answering have prevented an unsupported answer / abstained needlessly** | **not recorded** (the shadow deliberately makes no semantic comparison with the production reply, and recording one would store content). Measured instead on questions with known ground truth, section 3 |

Because those two questions cannot be answered from aggregates without logging content, the false-supported evidence comes from the offline probe, which is the only place ground truth exists. The shadow tells how often and in what shape real questions would be claimed; the probe tells whether what is claimed is right.

## 3. Offline probe on the real production corpus (frozen, run at the start and again at the end)

`tools/knowledge_selective_probe.py` runs the same classification, retrieval, revalidation, evidence rules, verification and rendering as the shadow and the live answerer, read-only, in a throwaway container from the production image. The 42 questions (authored before the first run; sha256 `145bd80237a9f4b48091a621b3e4a529115bdb555d8c6f035ecba35664fe2e5d`; text and replies kept in the private directory `~/.local/share/reachy-phase48e/`, since they paraphrase the owner's notes and meeting) cover answerable note and meeting facts, status questions, absent facts, loosely related absent facts, spoken (public-ceiling) turns, and non-knowledge. Categories only, no text: [start results](phase-48f-probe-start.json).

### Start-of-window result (2026-10-10 14:58 UTC)

| Truth | n | Ineligible | Untyped | Typed | If typed or ambiguous: state |
|---|---|---|---|---|---|
| answerable from notes or the meeting | 17 | 1 (a task-status phrasing) | 15 | 1 | unsupported (1) |
| absent facts (10 plain, 6 loosely related) | 16 | 6 | 10 | 0 | none |
| spoken (public-only) turns about private records | 3 | 1 | 2 | 0 | none |
| status questions | 3 | 3 | 0 | 0 | handled by deterministic handlers before this path |
| non-knowledge | 4 | 4 | 0 | 0 | none |

Observations (these are the starting evidence, not a conclusion):
1. **Routing coverage on natural questions is very low.** Of 17 questions whose answers are in the corpus, 1 was typed, and it was answered conservatively as unsupported (the minutes record "Decisions: none recorded", so "I couldn't establish that" is a cautious non-answer rather than a wrong one); 15 were untyped ("not understood"), 1 was routed as a status question. The deterministic path understands the question forms of its structured relations, and most of the owner's natural phrasings ("What did I write in my note about...", "What was said about X in the meeting?") are not among them.
2. **False-supported claims: 0 of 1 claimed turn** (and 0 of 42 questions produced a supported claim at all). No restricted exposure: the three spoken questions about private records were never typed.
3. **Six absent-fact questions were classified `ineligible / not_knowledge`** ("Who owns the Ferry queue schedule?", "Who approved the vendor contract?", ...): they carry no record noun or known term, so they would stay on the existing generic-model path, which is the status quo and not a regression, but is also where an ungrounded personal-looking answer can come from. This is what `record_dependent_untyped_by_path` and the unrecorded safeguard concern are about.
4. The live shadow, not this probe, decides whether the owner's real questions look like these.

## 4. Verification on the live system

Production reply unchanged (a typed knowledge-like probe and an arithmetic probe at 14:57:02 UTC answered by the generic model exactly as before: "Two plus two is four." and "I don't have access to your notes ..."). **These two probes are the only non-owner turns in the telemetry**: one non-knowledge turn and one knowledge-like (classified by the shadow, not answered by it); subtract them from the final counts. **First telemetry observed (15:02 UTC, by a graceful stop of core, a logged boundary):** two turns, both admitted and processed ok: one `ineligible / not_knowledge` (the arithmetic probe), one `untyped / not_understood` with anchors first-person, record noun and known term (the notes probe), both modality text, both `production_path = model`, `record_dependent_untyped_by_path.model = 1`, assessment latency in the `<=5 ms` bucket. Only category counts: no text, id or title. This confirms the shadow classifies live turns, writes only vocabulary counters, and left the replies alone. **Operational note:** the telemetry is flushed by the next counted turn after five minutes, or at shutdown, not by a timer, so counts from a quiet period live in process memory until then. Stop core gracefully (`docker stop -t 30`) and copy the file before reading it at the end of the window; a crash loses whatever has not flushed.

## 4a. Owner direction after the start-of-window result (2026-10-10)

Keep 48F running as is; no change to router rules, retrieval, evidence rules, the selective answerer, shadow telemetry or candidate capture rules. Interpretation at this point: safety and groundedness promising (0 false-supported claims and 0 restricted exposure observed), routing coverage very low, likely usefulness questionable. **The live hypothesis: does normal owner usage show the same low routing coverage as the frozen offline probe?** Collect normal Web/Android usage until 100 to 200 genuine knowledge-like turns or 7 to 14 days, unless a privacy or security issue appears first; do not manufacture queries to improve coverage. **48G stays blocked.** The frozen 42-question probe file is preserved unchanged (sha256 above) and is rerun exactly as is at the end for comparability.

The final report is evaluated in three separate layers:

1. **Routing coverage:** eligible / typed / ambiguous / untyped / ineligible, and the share of genuine personal-knowledge questions the selective path could actually claim.
2. **Retrieval and groundedness:** false-supported claims, unsupported and absence behaviour, restricted-record leakage, citation and source correctness.
3. **Practical value:** how many real questions selective answering would improve over the generic path, how many would fall through unchanged, and whether protection against unsupported personal claims justifies the coverage limitation.

"No false-supported claims" alone is not sufficient for promotion if coverage remains extremely low. End states: **PROMOTE** (useful coverage and clean groundedness), **NARROW** (strong safety, only some question classes route reliably), **DO NOT PROMOTE** (live coverage too low to give meaningful value).

## 4b. Boundary: Phase 49 deployment (2026-10-11)

Owner-approved boundary option. Core was stopped gracefully at 06:34:54 UTC (`docker stop -t 30`, exit 0) so the telemetry flushed, and the new core (image `cbf13868a429`, commit `3e17ad3`) started at 06:38:44 UTC with the same flags (`KNOWLEDGE_INDEXING/RETRIEVAL/SELECTIVE_SHADOW=true`, selective answering absent) and no change to the router, registry, retrieval, evidence rules or answerer (unchanged since `9c8214a`; the dev8/10/12/14 freeze tests pass).

* **Cohort A (to 06:34:54 UTC):** the suppressed report (`--min-cell 5`) of the telemetry file read after the stop: funnel `attempted 6, admitted 6, processed_ok 6`, modality text 6, latency `<=5 ms` 6, 12 cells suppressed (the file is cumulative since the window opened, so it includes the two 48F verification probes of 2026-10-10 14:57; the in-memory capture counters of the last process are `attempted 4`). File copy preserved: `~/reachy-backups/phase48-boundary-049/selective-shadow.pre-049.jsonl` (sha256 prefix `db5f9bf741c2d6cf`, 0600).
* **Cohort B (from 06:38:44 UTC):** the same file keeps being appended. Subtract the cohort-A copy; additionally subtract my 20 deployment probes (06:39:23 to 06:39:45 UTC, channel `probe-049`: 6 API probes and the 14-request 44H matrix, text and voice), which may appear in the first cohort-B hourly flush.
* **What changed for cohort B:** the answer path for a turn that names a note or meeting (the grounding fix `14403a1`) and, with its flag off, nothing from Phase 49. The shadow's classification of the same text is unchanged. Do not merge A and B as one uninterrupted window; report them separately and say so.

[Deployment record](phase-49-deployment-2026-10-11.md).

**Boundary 2 (2026-10-11 07:27 UTC, Phase 49 activation, same image, flags otherwise unchanged).** Graceful stop at 07:27:04 flushed the telemetry: cumulative `admitted 26, processed_ok 26`, i.e. cohort A's 6 plus exactly my 20 deployment probes, so **cohort B (06:38:44 to 07:27:04) contains no owner usage** (copy `~/reachy-backups/phase48-boundary-049/selective-shadow.cohortB-end.jsonl`, sha256 prefix `d8676998c7b1f5cd`). Cohort C starts at 07:27:07; subtract its 3 probes. With `NOTEPAD_PROCESSING_ENABLED` on, a "what are my tasks" style question is answered by the Phase 49 inquiry (confirmed / pending / unprocessed), which changes the production answer path for those turns; the shadow classifier is unchanged. [Activation record](phase-49-activation-2026-10-11.md).

**Boundary 3 (2026-10-11 10:08 UTC, Brain provenance deployment, core-only, flags unchanged).** Graceful stop at 10:08:47 flushed the telemetry: cumulative `admitted 32, processed_ok 32` = cohort A 6 + cohort B's 20 probes + cohort C's 6 probes, so **cohort C (07:27:07 to 10:08:47) contains no owner usage** (copy `~/reachy-backups/phase48-boundary-049/selective-shadow.cohortC-end.jsonl`, sha256 prefix `77d160f8c4c3ef44`). Cohort D starts at 10:08:51 (image `1c3290c4d993`); subtract its 5 verification probes. No router, registry, retrieval, evidence-rule or answerer change. [Record](phase-49-brain-provenance-deployment-2026-10-11.md).

## 5. End-of-window procedure

1. Close when the owner calls it: 100 to 200 genuine knowledge-like turns (the shadow's `admitted` count) or 7 to 14 days, whichever gives enough representative evidence first.
2. Read the telemetry via the suppressed report (`--min-cell 5`, and `--by day` for the trend), and read it **before any core restart** where possible; counters flush every 5 minutes and at stop, so at most five minutes of counts can be missing after a hard failure.
3. Repeat the offline probe on the same frozen question file; compare its categories with the start.
4. Record latency/resource impact (chat p95, swap in/out, restarts, core memory and CPU).
5. Write the report with the categories the owner listed and the recommendation; promotion evidence is the safety set (0 restricted exposure, 0 selective-path safety failures, very low false-supported rate, correct abstention on unsupported facts, resolvable citations, acceptable latency, routing coverage sufficient for the owner's real question forms), not a single accuracy percentage. High abstention with near-zero unsupported claims is acceptable for a first rollout.
