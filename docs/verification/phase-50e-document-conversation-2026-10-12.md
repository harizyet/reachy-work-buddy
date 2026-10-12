# Phase 50E: document-scoped conversation (2026-10-12)

Local development while the MS-01 deployment gate waits for the owner's approval ([sequence](../phase-50.md#0-revised-execution-sequence-owner-decision-2026-10-12)). **Nothing deployed; flag-gated behind `DOCUMENT_LIBRARY_ENABLED` and a worker; no client sends `context_document_id` yet (50J).**

## Behaviour

Described in [services reference](../reference/services.md#document-library-phase-50b-50c): `context_document_id` on `/conversation`, deterministic evidence selection (search inside the document, pages read from the worker, whole text if at most three pages), fixed replies when the document is missing, deleting, unprocessed, not permitted or has no relevant passage (model not called), local-only generation, `citations` from the supplied pages, reply privacy at least the document's class, a `sensitive` document never sent to the frontier model, and the hub-set ceiling (typed owner web/Android messages `sensitive`; voice capped at public by core; Telegram unchanged).

## Verification (in-process, scripted model, real worker app over ASGI with a fake engine)

* `test_document_library.py` (42 tests including 8 for 50E): answer from the right excerpt only with citations from supplied pages; fixed reply and no model call when the document does not cover the question; whole short document supplied; not-found, not-ready, over-ceiling and shared-speaker documents get fixed replies with no model call and no worker content call; the trusted ceiling lets a sensitive document be used and the reply keeps its class, and the frontier is refused for it; document text containing instructions is supplied as quoted data and an action request ("delete all my tasks") is handled by the action gate before the document or the model; no document means the conversation is unchanged.
* Hub: `test_the_hub_sets_the_document_ceiling_from_the_authenticated_channel_only` (typed web with enforced authentication sets it; voice, Telegram, an unauthenticated hub and any body field do not).

## Not done / limits

No real-LLM quality run (the model here is scripted; answer quality over real MinerU text is for the owner-facing acceptance after the gate); search is MinerU's lexical document search, so a purely semantic question about a long document may find nothing (the reply then says so rather than guessing; 50F/50H address broader retrieval and summaries); no UI to attach a document (50J).
