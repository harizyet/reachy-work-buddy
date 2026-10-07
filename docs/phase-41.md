# Phase 41: Meeting speaker names and reviewed corrections

Status: **started 2026-10-07.** Decision: [ADR 0030](adr/0030-meeting-speaker-names-and-reviewed-corrections.md). Extends [Phase 27](phase-27.md) meetings; first client is the [Android app](phase-40.md).

## Stages

| Stage | Work | State | Gate |
|---|---|---|---|
| 41.0 Documents | Roadmap row, this page, ADR 0030 | **Done 2026-10-07** | Owner can redirect scope |
| 41.1 Core | Migration 019, `speaker_names` and `transcript_corrections`, store methods (in-memory and Postgres), `PUT /meetings/{id}/speakers`, `POST .../corrections/suggest`, `PUT/DELETE .../corrections/{n}`, `POST .../corrections/replace` (change all) | **Done 2026-10-07** (`test_meeting_annotations.py`; Postgres durability test passes against a disposable pgvector container) | Store parity, validation and verification tests |
| 41.2 Hub proxies | Owner-authenticated proxies and route constants; longer timeout for suggestions | **Done 2026-10-07** (`test_operator.py`) | Auth and core-error pass-through |
| 41.3 Android | Speaker labels in the transcript, tap to name, Suggest corrections (asks local or cloud model each time) grouped into one "Change all N" card per mistake, a Replace (find and replace) dialog, tap a segment to edit or restore | **Done 2026-10-07**; verified in an emulator against a throwaway hub with a stubbed local model | Real model and real recording |
| 41.6 Key terms | Global glossary (`/meeting-terms`), per-meeting terms, attendees and speaker names as vocabulary; candidate generation (spelling plus phonetic) and a model that only chooses; spelling variants accepted without a model; confidence and source on each suggestion; migration 020; app screens | **Done 2026-10-07**; real-Postgres tests pass; emulator-checked with a stub model | Permanent regression case "germanite to Gemini" (`test_meeting_annotations.py`) |
| 41.7 Model benchmark | 23-case harness; compare the 7B, Qwen3-14B, Gemma-3-12B and Gemma-4-12B; keep the production 7B | **Done 2026-10-07**, see [the record](verification/meeting-corrections-benchmark-2026-10-07.md); no production model change | Add real ASR mistakes over time (1 real case so far) |
| 41.4 Web panel | Show names and corrections in the Meetings tab | **Not started** | n/a |
| 41.5 Acceptance | Deploy migration 019, run suggestions with the real local model on a real recording | **Pending (owner)** | Owner |

## Known limits

With key terms the 7B scores 0.89 F1 on the benchmark but still misses the real "germanite" case; Qwen3-14B-AWQ and (batched) Gemma-4-12B find it. Whether to move the production model is undecided and needs a chat-quality check this benchmark does not provide.


Measured 2026-10-07 on a real recording with "Gemini" heard as "germanite": the local Qwen2.5-7B returned no suggestions at any chunk size (400 to 6000 characters) or prompt variant tried, so its misses are a knowledge limit, not a size or time limit. The cloud model (GLM-5.3 on Together AI, a reasoning model) found it, but one whole-transcript request timed out, so cloud runs use ~800-character chunks, five at a time, with a 90 s per-chunk timeout and a 200 s overall deadline; a run can be partial (the app says so) and varies between runs. A per-meeting list of key terms matched against model-flagged words is the likely next step for local.

Suggestion quality depends on the local model (not yet judged on a real recording). Speaker names apply per meeting; there is no cross-meeting voice identity.
