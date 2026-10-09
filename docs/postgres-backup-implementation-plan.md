# PostgreSQL backup: implementation plan (PLAN ONLY, 2026-10-12)

Status: **plan for owner review. Nothing is built, installed, scheduled or changed.** No production backup behaviour changes, no credential is created or stored, and the existing 44H dump (`reachy-before-phase44h-boundary-*.dump`) and the `reachy-rollback/companion-core:pre-44h-boundary` image stay untouched until this plan, its credential handling and its storage handling are reviewed and approved. It implements the owner's choices of 2026-10-12 on top of the [hardening proposal](postgres-backup-hardening-proposal.md).

## 1. Owner choices this plan implements

| Choice | Plan |
|---|---|
| Off-host destination | **Synology NAS, provided it is a separate failure domain** (see section 3: this condition is not yet shown to hold) |
| Encryption | Backup artifacts are **encrypted before they leave the host** |
| Retention | **7 daily, 4 weekly, 6 monthly** |
| Alerting | **Telegram to the owner on failure, staleness or verification failure only; no routine success messages** |
| Restore test | **Monthly, into an isolated disposable PostgreSQL instance** |
| Restore verification | **Schema/revision, representative tables and integrity checks** |

## 2. What the job does (design)

One host script, `scripts/backup/reachy-pg-backup.sh`, driven by a systemd **user** timer (daily 03:30 host time, `Persistent=true`; the user needs lingering enabled so it runs after a reboot without a login). Each run:

1. **Dump.** `docker exec reachy-homelab-postgres-1 pg_dump -U reachy -d reachy_hub -Fc` (direct to Postgres, never through PgBouncer; read-only; about one second at 11 MB). `umask 077`; staging directory `~/reachy-backups/scheduled/staging/`.
2. **Verify the dump** before accepting it: size above a floor, `pg_restore --list` succeeds and lists `alembic_version`, the table-of-contents count is within 20% of the previous accepted dump. Record in a sidecar **manifest** (JSON, inside the artifact): UTC time, host, database size, Alembic revision (`select version_num from alembic_version`), row counts of every public table, extension versions, and the SHA-256 of the dump. Row counts are taken in the same transaction snapshot as the dump (`pg_dump --snapshot` with an exported snapshot, or one `REPEATABLE READ` read-only transaction), so a later restore can be compared exactly.
3. **Encrypt** (section 4) the dump and its manifest into one artifact `reachy-hub-YYYYmmddTHHMMSSZ.dump.gpg`; delete the plaintext staging files with `shred -u`.
4. **Keep locally** under `~/reachy-backups/scheduled/` (the same retention tiers) and **upload to the NAS** (section 3). A failed upload does not fail the local backup; it is queued (the file simply remains un-uploaded) and retried on the next run and every hour until it succeeds.
5. **Retention** (section 5), local and NAS side, by the same code.
6. **Status.** Atomically rewrite `~/reachy-backups/scheduled/STATUS.json`: last attempt, last verified local backup, last NAS upload, last restore test and outcome, free disk space, last error. This file is the only place success is recorded; success never sends a message.
7. **Alert** (section 6) only when something is wrong.

The script never writes to the database, never stops or restarts a container, and never touches any path outside `~/reachy-backups/scheduled/` and the NAS target folder. Hand-taken deployment dumps in `~/reachy-backups/` (and everything named `reachy-before-*`) are outside its pattern and are never listed, pruned or moved.

## 3. The Synology NAS as a separate failure domain, and credential handling

