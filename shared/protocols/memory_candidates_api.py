"""Memory-candidate review routes (Phase 44F). companion-core serves them behind its service token; the hub proxies them for the owner session only
(owner cookie plus CSRF for every change; no bearer-token path). `PRIVACY_STATE` is the small authenticated hub read companion-core uses to learn
whether privacy mode is on before it may propose a candidate."""

MEMORY_CANDIDATES = "/memory-candidates"
MEMORY_CANDIDATE_ACCEPT = "/memory-candidates/{candidate_id}/accept"
MEMORY_CANDIDATE_REJECT = "/memory-candidates/{candidate_id}/reject"
MEMORY_CANDIDATES_FORGET_CONVERSATION = "/memory-candidates/forget-conversation"
MEMORY_CANDIDATES_CAPTURE_COUNTERS = "/memory-candidates/capture-counters"  # Phase 48B instrumentation: read-only aggregate counters, core only (no hub proxy)
PRIVACY_STATE = "/privacy/state"
