# Phases 22–23: physical deployment, acceptance testing, and Google accounts

Status: **Mixed historical implementation record and open acceptance plan.**
22a and 23 are implemented; 22b and the Google production release gates
remain open. Preserve the matrices below as acceptance requirements. Earlier
implementation sequences describe the design at the time, not work that
must be repeated or current installation instructions.

See the [phase ledger](plan.md#6-implementation-roadmap) for current status,
[project state](project-state.md) for hardware findings and outstanding
acceptance, and [deployment](deployment.md) for current procedures.
Evidence is retained in [bring-up](verification/phase-22-bring-up.md),
[first motion](verification/phase-22b-first-motion-2026-09-23.md),
[camera](verification/phase-22b-camera-2026-09-24.md) and
[Accounts](verification/phase-23-accounts-2026-09-23.md) records.

## Starting point and architecture gate

Phases 0–21 implement the application. `robot.py` now also provides
`ReachyDaemonBackend`, a real HTTP client to `reachy-mini-daemon`
(`ROBOT_BACKEND=reachy_daemon`); `deploy/reachy/` has a captured install
recipe and systemd unit, with Bash launchers under `scripts/`. Clean-image
installer validation remains outstanding. A `POST /behaviour/{name}` call has
been dispatched end-to-end against the real daemon's own `--mockup-sim`
mode; the real Nano daemon has separately passed connectivity checks. A
named behaviour command has not yet triggered a move on real Nano motors. Google connectors and OAuth account settings do not exist. Calendar
data is local Postgres; the simulation Compose profile sends email to
Mailpit, while production needs a configured SMTP relay.

Preserve ADRs 0001, 0004, 0010, 0011, 0013 and 0016–0018, with the
Phase 22a transport amendment in [ADR 0019](adr/0019-robot-initiated-hub-connectivity.md). Target placement:

| Machine | Responsibility |
|---|---|
| Homelab | Core, hub, Postgres, Caddy, inference/STT/TTS, operator web GUI, Google credentials and connectors |
| Reachy onboard computer | **Confirmed absent** for this deployment (2026-09-22 inventory) — Reachy Mini has no independent onboard Linux compute; camera/audio/motor-controller are all USB-attached to the Nano |
| Original Jetson Nano | **Confirmed the sole robot-attached machine and required embodiment host**, not an optional accelerator — see the [ADR 0004 topology amendment](adr/0004-offline-fallback.md#phase-22-topology-amendment-2026-09-22). Also serves companion-board startup/diagnostics and browser access to the hub GUI |
| Operator laptop/phone | Same authenticated web GUI, chat, call and telepresence pages |

**Physical topology resolved (2026-09-22).** ADR 0004 required embodiment to
survive a Jetson outage; physical inventory confirmed the Nano is the only
robot-side computer, so that guarantee cannot be met by running the only
embodiment process on it. Recorded as a reviewed
[ADR 0004 amendment](adr/0004-offline-fallback.md#phase-22-topology-amendment-2026-09-22):
the homelab-outage guarantee stands unchanged; the Jetson-outage guarantee is
revised to no longer apply for this topology (Jetson offline means the robot
is inert, not degraded-but-alive) rather than silently relocating or
duplicating the presence loop. One process owns hardware; do not run
competing simulated and real robot registrations.

The original Nano uses the JetPack 4 family, which is end-of-life. This repo
requires Python >=3.13 and pins CPU PyTorch/torchaudio: neither ARM64 wheel
availability nor compatibility with the board's OS/GPU stack has been proven.
Inventory and test those requirements before choosing a native service or
container; a container does not upgrade host GPU drivers. Do not promise Nano
LLM/STT acceleration as a Phase 22 requirement. See [NVIDIA support status](https://developer.nvidia.com/embedded/faq)
and [Reachy daemon/SDK deployment guidance](https://huggingface.co/docs/reachy_mini/en/SDK/quickstart).

## Phase 22a — bring-up (implemented)

### Deliverables, in implementation order

1. **Inventory and compatibility report.** Record board model/RAM, OS,
   JetPack/L4T/kernel/architecture, power supply, storage/free space, cooling,
   Reachy variant, daemon/SDK versions, USB/network attachment, camera and
   audio devices, hostnames/IPs, time sync, and available desktop/browser.
   Prove the chosen Python/runtime and locked dependencies on the actual
   embodiment host. Record the Nano's supported role and topology decision.
2. **Real hardware adapter.** Implement `RobotBackend` using the supported
   SDK/daemon behind the existing semantic API. Exercise bounded named
   behaviours, camera, speaker, microphone capture and the existing voice
   path. Add the missing physical capture wiring if required. Serialize
   hardware ownership, handle daemon loss, and make simulation explicit in
   status. Real mode must fail clearly rather than silently use simulation.
   Preload motion/model assets so offline startup needs no download.
3. **Repeatable deployment.** Add the launchers below, robot-side service
   supervision, authenticated outbound WSS registration/reconnect per ADR 0019, environment
   examples, device permissions, and a production homelab configuration that
   excludes simulated embodiment and test mail delivery. Preserve the existing
   simulation workflow as an explicit development option. Add the separate
   outbound HTTPS media transfers needed to remove existing hub-to-robot
   camera/audio HTTP dependencies; do not put media bytes on the control socket.
4. **GUI access and network verification.** Serve the existing operator UI,
   chat, call and telepresence pages from hub; expose working navigation.
   Validate direct `/ui/` and proxied `/hub/ui/` mounts. Configure HTTPS for
   browser media on LAN hosts and retain the trusted LAN/VPN boundary for
   existing unauthenticated APIs. Validate actual WebRTC media connectivity;
   successful HTTP signaling alone is insufficient. Record any required ICE
   or TURN setup for the intended VPN/remote path.
Deliverable 5, **run acceptance and fix blockers**, is Phase 22b — see
below; it is deliberately not attempted yet.

### Bash launcher contract

These scripts exist at `scripts/*.sh`. The table is their target contract;
[current deployment limits](deployment.md#robot-host-and-jetson-nano) and
[recorded verification](verification/phase-22-bring-up.md) distinguish what
is implemented/tested, including the remaining HTTP command registration:

| File | Required behaviour |
|---|---|
| `scripts/start-homelab.sh` | Validate config, select production or explicit simulation Compose configuration, start services, wait for Postgres/core/hub and GUI readiness, report real robot availability, open the operator GUI |
| `scripts/start-reachy.sh` | On the confirmed embodiment host, check daemon/device access, start supervised real embodiment, verify `sim=false`, establish authenticated outbound WSS to hub and register identity/capabilities, open/print the hub GUI URL |
| `scripts/start-jetson.sh` | On the original Nano, check the recorded compatibility baseline and network/robot reachability, start only its assigned companion services without advertising a changing LAN IP, open/print the same GUI; delegate to the Reachy launcher only if the topology decision explicitly assigns that role |
| `scripts/check-platform.sh` | Non-destructive readiness checks and a redacted diagnostic report; physical motion/audio only with an explicit test flag |

Shared interface: `--env-file PATH`, `--no-browser`, `--check`, `--help`;
homelab additionally `--project NAME` and explicit `--build`/`--simulation`.
Document the exact invocation on each host and which one-time installation
steps require administrative access. Resolve paths relative to the script,
quote arguments, use Bash strict mode, bounded waits and useful exit codes.
Do not print secrets or full interpolated Compose configuration.

Starting twice must be safe: no duplicate processes, registry records or
browser windows from supervised restarts. Preserve existing env files,
database volumes, signing/encryption keys, and unrelated containers such as
OVMS. No automatic reflash, dependency upgrade, database reset or privileged
device access. Separate first-time installation/build from routine startup.
Use only necessary devices/groups, not blanket privileged containers.

GUI startup means serving the web assets and opening their URL with the
local desktop browser when available. Over SSH/headless boot, print the
reachable URL; do not fail an otherwise healthy startup for lack of a
display. Never auto-login or put credentials in URLs. The Nano does not
host a duplicate hub/core/database just to display the GUI. Local fallback
starts even when hub is unavailable; registration retries with bounded
backoff (1 s doubling to 30 s with jitter) while the launcher reports the
degraded state. Configure a stable hub hostname and per-robot credential,
not a robot address in the hub. The supervised service owns reconnection,
not a foreground shell loop. Run one hub worker until connection routing
across workers is explicitly implemented.

## Phase 22b — physical acceptance testing (started 2026-09-23, IN PROGRESS)

Deferred until Phase 23 proceeded first (owner's call, 2026-09-22) so it
wasn't blocked on Nano hardware availability, then started 2026-09-23 once
the owner was physically present and supervising. Real outbound WSS
registration was achieved for the first time, the real daemon came up
non-simulated, daemon audio was root-caused and fixed (self-healing on
every future daemon start), and all 14 of the daemon's mapped named
behaviours were owner-accepted — see [first-motion
session](verification/phase-22b-first-motion-2026-09-23.md) for full
evidence. One motor (`stewart_5`) doesn't reach precise commanded head
poses; the owner explicitly decided not to pursue physical
inspection/repair of it, since this project isn't the robot's
manufacturer and named behaviours only need to convey action/emotion, not
exact joint tracking — that thread is closed, not blocking. Resume by
continuing deliverable 5 — the acceptance matrix below — most rows remain
unattempted (TLS, network-change reconnect, 8h/24h endurance, physical
voice round-trip beyond audio playback, channels/calls, etc).

### Required equipment and configuration

- Powered Reachy and Nano, stable network, adequate cooling/storage, local
  physical access and a tested means to stop motion/audio.
- Homelab Docker Compose/Buildx, Postgres backup, known deployment revision,
  private env file with owner/session credentials and robot/network settings.
- Laptop/phone browser, microphone/speaker/camera, HTTPS hostname/certificate
  and LAN/VPN route. Confirm name resolution from containers and the Nano.
- Real local LLM endpoint discovered through `/v1/models`; hosted-provider
  and Telegram credentials for those live checks, kept in ignored files.
  Do not share the production Telegram polling token with a concurrent test
  stack. Live sends target an explicitly chosen test chat.
- No Google credentials required to pass Phase 22b; Phase 23 adds them.

### Satisfactory-run acceptance matrix

The thresholds below are planned acceptance targets, not measured results.
Record workload, timestamps and actual values; change a target explicitly
before the final run if hardware evidence makes it inappropriate.

| Test | Pass condition and evidence |
|---|---|
| Automated baseline | All Python tests, Ruff, JS syntax/browser regressions pass; `bash -n` and ShellCheck pass for launchers; test failures, missing dependencies and skips are recorded |
| Startup/restart | Three successful startup cycles, including one cold boot of each physical host; second launcher invocation creates no duplicates; with installed assets, GUI/core/hub ready within 120 s of launcher invocation and robot registered within 60 s of network/daemon readiness |
| Physical identity | GUI reports the actual robot and `sim=false`; observed movements, fresh camera scene changes and audible playback correspond to commands; synthetic frames cannot count |
| Motion/fallback | Ten cycles of safe named behaviours; local idle persists through a 5-minute homelab outage; disconnected state appears within configured watchdog timeout + 2 s, recovery within two heartbeat intervals + 5 s; no unsafe or replayed motion |
| Outbound connectivity | With inbound robot ports blocked, prove WSS command/state and separate media transfers through real Caddy/TLS; switch robot networks and restart hub, reconnect within 60 s of restored connectivity without address edits or replayed actions; reject wrong/revoked tokens and old connection generations; media load must not starve heartbeats |
| Jetson/daemon failure | Shut down Nano independently: core and independent embodiment continue under ADR 0004; restart daemon separately and recover without duplicate hardware controllers; revised topology requires its documented alternative criteria |
| Physical voice | 20 scripted quiet-room turns, at least 18 correctly transcribed and answered; report STT, inference and end-to-end p50/p95 separately; target local end-to-end p95 <=15 s after end of speech, with no stalled presence loop |
| Privacy and consent | Office/private responses never speak sensitive fixture content into the room; DND queues proactive notices while direct chat replies work; voice cannot approve send/delete and bulk deletion remains blocked |
| Channels and calls | Ten real web → Telegram → web exchanges retain the user/session; five real browser PTT calls deliver audio privately with no room playback; camera/control/speak work with core stopped; test desktop and mobile |
| Inference failure | Local success, real hosted cloud manual override and local-failure fallback; usage records both attempts; cancellation causes no second attempt; sanitized errors and existing deadlines hold |
| Persistence | Reboot preserves owner login capability, provider settings, sessions and durable work data; expected in-memory transcript reset is distinguished; restore a backup into a disposable project successfully |
| Endurance | 8-hour desk run including at least 50 interactions, plus one 24-hour idle soak; zero crashes/OOMs, unintended motion or privacy failures, no sustained thermal throttling; after warm-up hourly RSS shows no unexplained continuing growth and final RSS is within 20% of baseline |
| Launcher failures | Missing config, unreachable hub, unavailable daemon, occupied port and headless display produce accurate, bounded diagnostics without destroying data; local fallback survives missing hub |

Collect redacted logs, host/version inventory, timing/resource samples,
test results and short physical observations/video where useful in
`docs/verification/phase-22-<date>.md`. Mark each check PASS/FAIL/BLOCKED
and distinguish simulation from hardware and real external accounts.
Never commit private recordings, message content, tokens or credentials.
Completion requires every required row to pass and no unresolved safety,
privacy, data-loss or startup blocker; a hardware-unavailable run is BLOCKED,
not a completed physical test. Clean up only disposable test resources.

## Phase 23 — production Google account settings

Implementation is complete, with isolated Postgres, provider, API and browser
checks. Production acceptance remains open: Google application registration
and owner consent, real refresh/revoke/reconnect, audience requirements, and
the deferred hardware repeat. See [ADR 0021](adr/0021-google-accounts.md) and
[Accounts verification](verification/phase-23-accounts-2026-09-23.md).
Ordinary users connect through Google's own username/password and permission
screens; Reachy never collects a Google password.

### Cross-cutting prerequisite: schema migrations and SecretStore

Complete this work before adding Google account tables or persisting OAuth
credentials. It is a prerequisite within Phase 23, not a new numbered phase.
The foundation is implemented and verified on isolated Postgres and built
images; see [ADR 0020](adr/0020-schema-and-secrets.md) and
[evidence](verification/phase-23-foundation-2026-09-23.md). Existing deployments
must follow the [explicit cutover](deployment.md#schema-upgrades-and-credential-keys);
this work did not upgrade any production database. Google account integration is also implemented;
[Accounts evidence](verification/phase-23-accounts-2026-09-23.md) distinguishes
fixture verification from the outstanding real-account/production gates. The requirements below remain the contract.

**Database schema versioning/migrations.** Introduce Alembic with explicit,
reviewed revisions for the shared Postgres database. Keep a single ordered
migration history with table ownership documented for hub/core; migrations
must not require importing either service's runtime into the other. Existing
SQL stores can remain SQL stores; this does not require an ORM rewrite.

- Inventory current and historical schema shapes, including previously
  missing columns. Provide a fresh-database path and an explicit legacy
  adoption path that inspects schema, repairs supported differences and
  validates before recording a baseline revision. Never blindly stamp an
  existing database as current or assume `CREATE TABLE IF NOT EXISTS`
  proves its shape. Unknown schema drift fails with actionable diagnostics.
- Run migrations once through a dedicated deployment job/command, with
  serialization/locking and bounded failure handling. Launchers run or wait
  for that job before starting compatible services; application startup
  checks schema compatibility instead of independently mutating tables.
  Retire startup DDL after migration coverage is complete.
- Version new accounts, OAuth state, encrypted secrets, calendar selections
  and provider metadata through this history. Use transactional changes where
  supported, explicit handling for nontransactional steps and resumable data
  backfills. A failed migration must not mark its revision complete.
- Back up first, record revision/application compatibility, and define recovery
  for interrupted or failed upgrades. Prefer a forward fix or tested backup
  restore when downgrade would destroy data; do not promise every revision
  is reversible. No automatic volume reset or startup downgrade.

**Shared SecretStore.** Introduce a core-owned provider-neutral interface for
credential creation/replacement, resolution, deletion and key rotation. LLM,
Google, SMTP and future core connectors use it; avoid a Google-only token
encryption subsystem or a general decrypt endpoint exposed through hub.
Preserve service boundaries and least privilege: hub proxies authenticated
settings and receives masked metadata, never decrypted provider credentials.

- Use a maintained authenticated-encryption implementation, versioned records
  and key IDs, with owner/provider/purpose bound to the encrypted value. Store
  opaque secret references in provider settings. Keep encryption keys outside
  Postgres in permission-restricted deployment secrets, distinct from the
  session signing key, with documented rotation and backup/recovery.
- Migrate both local and cloud LLM API keys from existing `llm_config` JSONB
  into SecretStore, preserving URLs, models, policy, omitted-key behaviour,
  explicit-null deletion and response masking. Never log secret values during
  migration. Persist ciphertext/reference and remove the active plaintext
  field atomically; interrupted upgrades must be safe to resume.
- Plan a coordinated application cutover so old instances cannot rewrite
  plaintext configuration. Include an explicit required-key preflight before
  migration. Missing/wrong keys or tampered records fail credential use closed,
  without falling back to legacy plaintext or echoing decryption errors.
- Google refresh tokens and runtime-managed OAuth client secrets use this
  store from their first write. SMTP credentials, if configured, use the same
  interface; keep environment-injected credentials as an explicit bootstrap
  source and never copy them to plaintext database fields. Inventory existing
  credential sources before migration; Mailpit alone does not prove a stored
  SMTP credential migration. Future connectors reuse the interface.
- Rotate by key ID with a resumable re-encryption process, retaining needed
  old keys until current records and retained backups are accounted for.
  Historical backups/WAL and old row versions may still contain plaintext
  LLM keys after logical migration: document restricted retention/expiry and
  provider-key rotation rather than claiming physical erasure from an UPDATE.
  Database encryption does not encrypt the source `.env` file automatically.

Acceptance for this prerequisite uses real isolated Postgres: fresh install;
supported older schema upgrades with seeded historical data; repeat/no-op
upgrade; concurrent migration exclusion; injected failure and recovery; and
backup restoration. Verify owner login, sessions, usage and settings survive.
Migrate fixture LLM credentials, prove inference still works, inspect active
rows for absent plaintext, and verify masking/null/partial-update semantics.
Test tamper/wrong-key denial, key rotation with interruption and old/new-key
backup recovery. Demonstrate reuse for Google and configured SMTP without
sending real mail. Update ADRs' current-state notes only after implementation
and evidence; retain their historical record of plaintext storage/startup DDL.

### Product scope

Add **Settings → Accounts** to the existing operator GUI, with separate
Gmail and Google Calendar cards. Support one Google identity per owner for
this phase, independently enabled capabilities, explicit linked identity,
granted permissions, selected calendars, last successful fetch/check,
connection health, Connect, Reconnect, Test connection and Disconnect.
Handle consent cancellation, partial grants, quota/network errors and revoked
access clearly; do not show “connected” merely because a token exists.

First production release is **read-only**: Gmail list/search/read and calendar
selection, upcoming events and free/busy. Keep drafts local. No Google send,
delete, mark-read, calendar edits or attachment ingestion in this phase.
Adding writes later requires ADR 0011 consent/undo semantics and new scope;
linking an account must never activate the existing Mailpit/SMTP send path.
Google reads must reach existing conversation/briefing/calendar flows, not
stop at a successful OAuth screen. Add deterministic mail read intents/tools
as needed and preserve the shared conversation pipeline.

### Architecture and implementation sequence

1. Complete the migrations/SecretStore prerequisite above and write an
   account-integration ADR before connector implementation: core owns OAuth
   exchange/refresh, encrypted credential storage and provider adapters; hub
   owns authenticated settings proxies, browser redirect/callback transport
   and owner identity. Define shared models/routes and additive migrations.
   Google authorization does not replace the operator's owner login.
2. Provision a Google Cloud project, enable Gmail/Calendar APIs, configure
   consent audience and a Web application OAuth client. Store the client
   secret and encryption key as deployment secrets; show setup readiness,
   public callback URI and masked configuration in the GUI. Changing client
   identity must explicitly invalidate/reconnect affected grants.
3. Implement authorization-code flow with offline access, PKCE where
   supported, short-lived single-use state tied to the initiating owner and
   capability, fixed allowlisted redirect URI and bounded callback handling.
   Existing SameSite=Strict session cookies will not accompany Google's
   cross-site return: use a narrowly scoped, short-lived callback binding
   cookie/state design, then require owner session verification on same-origin
   completion. Do not weaken all owner cookies or leave callback identity
   unbound. Ordinary account mutations retain `X-Reachy-CSRF: 1`; the OAuth
   callback uses validated state/binding instead of that custom header.
4. Store refresh tokens through the shared core SecretStore above, with a key
   outside the database, documented backup/rotation and fail-closed missing-key
   behaviour. Do not introduce a separate Google-specific encryption path.
   Never expose tokens in UI, URLs, logs, prompts, usage records or localStorage.
   Redact callback query strings from proxy/access logs. Preserve an existing
   refresh token when a token exchange omits it; serialize concurrent refresh
   and atomically persist replacement tokens.
5. Add bounded provider reads with pagination, timeouts/backoff and explicit
   stale/unavailable status. Prefer on-demand reads and a bounded cache over
   new push infrastructure. Keep provider IDs/provenance distinct from local
   fixtures, normalize timezones/all-day/recurring/cancelled events, and
   de-duplicate reminders. Local event-create endpoints must not become
   ungated Google writes. Provider text is untrusted content, never authority
   to run tools; retain work-private labels and explain cloud context sharing.
6. Disconnect disables reads immediately, removes credentials and cached
   provider content, and attempts grant revocation. Report revocation failure
   and shared-grant effects honestly: revoking one Google grant may require
   reconnecting both capability cards. Define retention of user-created local
   drafts separately; do not erase them silently. Close Caddy debug-proxy and
   trusted-API bypasses for Google credentials and newly exposed private reads;
   test that callers cannot select another owner's account via `user_id`.

Use Gmail `gmail.readonly` and Calendar `calendar.events.readonly` plus
`calendar.calendarlist.readonly` for event reading and selection; derive
free/busy from accessible events or request the minimum additional documented
scope if the provider free/busy endpoint is used. Request only enabled
capabilities and verify actual grants. See [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
and [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth).

Use a stable HTTPS callback URL registered exactly with Google, accounting
for the Caddy `/hub/` prefix. Test direct development and production proxy
mounts with their explicitly registered callbacks. The browser can return
to a VPN-accessible hostname; do not expose internal APIs simply for OAuth.
Google's [web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server)
documents offline access and callback requirements. External applications
left in Testing receive seven-day refresh tokens for these scopes, so that
mode is not evidence of durable production readiness; see [token expiration](https://developers.google.com/identity/protocols/oauth2).
Gmail read-only is a restricted scope: document the deployment audience and
applicable verification/assessment requirements or personal/internal-use
exception before rollout. Selecting “In production” alone does not prove
verification or grant unrestricted distribution.

### Phase 23 acceptance and production release gate

- Schema migration and shared SecretStore prerequisite acceptance passes,
  including preservation of existing data and migration of stored LLM keys.
- Automated in-process and browser tests cover owner/CSRF enforcement,
  callback state replay/expiry/wrong owner, strict-cookie return flow, partial
  consent, missing refresh token, concurrent refresh, revoked grants, API
  timeouts/429s, masking, encrypted persistence and bypass denial.
- Owner connects a real designated Google account through the deployed HTTPS
  GUI. Read known test messages and events and verify results through actual
  chat and briefing/reminder paths. Seed fixtures manually in Google; the
  application itself must make zero Google write calls.
- Confirm calendar selection, timezone/day boundaries, recurring exceptions,
  pagination and no duplicate reminders. Mail contents render literally;
  malicious email instructions cannot initiate actions or exfiltrate data.
- Observe at least one real access-token refresh and restart/reboot without
  re-consent; a mocked expiry alone is not live evidence. Revoke access in
  Google, observe reconnect-required status, reconnect successfully, then
  exercise local disconnect and shared-grant behaviour.
- Verify from desktop/mobile and Nano browser (if a desktop is installed),
  Office/DND privacy, and read-only permissions at Google as well as in the
  app. No production account data or tokens appear in logs or test reports.
- Restore encrypted account records and their key into an isolated test
  deployment; verify recoverability without two active polling deployments.
  Missing/wrong keys fail safely. Confirm Google app publishing/audience
  requirements and record any unresolved external verification blocker.
- Once Phase 22b's own hardware acceptance has run, repeat its startup,
  outages, privacy and 8-hour desk acceptance with Google enabled. Record
  evidence in `docs/verification/phase-23-<date>.md`. Production readiness
  requires all these checks and applicable Google setup gates; a fixture
  server or consent-only demo does not qualify. Phase 23's own
  implementation and functional (non-physical) tests can proceed before
  Phase 22b, per the split below — only this final physical-repeat step
  genuinely depends on 22b's baseline existing first.

## Execution boundaries

Phase 22 is split: implement Phase 22a (inventory/topology, real backend, WSS
connectivity, launchers) first — done. Phase 22b (real hardware acceptance
and fixes) is deliberately deferred; begin Phase 23 with schema migrations
and SecretStore now, without waiting on it, then implement Google
connectors. Phase 23's final physical-repeat acceptance (see above) still
needs Phase 22b's baseline to exist first, so return to Phase 22b before
declaring Phase 23 production-ready end to end. Credentials
belong in ignored, permission-restricted local files, never chat. This plan
does not reflash the board, launch a production stack, authorize Google access,
or claim either phase complete.
