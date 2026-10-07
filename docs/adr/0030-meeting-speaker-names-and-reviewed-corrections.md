# ADR 0030: Meeting speaker names and reviewed transcript corrections

- Status: **Accepted 2026-10-07** for [Phase 41](../phase-41.md).
- Date: 2026-10-07

## Context

Meeting transcripts carry raw speaker labels (`SPEAKER_00`) and the speech model mishears names and terms (in a real recording, "Gemini" came out as "Germanite"). The owner wants to name speakers and to have the language model suggest fixes from the meeting's context.

## Decision

1. **Raw evidence is never rewritten.** `transcript_segments` and `diarization_segments` stay exactly as the speech services produced them. Owner names live in `speaker_names` (label to display name) and accepted fixes in `transcript_corrections` (segment index to replacement text). Clients overlay them when displaying.
2. **The model suggests, the owner decides.** `POST /meetings/{id}/corrections/suggest` returns word-level suggestions and stores nothing. A correction exists only after the owner applies it with `PUT /meetings/{id}/corrections/{n}` (or edits a segment by hand through the same route); `DELETE` restores the original. `POST /meetings/{id}/corrections/replace` is the owner-initiated "change all": it rewrites every whole-word, case-insensitive match of one phrase across the transcript as corrections (the model is not involved), so a mistake that repeats is fixed everywhere, not only where the model flagged it. The LLM has no authority to change a transcript.
3. **Suggestions are verified.** Each suggestion must name an existing segment and quote text that is really in it; anything else is dropped. The prompt tells the model the transcript is data, not instructions.
4. **Meeting speech stays local unless the owner chooses otherwise, per request.** `suggest` takes `model: "local" | "cloud"`, defaulting to local, and the app asks which to use every time. Routing settings never send meeting text to the cloud on their own, and a choice that is not configured returns 409 instead of falling back to the other model (ADR 0018, privacy). Choosing cloud is the owner knowingly sending that transcript text to the cloud provider.
5. **Same trust boundary.** Core exposes the routes; the hub proxies them behind the owner-cookie/CSRF or bearer check. No new service and no sibling imports.

6. **Key terms, resolved by candidates (2026-10-07).** Measured on a real recording: the 7B local model never turned "germanite" into "Gemini" on its own, at any chunk size, so suggestions no longer rely on the model knowing the answer. The owner supplies vocabulary at three levels: a global glossary (`/meeting-terms`), per-meeting key terms (`PUT /meetings/{id}/terms`), and automatically the meeting's participants and named speakers. The server finds spans of one to three words that look or sound like a term (spelling similarity plus a light phonetic key), then a model only chooses among those candidates or says none. A span with the same letters as a term ("anti-gravity", "click house") is accepted without a model. Suggestions are labelled high confidence (same letters as a term, no model), matches your term (a model judged it fits; small models get this wrong, so it is not "high"), or model guess (the free-form scan, which still runs and can surface things the vocabulary cannot). Nothing is applied without the owner.

## Consequences

- Migration 019 adds two JSONB columns to `meetings`; additive.
- Quality depends on the local model; a weak model produces few or poor suggestions, which the owner can dismiss.
- Long meetings are checked in up to six windows; the rest is reported as not checked.
- Only the Android app uses the new routes so far; the web control panel does not show names or corrections yet.
