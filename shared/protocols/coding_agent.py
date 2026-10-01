"""coding-agent-service routes (Phase 29, docs/phase-29.md). Separate
service-to-service credential from accounts' SERVICE_HEADER per 29.19
("separate ... from Reachy application credentials") — a leaked
coding-agent token should not also authenticate account data calls.
"""

SERVICE_HEADER = "X-Reachy-Coding-Agent-Service-Token"

PROJECTS = "/projects"
PROJECT = "/projects/{project_id}"

SESSIONS = "/sessions"
SESSION = "/sessions/{session_id}"
SESSION_RESUME = "/sessions/{session_id}/resume"
SESSION_INPUT = "/sessions/{session_id}/input"
SESSION_STOP = "/sessions/{session_id}/stop"
# 29.3: re-checks a non-terminal session against its provider/container
# right now, rather than waiting for a future 29.4 hook event or a 29.14
# background poller — neither exists yet.
SESSION_REFRESH = "/sessions/{session_id}/refresh"
SESSION_EVENTS = "/sessions/{session_id}/events"
SESSION_USAGE = "/sessions/{session_id}/usage"

# Read-only listing of Claude Code sessions run outside Reachy, found in a
# mounted copy of the host's ~/.claude/projects history.
TERMINAL_SESSIONS = "/terminal-sessions"

PROVIDER_CAPABILITIES = "/providers/{provider}/capabilities"
# 29.26: account allowance windows last reported by that provider's CLI
# through a managed session (not a live quota query).
PROVIDER_ALLOWANCE = "/providers/{provider}/allowance"

# 29.19: owner-entered provider credentials (e.g. a Claude Code API key).
# Reachy-hub proxies these under owner cookie+CSRF auth; this service only
# ever sees the shared-secret service token, never an owner session.
PROVIDER_CREDENTIALS = "/providers/credentials"
PROVIDER_CREDENTIAL = "/providers/{provider}/credential"
