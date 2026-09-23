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

Starting the real daemon can move the robot. Do not start it or trigger physical
motion without the owner present and supervising. Keep launcher `--check`
read-only. Host-specific launcher changes need target-platform verification;
syntax checks alone missed real systemd, shell, and networking failures.

## Documentation maintenance

Use the ownership table in [docs/README.md](docs/README.md#where-information-belongs).
Update the canonical page and link to it elsewhere. Directory READMEs are short
entry points; HANDOVER is a current snapshot; ADRs capture decisions; verification
records capture dated evidence. Do not copy feature history into each of them.
Check relative links and heading anchors whenever files move or headings change.
