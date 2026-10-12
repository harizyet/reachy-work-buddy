"""Meeting analysis routes (Phase 31, docs/phase-31.md). companion-core serves them behind its service token only when MEETING_ANALYSIS_ENABLED is true (404 otherwise); the hub
proxies them for the OWNER SESSION only (cookie plus CSRF for every change, no bearer-token path) under the same paths."""

MEETING_ANALYSIS_CONFIG = "/meeting-analysis/config"
MEETING_ANALYSIS = "/meetings/{meeting_id}/analysis"  # GET: state, run and items of one meeting. POST: enqueue an analysis of its current transcript
MEETING_ANALYSIS_RETRY = "/meeting-analysis/runs/{run_id}/retry"
MEETING_ANALYSIS_ITEMS = "/meeting-analysis/items"  # GET: every action candidate awaiting a decision
MEETING_ANALYSIS_ACCEPT = "/meeting-analysis/items/{item_id}/accept"  # POST {text?}: confirm an action as a task
MEETING_ANALYSIS_DISMISS = "/meeting-analysis/items/{item_id}/dismiss"
MEETING_ANALYSIS_PROVENANCE = "/meeting-analysis/provenance/{record_id}"  # GET: the meeting, segments and quotes a task was made from
