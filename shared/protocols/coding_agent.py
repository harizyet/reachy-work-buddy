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
SESSION_EVENTS = "/sessions/{session_id}/events"
SESSION_USAGE = "/sessions/{session_id}/usage"

PROVIDER_CAPABILITIES = "/providers/{provider}/capabilities"
