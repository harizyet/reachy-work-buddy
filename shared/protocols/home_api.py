"""Home dashboard routes (docs/phase-51.md, extends ADR 0015). companion-core serves them behind its service token; the hub proxies them for the OWNER SESSION only under the same
paths (cookie plus CSRF for the POST, no bearer-token path). Both are read-only: nothing here creates, accepts or changes a record."""

HOME = "/home"  # GET ?sections=schedule,tasks,...: the structured snapshot, or only the named sections (a section refreshes on its own)
HOME_BRIEF = "/home/brief"  # POST {narrative?}: "Brief me on today" - deterministic lines, plus an optional local-model rewording of exactly those lines

SECTIONS = ("schedule", "tasks", "reminders", "reviews", "weather")
