# Operator UI

Plain HTML/JS/CSS, served by reachy-hub at `/ui/` or through Caddy at
`/hub/ui/`. Login, component status, LLM usage/settings, session mode/DND,
audit activity, and queued notifications. No build step or external assets.

See [deployment setup](../../deploy/homelab/README.md#operator-dashboard-phase-19)
and [ADR 0016](../../docs/adr/0016-operator-ui.md) for configuration and API
semantics. The UI works at both direct and proxy paths. It refreshes health
and usage every 10 seconds without overwriting edited form values.

Phase 20's web chat and Phase 21's hybrid routing are intentionally absent.
