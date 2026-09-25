# Portal search and animation controls — 2026-09-25

The owner requested redeployment and testing, then limited the run to the
web portal because Reachy was powered off. No Nano deployment, daemon
start or physical animation was performed.

## Deployment

The existing `reachy-homelab` project was rebuilt at 14:32 UTC with
`scripts/start-homelab.sh --build --no-browser`, using its existing private
environment and Compose override. Source was `9b84d93` plus the working-tree
portal animation-settings change. Both hub and core HTTP health checks
passed. The migration job succeeded; schema remains `008_assistant_context`.

- Hub image: `sha256:3ee5c21cd8f4b169aa703dedb72ca1da4c72fcaa6c4d13462285de8bc9cda03c`.
- Core image: `sha256:ba4a3556aacd14aaf6d91073f35d50df01f0671eb73535aa20ac0e72ff88295d`.
- Pre-deploy database backup: host `~/reachy-backups/reachy-before-portal-controls-20260925.dump`, mode 0600, 42,185 bytes.

Existing database volumes, credentials, Caddy, SearXNG and unrelated OVMS
were retained. Credential files were verified gitignored and mode 0600.

## Browser evidence

Real Chromium, owner-cookie login, and the deployed Caddy `/hub/ui/` path:

- A typed latest-Python-release question returned successful turn search
  metadata with five real provider results. Expanding the Reachy icon
  showed all five entries and clickable source links.
- A subsequent “Thanks” turn returned `web_search: null`.
- Settings displayed the registered `nano-1` robot. With it powered off,
  the panel reported “Robot animation settings are unreachable” and disabled
  both toggles. Mobile width had no horizontal overflow; screenshot inspected.
- The deployed motion-settings route returned 401 without authentication
  and 403 for a cookie-authenticated PUT without CSRF.

Three local-fixture Chromium chat/animation tests also passed, covering
saving independent toggles, stale active-session rejection, unavailable
robots, logout, and direct/proxied mounts. These fixture checks are separate
from the live search and offline-state checks above. Existing in-process
motion/auth checks were already recorded in the handover before deployment.

Temporary scripts, screenshots and build log are under `/tmp/reachy-portal-*`;
they are not durable artifacts and contain no saved credentials.

## Remaining acceptance

The Nano still needs its embodiment image rebuilt with the new settings
endpoint before live toggles can work. Real conversational gesture and
speech-wobble acceptance remains open. Follow the existing supervision rules
when that run is scheduled. The UI/runtime behavior is documented in the
[operator guide](../operator-guide.md#conversational-animations).
