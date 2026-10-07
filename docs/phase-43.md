# Phase 43: Meeting deletion, summaries, minutes and meeting context

Status: **built and deployed 2026-10-07.** Decision: [ADR 0032](adr/0032-meeting-outputs-and-context.md). Builds on [Phase 41](phase-41.md) (corrections), [Phase 42](phase-42.md) (deep local) and the web search of [Phase 24a](phase-24a.md).

## What exists

| Capability | Where | Notes |
|---|---|---|
| Delete a meeting and its recording; bulk "delete failed and cancelled"; Cancel for in-progress ones | Android Meetings list and detail menu; web Meetings list and detail | Confirmation first; 409 while processing or while a deep job runs on it |
| Summary and minutes (local by default), shown with the tier that wrote them | Meeting detail: Summary, Minutes, Transcript | Written in parts for long meetings |
| Rerun on Deep local or Cloud | Same screen ("Rerun with another model") | Deep local warns that Reachy is unavailable, shows the banner, notifies, and sends the Telegram notices of Phase 42C ("deep summary", "deep minutes") |
| Use as context | Meeting detail, then Talk (Android) or Chat (web) with a context chip | Answers from the meeting with the local model; "Ask the cloud model" / "Use frontier model" sends the meeting text to the provider for that message only |
| Web search for outside facts | Automatic when a meeting is attached | Questions about the world search; questions about what was said do not; only the question text is sent |
| Clickable citations | Android Talk, web Chat | `[S1]` links and a visible Sources list |

API (core, hub proxies the same): `DELETE /meetings/{id}`, `POST/DELETE /meetings/{id}/outputs/{summary|minutes}`, `POST /meetings/{id}/outputs/{kind}/deep`, `context_meeting_id` on chat turns. See [services reference](reference/services.md). Migration 021 (`summary`, `minutes`).

## Verification (2026-10-07)

- Core, hub, Postgres, Android (31 JVM tests) and browser tests pass; the Android flows were run in an emulator against a throwaway hub.
- Real stack: deleting a throwaway upload removed the record and its recording from disk; summary and minutes of the real recording took 3 to 4 s on the local 7B; context questions came back labelled work-private from the local model; "Is Codex free?" ran a real web search (5 results from OpenAI's pages) and was answered from them, while "What did the speaker say about taste?" stayed on the meeting and the bare "Is it free?" did not search.
- Not run on the real stack: a deep summary or minutes (the job runner is the one verified in Phase 42C and these tasks are covered by unit and emulator tests), and the browser UI against the production hub (no owner session in development).

## Known limits

The 7B reproduces the transcript's mis-hearings in summaries and minutes (rerun on a higher tier, or fix the transcript first), does not know recent products without a search, and often omits `[S1]` markers (the Sources list is always shown). Retrieval for long meetings is keyword overlap, not embeddings. Jobs are held in memory (see Phase 42C).
