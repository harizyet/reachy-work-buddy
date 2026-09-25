# Agent instructions

**Before starting work, read [HANDOVER.md](HANDOVER.md).** It contains current
scope, open acceptance, and machine-specific cautions. Update it before ending
the session; keep durable procedures in their canonical documentation instead
of adding another chronological implementation log.

## Required references

[docs/README.md](docs/README.md) defines where each kind of information belongs.
Read the relevant guide before changing its area:

- [Development and testing](docs/development.md): workspace, pytest/in-process
  integration conventions, dependency/index routing, Docker, and verification.
- [Deployment](docs/deployment.md): profiles, credentials, database upgrades,
  robot supervision, and isolated test-stack cleanup.
- [Service reference](docs/reference/services.md): implementation/API map.
- [Roadmap](docs/plan.md#6-implementation-roadmap): phase scope and exit criteria.
- [ADRs](docs/README.md#architecture-decisions): binding boundaries. Read the
  relevant decisions before structural changes; do not reinterpret ownership
  case by case. User-authorized scope takes precedence over stale prose.

## Engineering boundaries

Services communicate over HTTP/defined network protocols, never sibling-service
runtime imports. Shared models belong in `shared/models`, route constants in
`shared/protocols`; import those rather than hardcoding shared paths. Sibling
imports are allowed only in tests for actual ASGITransport integration chains.

Keep core reasoning/consent separate from hub sessions/channels/auth and
embodiment presence/hardware. Preserve deterministic intent/consent precedence,
text-only destructive confirmation, and private-response routing. The LLM has
no authority to bypass an action gate. Consult ADRs 0001, 0006, 0011, and 0018.

Keep browser paths relative for direct/proxied mounts, render conversation text
literally, and preserve owner-cookie/CSRF plus bearer access. Do not add keys or
transcripts to localStorage. A browser login does not authenticate every legacy
API endpoint; preserve and describe the actual trusted-network boundary.

Do not add speculative endpoints or later-phase functionality while working on
a current phase. Prefer established patterns and small concrete changes over
premature abstractions. Comments should explain constraints or non-obvious
ordering. `/gaze` and `/pose` remain reserved, not invitations to implement them.

## Verification and safety

Follow the [test conventions](docs/development.md#testing-conventions), including
importlib mode, no test-directory `__init__.py`, injected stores, controlled-time
loop tests, and isolated service dependency checks. Ruff must pass for code
changes. Match verification to the change; documentation-only edits require
link/anchor and factual consistency checks, not robot or model activity.

Before claiming a feature works end to end, exercise the real process, image,
database, or API needed for that claim. Label mocks, simulator checks, and live
physical acceptance separately. Historical test counts are not current health.
When tests and a live run disagree, investigate the live failure.

Use a separate named Compose project for disposable checks; never delete user
volumes or stop unrelated services as routine cleanup. Preserve database data
when upgrading schemas. Keep credentials in permission-restricted gitignored
files, never chat/log output; confirm ignore rules. See the
[deployment rules](docs/deployment.md#upgrades-and-verification-cleanup).

Starting the real daemon can move the robot. In any dev/test context — a
Claude Code session manually running the launchers, an unaccepted/in-progress
deployment, or any host not explicitly designated production per the
deployment guide — do not start the daemon without the owner present and
supervising. Keep launcher `--check` read-only. Host-specific launcher
changes need target-platform verification; syntax checks alone missed real
systemd, shell, and networking failures.

For a designated production Nano (owner's explicit, accepted-risk decision,
2026-09-23 — see [deployment](docs/deployment.md#robot-host-and-jetson-nano)),
`reachy-mini-daemon` may be systemd-enabled for unattended boot start,
including its own wake-up motion, without a human physically watching every
boot. This is a deliberate exception to the rule above for that one
designated host, not a relaxation of it generally — a session working on
launcher/daemon-start code, or operating any other host, still follows the
owner-present rule for daemon start.

Named-behaviour playback (`POST /behaviour/{name}`, the bounded, mapped,
pre-recorded moves in `_DEFAULT_BEHAVIOUR_MOVES`) does not require the
owner physically watching each call — owner's explicit decision,
2026-09-23: the robot is small with no meaningful risk to bystanders, and
this class of motion is bounded and pre-recorded, not arbitrary. This
does **not** extend to: starting/restarting the daemon itself (still
needs the owner present, above — its own wake-up/go-to-home routine is
unbounded first motion after however long the robot was last positioned);
raw/diagnostic joint commands (`POST /api/move/goto` or any other
non-behaviour move) used to investigate a problem; or any new/expanded
behaviour not already in the mapped, tested set. Those still need the
owner present per the rule above.

Remote standby/resume (`POST /robots/standby`, `POST /robots/resume` on
reachy-hub; triggered only via the explicit `/reachy standby`/`/reachy wake`
command — or a registered channel alias — parsed by
`companion_core.commands.parser`, per Phase 24b; free-form phrase matching
was retired, not repurposed, see docs/phase-24b.md) is a further, narrower
exception the owner explicitly approved, 2026-09-23, alongside the two
above: resume replays the real daemon's wake-up motion (same class of
motion the production-boot exception above already covers unattended),
triggered from an owner-authenticated conversational channel instead of a
boot event. It does not require the owner physically present, on the same
designated production host as the boot-start exception. This is still not
a general relaxation — it's gated by `require_remote_auth`'s
owner-bound credential, exactly like every other remote-control route,
and it only exists for this one narrow phrase-triggered path.

Automatic daemon restart on error (`reachy-daemon-recovery.service`,
`deploy/reachy/daemon-error-recovery.sh`) is a further exception the owner
explicitly approved, 2026-09-25, during 24d, after the daemon's boot
wake-up failed and left it in `state: error`. On the same designated
production Nano only, when the daemon reports `state == "error"`, it may
be restarted unattended, replaying its wake-up motion, **at most once per
boot**. If it errors again in the same boot, the recovery stops, logs a
`crit` alert and leaves the daemon for the owner, with no loop. It is
not a general relaxation: any other trigger, a higher restart count, or
any corrective move still needs the owner present, per the rules above.

## Documentation maintenance

Use the ownership table in [docs/README.md](docs/README.md#where-information-belongs).
Update the canonical page and link to it elsewhere. Directory READMEs are short
entry points; HANDOVER is a current snapshot; ADRs capture decisions; verification
records capture dated evidence. Do not copy feature history into each of them.
Check relative links and heading anchors whenever files move or headings change.
