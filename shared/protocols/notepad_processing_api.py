"""Notepad processing routes (Phase 49, docs/phase-49.md). companion-core serves them behind its service token only when NOTEPAD_PROCESSING_ENABLED is true (404 otherwise); the hub
proxies them for the OWNER SESSION only (cookie plus CSRF for every change, no bearer-token path) under the same paths."""

NOTEPAD_PROCESSING_CONFIG = "/notepad-processing/config"
NOTE_PROCESSING = "/notes/{note_id}/processing"  # GET: state, job and proposals of one note. POST: enqueue a job for the note's current text
NOTE_MEETING_LINKS = "/notes/{note_id}/meeting-links"  # GET: suggested and confirmed links (refreshes time-overlap suggestions)
NOTE_MEETING_LINK = "/notes/{note_id}/meeting-links/{meeting_id}"  # PUT {state: confirmed|rejected}: link, confirm, reject or unlink
NOTEPAD_JOB_RETRY = "/notepad-processing/jobs/{job_id}/retry"
NOTEPAD_PROPOSALS = "/notepad-proposals"  # GET: every proposal awaiting a decision
NOTEPAD_PROPOSAL_ACCEPT = "/notepad-proposals/{proposal_id}/accept"
NOTEPAD_PROPOSAL_DISMISS = "/notepad-proposals/{proposal_id}/dismiss"