**What is known (read-only, 2026-10-12).** The repository documents no NAS. The Tailscale network lists a Linux node named `localnas` (last seen about two days earlier, offline when checked); the LAN is `10.180.1.0/24`. Whether `localnas` is the Synology, and whether it sits in a separate failure domain (different physical device and disks, ideally a different power circuit, not in the same enclosure or on the same filesystem as this host, not mounted writable into this host's filesystem as a normal directory that a bug could `rm -rf`), is **not established**. It is an input the owner must confirm. A NAS on the same power strip in the same room is a separate device but only a partly separate failure domain (fire, theft, power surge); the plan records that residual risk instead of hiding it.

**Transport.** SFTP (or rsync over SSH) to a dedicated DSM user, over the LAN address or the Tailscale name. No SMB/NFS mount on the host: a mounted share lets a runaway process delete history, and a stale mount can hang the job.

**Credentials (to be reviewed and approved before anything is created).**
- A **dedicated DSM user** `reachy-backup`, member of no admin group, shell disabled except SFTP, with read/write only on one shared folder `reachy-backups` (quota, for example 5 GB, which is 100 times today's need). It cannot see any other share.
- A **dedicated SSH key pair** generated on the host for this job only (`~/.ssh/reachy-backup_ed25519`, mode 0600, passphrase-less because the job is unattended; the public key goes into that DSM user's `authorized_keys` with the forced command or SFTP-only restriction DSM supports). The key is not reused for anything else, and its path and fingerprint are recorded in the deployment notes (the key material never appears in a log, a document or chat).
- **NAS-side protection against a compromised host:** enable DSM **Snapshot Replication** on the `reachy-backups` share with immutable (locked) snapshots for 30 days, so a host that is compromised or buggy cannot permanently delete the history. This is the one setting that makes the "separate failure domain" real against deletion, not just against disk loss; if the owner's DSM cannot do it, the plan says so and the residual risk is accepted explicitly.
- **Telegram:** the alert sender needs a bot token. Preferred: a **new, dedicated bot** (or at least a dedicated token) so a leaked backup token cannot read the owner's conversations; fallback: read the existing `TELEGRAM_BOT_TOKEN` from `deploy/homelab/.env` (0600) at run time, which widens the blast radius and is flagged for the owner's decision. The token is stored in `~/.config/reachy-backup/config` (0600, outside the repository, gitignored pattern confirmed), never echoed.
- **Encryption key** (section 4) is separate from both.
- Nothing in the repository holds a secret. Everything lives in `~/.config/reachy-backup/` (0700) and is described, not contained, in the documentation.

## 4. Encryption

Artifacts are encrypted **before transfer** with `gpg --encrypt --recipient <backup key> --compress-algo none` (GnuPG is installed; `age` is not). The choice and its limit, stated plainly:
- **What encryption protects:** the copy on the NAS (a NAS stolen, shared, snapshotted into a cloud, or read by another user) and any copy of the local backup directory that leaves the host. It does **not** protect against a compromised host, which already holds the plaintext database.
- **Key custody.** A dedicated key pair is generated for backups. The **public key** lives on the host (encryption only). The **private key** is needed for restore and for the monthly restore test. Two options for the owner: (a) the private key also lives on the host in the GPG home with mode 0600, which lets the monthly test run unattended, with an offline copy kept with the existing encrypted key backup (recommended, because an unattended restore test is the point of the plan); (b) the private key stays offline, the monthly test becomes a manual step the owner performs when reminded. Either way, the offline copy of the private key is created and **its readability is tested in the first cycle**: an artifact nobody can decrypt is not a backup.
- The credential keyring (`.env.secret-keys.json`, `.env.coding-agent-secret-key.json`) is **not** part of the artifact and is not uploaded by this job; it keeps its existing separate encrypted off-host copy. The restore test uses the live keyring files read-only to prove the restored credentials decrypt.

## 5. Retention: 7 daily, 4 weekly, 6 monthly

Tiers are computed from artifact names, never from file times. An artifact is **daily** (the newest verified per UTC day, keep 7), **weekly** (the Sunday artifact, keep 4) or **monthly** (the first of the month, keep 6); one file can satisfy several tiers. Expected steady state about 15 to 17 artifacts, under 6 MB at 11 MB database size. Safety rules in code and in tests: pruning only touches names matching `reachy-hub-*.dump.gpg` inside the two managed directories; **dry run is the default for the first week** and prints what would be deleted; nothing is pruned if fewer than 3 newer *verified* artifacts exist; a prune that would remove more than 4 files in one run aborts and alerts; the NAS side is pruned only after the same artifact is confirmed present on the NAS by size and SHA-256. Local and NAS retention are the same numbers, applied independently.

## 6. Alerting (Telegram, failure only)

Events that send one message each (deduplicated to once per 24 h per event type, with the failing step and a one-line reason, never a secret, a path to a secret or database content):
1. The backup run failed or the dump failed verification.
2. **Staleness:** the newest verified local backup is older than 36 h, or the newest NAS upload is older than 36 h.
3. The monthly restore test failed or did not run.
4. Disk space below 10 GB free, or the NAS target folder above 80% of quota.
5. A retention action was refused by a safety rule.

No message is sent for a normal run, and no "all clear" message is sent by default (the owner can ask for a single recovery notice later). Two independent detectors, so a dead host cannot silence the alerts: **(i) host-side:** the service's `OnFailure=` unit and a separate hourly staleness timer on the host; **(ii) NAS-side:** a daily DSM scheduled task that checks the newest file on the share is younger than 36 h and sends a DSM notification (webhook to the same Telegram bot, or DSM email) if not. The host-side detector cannot see a powered-off host; the NAS-side one can.

## 7. Monthly restore test (isolated, disposable)

A second timer (monthly, plus after any schema migration, started by hand) runs `scripts/backup/reachy-pg-restore-test.sh`:
1. **Fetch the newest artifact from the NAS** (so the off-host copy and its encryption are what is tested, not the local one), decrypt it to a 0700 temp directory, and verify the manifest's dump SHA-256.
2. Start a throwaway `pgvector/pgvector:pg16` container (the production image) on a newly created `--internal` Docker network (no egress), **no published ports**, a random password in a 0600 env file, a unique name (`reachy-restore-test-<stamp>`), a memory and CPU cap, and the test dir mounted read-only; never connected to the compose network or the production database.
3. `pg_restore --exit-on-error --no-owner` into it. The command must exit 0.
4. **Verification:** (a) *schema and revision*: `alembic_version` equals the live revision and the restored object list equals `pg_restore --list` of the dump; extensions `vector` present at the same version. (b) *representative tables*: for every public table the restored row count equals the count in the manifest (exact, since taken at the dump snapshot), with named spot checks on `memories`, `notes`, `tasks`, `alarms`, `meetings`, `action_receipts` and `knowledge_items` (81 rows, 384-dimension vectors, a cosine query returns rows). (c) *integrity*: `pg_amcheck` over all tables and btree indexes if present in the image (otherwise `amcheck` function calls), validity of all constraints and foreign keys (`select ... from pg_constraint where not convalidated`), no invalid indexes (`pg_index.indisvalid`), sequences at or above their column maxima. (d) *credentials*: the application's migration job, run twice against the restored copy with the live keyring mounted read-only (the documented deployment check), confirms every stored credential decrypts.
5. **Always clean up:** remove the container, network, and temp files with `shred`, even on failure; confirm nothing named for the test remains; record pass or fail, elapsed time and the checks that ran in `STATUS.json`; alert on any failure.

## 8. Failure modes and how each is detected

| Failure | Detection |
|---|---|
| Timer not running, host off, disk full, script bug | host staleness timer; NAS-side staleness task; disk-space check |
| Corrupt or empty dump | verification step; monthly restore test |
| NAS unreachable or offline (it was offline when checked) | upload retried hourly; a 36 h staleness alert; local copy still made |
| Encryption key lost or unreadable | first-cycle decrypt test of the offline copy; every monthly test decrypts |
| Silent schema drift (new tables not in dumps) | the manifest lists every public table; the test compares them to the live schema |
| Retention bug deleting too much | name-pattern guard, minimum-newer-verified rule, max-deletions guard, dry-run week, NAS-side immutable snapshots |
| A compromised host deleting the NAS copy | immutable DSM snapshots (or the explicitly accepted residual risk) |

## 9. Work breakdown, with approval gates (nothing starts without approval)

0. **Plan review** (this document): owner reviews credential handling, storage handling, key custody option, alert-token option; gives the inputs in section 10.
1. **Build in a sandbox:** the two scripts, the systemd units (templates), the config template, the unit tests (a fake `docker`, a temp directory standing in for the NAS, a fake Telegram sender; retention tests with a clock; the guard rules; the verification step against a throwaway PostgreSQL), ruff/shellcheck clean. No production access.
2. **Dry run on production, read-only:** one manual run to a temporary directory (a `pg_dump` is read-only and is what the hand-taken dumps already do), no timer, no NAS, no alert; compare against a hand-taken dump.
3. **NAS and credentials:** the owner creates the DSM user, share, quota and snapshot rule and the Telegram bot; the SSH key and gpg key are generated on the host; permissions verified; a transfer of one test artifact; the offline private-key copy tested.
4. **Enable timers** (daily backup, hourly staleness check, monthly restore test) in dry-run retention for the first week.
5. **Soak and prove:** 7 consecutive unattended days; a deliberate failure alert; a deliberate staleness alert from both detectors; the first restore test from the NAS copy; retention switched from dry run to live; a verification record.
6. **Only then** decide the release of the 44H dump and the pre-44h rollback image (owner decision; both are small).

Rollback at every step: disable and remove the user units; delete the managed `scheduled/` directories after the owner agrees; nothing else was changed.

## 10. Inputs needed from the owner

1. Confirm which device is the Synology, its model and DSM version, and whether `localnas` on Tailscale is it; where it sits relative to the homelab host (room, power), and whether DSM can take **immutable snapshots** of a share.
2. Approve the dedicated DSM user and share, the quota, and SFTP (not a mounted share) as the transport.
3. Choose key custody: private key also on the host for unattended restore tests (recommended), or offline with a manual monthly test.
4. Choose the Telegram token: a new dedicated bot (recommended) or the existing bot's token.
5. Confirm the schedule (03:30 host time daily; first-of-month restore test) and that a missed day alerts only after 36 hours.
6. Confirm that an "all clear" message after a failure is wanted or not.
