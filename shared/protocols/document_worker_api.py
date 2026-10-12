"""Document worker routes (Phase 50A, ADR 0034). The worker is Reachy's only interface to the document backend.

Resources are addressed by Reachy's own document id, never by a backend identity: two Reachy documents with the same bytes
share one backend object but keep separate policy, so a route that took the backend reference could not tell them apart.
"""

WORKER_HEALTH = "/health"
WORKER_DOCUMENTS = "/documents"
WORKER_DOCUMENT = "/documents/{document_id}"
WORKER_STATUS = "/documents/{document_id}/status"
WORKER_PARSE = "/documents/{document_id}/parse"
WORKER_READ = "/documents/{document_id}/read"
WORKER_LOCATOR = "/documents/{document_id}/locator"
WORKER_SEARCH = "/documents/{document_id}/search"

# Extraction inspector (reuses MinerU's own page images, structured result and renderers; nothing here carries a path or a backend locator)
WORKER_INSPECT_PAGE = "/documents/{document_id}/inspect/pages/{page}"
WORKER_INSPECT_IMAGE = "/documents/{document_id}/inspect/pages/{page}/image"
WORKER_INSPECT_BLOCK_IMAGE = "/documents/{document_id}/inspect/pages/{page}/blocks/{block}/image"
WORKER_EXPORT = "/documents/{document_id}/export"
