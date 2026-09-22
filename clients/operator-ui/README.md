# Operator UI

Plain HTML/JS/CSS, served by reachy-hub at `/ui/` or through Caddy at
`/hub/ui/`. Login, component status, LLM usage/settings, session mode/DND,
audit activity, and queued notifications. No build step or external assets.

See [deployment setup](../../deploy/homelab/README.md#operator-dashboard-phase-19)
and [ADR 0016](../../docs/adr/0016-operator-ui.md) for configuration and API
semantics. The UI works at both direct and proxy paths. It refreshes health
and usage every 10 seconds without overwriting edited form values.

Phase 20's web chat and Phase 21's hybrid routing are intentionally absent.

Workflow: log in with the bootstrapped owner, load the conversational user
ID (not necessarily the login username), then save mode/DND or model
settings. That user must already have a session from Telegram or another
channel. A blank key field preserves the stored key; “Remove saved key”
clears it; “Disable model” restores core's unconfigured reply behavior.
Changes take effect on the next conversation turn without restarting.

The page shell is public, but dashboard data and controls require login.
No password/key is stored in localStorage. All cookie mutations include
the CSRF header. Telepresence shares the same cookie; the dashboard does
not itself provide Phase 20's web chat. Telegram shows configuration only,
and model utilization shows API calls/tokens/latency rather than hardware
load. On core outage, its status and usage become unavailable while the
remaining component probes stay visible.

Verified during Phase 19 in Chromium at desktop and 390px mobile widths,
including a real OVMS completion, settings persistence, logout, and a core
outage. Python API tests live in `services/reachy-hub/tests/test_operator.py`;
there is no committed frontend test runner or build dependency.
