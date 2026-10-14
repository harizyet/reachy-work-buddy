"""Multimodal meeting intelligence routes (Phase 53, docs/phase-53.md). companion-core serves them behind its service token only when MEETING_MULTIMODAL_ENABLED is true (and the document
library is on); otherwise they do not exist (404). The hub proxies them for the OWNER SESSION only (cookie plus CSRF for every change, no bearer-token path) under the same paths and sets
the trusted access ceiling (`X-Reachy-Access-Ceiling`, see document_library_api) itself; nothing in a request can raise it.

A `window_key` is "<first segment index>-<last segment index>" of one discussion window of the transcript."""

MEETING_MULTIMODAL_CONFIG = "/meeting-multimodal/config"
MEETING_MULTIMODAL = "/meetings/{meeting_id}/multimodal"  # GET: attached documents, alignment and analysis state, the transcript windows with their slide suggestions
MEETING_MULTIMODAL_DOCUMENTS = "/meetings/{meeting_id}/multimodal/documents"  # POST {document_id}: attach an existing document (idempotent)
MEETING_MULTIMODAL_DOCUMENT = "/meetings/{meeting_id}/multimodal/documents/{document_id}"  # DELETE: detach; the document itself is untouched
MEETING_MULTIMODAL_ALIGN = "/meetings/{meeting_id}/multimodal/alignment"  # POST {force?}: estimate which page was discussed in each part of the transcript
MEETING_MULTIMODAL_ANALYSE = "/meetings/{meeting_id}/multimodal/analysis"  # POST {force?}: combined analysis of the transcript and the attached documents
MEETING_MULTIMODAL_REVIEW = "/meetings/{meeting_id}/multimodal/windows/{window_key}/review"  # PUT {decision, document_id?, page?}: the owner's decision. DELETE: withdraw it
MEETING_MULTIMODAL_ASK = "/meetings/{meeting_id}/multimodal/ask"  # POST {question}: a question answered from this meeting and its attached documents, with separate citations
MEETING_MULTIMODAL_RETRY = "/meeting-multimodal/runs/{run_id}/retry"
MEETING_MULTIMODAL_ACCEPT = "/meeting-multimodal/items/{item_id}/accept"  # POST {text?}: confirm an action as a task
MEETING_MULTIMODAL_DISMISS = "/meeting-multimodal/items/{item_id}/dismiss"
