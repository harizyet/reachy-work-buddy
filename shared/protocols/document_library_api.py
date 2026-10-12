"""Document library routes (Phase 50B, docs/phase-50.md). companion-core serves them behind its service token only when DOCUMENT_LIBRARY_ENABLED is true (404 otherwise).

They live under /document-library because /documents is the older text-RAG ingest (Phase 5), which this phase does not touch.
"""

DOCUMENT_LIBRARY_CONFIG = "/document-library/config"
DOCUMENT_LIBRARY_DOCUMENTS = "/document-library/documents"  # GET: the catalogue. POST (multipart): upload an original
DOCUMENT_LIBRARY_DOCUMENT = "/document-library/documents/{document_id}"  # GET: detail. PATCH: title, project scope, sensitivity, priority. DELETE: remove the document everywhere
DOCUMENT_LIBRARY_REPROCESS = "/document-library/documents/{document_id}/reprocess"  # POST {tier?}: parse the retained original again
DOCUMENT_LIBRARY_READ = "/document-library/documents/{document_id}/read"  # GET: bounded read of the parsed text (page_range, after, limit)
DOCUMENT_LIBRARY_LOCATOR = "/document-library/documents/{document_id}/locator"  # GET: read around a locator of this document
DOCUMENT_LIBRARY_SEARCH = "/document-library/documents/{document_id}/search"  # POST {query, limit}: search inside this one document

# The trusted access ceiling for a request that reads document CONTENT (read, locator, search). Only the hub may set it, from the authenticated channel and its trust policy:
# owner web or Android session -> "sensitive"; owner Telegram -> its existing trusted-owner ceiling; robot voice, a shared speaker or uncertain identity -> a lower one. Core is
# reachable only with the service token, so the header cannot come from a browser or from document text. Absent means "work-private" (the conservative default); an unknown value is refused.
ACCESS_CEILING_HEADER = "X-Reachy-Access-Ceiling"
DOCUMENT_LIBRARY_SUMMARIES = "/document-library/documents/{document_id}/summaries"  # GET: summaries of this document (newest first). POST {style, force?}: start one (ordinary, executive, technical)
DOCUMENT_LIBRARY_INSPECT = "/document-library/documents/{document_id}/inspect/pages/{page}"  # GET: one page as MinerU extracted it (blocks, markdown, html)
DOCUMENT_LIBRARY_INSPECT_IMAGE = "/document-library/documents/{document_id}/inspect/pages/{page}/image"  # GET: MinerU's rendering of the original page (PDF and images)
DOCUMENT_LIBRARY_INSPECT_BLOCK_IMAGE = "/document-library/documents/{document_id}/inspect/pages/{page}/blocks/{block}/image"  # GET: the crop of one block (a figure, a table)
DOCUMENT_LIBRARY_EXPORT = "/document-library/documents/{document_id}/export"  # GET ?format=markdown|html|content_list|middle_json: a download of what MinerU extracted
DOCUMENT_LIBRARY_ORIGINAL = "/document-library/documents/{document_id}/original"  # GET: the stored original, integrity-checked, as an attachment
