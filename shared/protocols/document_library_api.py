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
