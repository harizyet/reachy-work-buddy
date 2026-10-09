# Proposal: minimal operational hardening for PostgreSQL recovery (2026-10-12)

Status: **proposal only. Nothing in this page has been built, scheduled or changed.** No existing recovery asset (the dumps in `~/reachy-backups`, the `reachy-rollback/*` images) is to be deleted, and no production backup behaviour changed, without the owner's approval. Requested by the owner on 2026-10-12 after the Phase 44H deployment, when the absence of any scheduled production backup meant the deployment-specific dump could not be shown to be redundant.

## What exists today (read-only facts, 2026-10-12)

| Item | State |
|---|---|
| Database | PostgreSQL 16 (pgvector) in the compose volume `reachy-homelab_postgres-data`, database `reachy_hub`, **11 MB** |
| Backups | **None scheduled** (no cron entry, no systemd timer except the distribution's `dpkg-db-backup`). Recovery points are the hand-taken pre-deployment dumps in `~/reachy-backups`: 35 files, 3.1 MB in total, mode 0600, the newest from the 44H deployment (verified with `pg_restore --list` at the time) |
| Keys | `.env.secret-keys.json` and `.env.coding-agent-secret-key.json` (0600) decrypt stored credentials. A dump is useless without them. The HANDOVER records an encrypted off-host key copy that the owner accepted as sufficient |
| Off-host copy of dumps | none documented |
| Failure detection | none: nothing would notice that backups had stopped |
| Restore testing | done by hand during deployments (rehearsal on a throwaway container), not periodically |
| Tools available on the host | `gpg`, `restic` (no `age`, no `borg`) |
| Retention rules in the repository | none written down |

## Goals, kept deliberately small

The data is small and slow-changing, so the aim is a boring, verifiable loop rather than a backup platform: **an automatic daily logical dump, kept long enough to matter, encrypted, copied off the machine, with a failure that makes noise and a restore that is proven on a schedule.**

## Proposal

1. **Automated dumps.** A systemd **user** timer (daily, 03:30 local, `Persistent=true` so a missed run happens at next boot) runs a small script that executes `pg_dump -Fc` **through `docker exec` on the postgres container** (direct, never through PgBouncer), writes to a new directory `~/reachy-backups/scheduled/` with `umask 077`, names files `reachy-hub-YYYYmmdd-HHMMSS.dump`, and verifies each dump before accepting it: non-zero size, `pg_restore --list` succeeds and lists `alembic_version`, and the table-of-contents entry count is within 20% of the previous dump. The script never touches the existing hand-taken dumps and never writes to the database. A dump that fails verification is moved aside as `*.failed` and counts as a failure.
2. **Retention.** Keep 7 daily, 4 weekly and 6 monthly scheduled dumps (about 17 files, under 6 MB at today's size), pruned by the script only inside `scheduled/`. Hand-taken deployment dumps are outside the policy and are removed only on the owner's explicit decision. Retention is a written number in the script header and the deployment guide; at this size cost is not a reason to shorten it.
3. **Encryption.** Dumps contain personal data. Encrypt each accepted dump with `gpg --symmetric` or, preferably, to a recipient public key whose private half is **not** on this host (the key copy the owner already keeps off-host), so a stolen disk or a copied backup directory reveals nothing. The unencrypted working dump is deleted after encryption. The restic repository in the next item is itself encrypted, so this is only needed if dumps also stay unencrypted on local disk; the owner's choice. The Postgres credential keyring is backed up separately, already encrypted off-host, and is **verified in the restore test** (the dump must decrypt its stored credentials with the backed-up keyring).
4. **Off-host copy.** Copy the encrypted dumps to a second place so one disk or one machine is not the only copy: either the existing USB storage the owner already uses for the key backup, or a `restic` repository on another host or bucket the owner names. This needs a destination decision; it is the part of the proposal that cannot be defaulted.
5. **Failure detection.** The script writes `~/reachy-backups/scheduled/STATUS.json` (last success time, last dump name, size, table count, last error). Two independent signals: the timer unit has `OnFailure=` that sends a message through the existing Telegram path (a dedicated receipt/notification rather than a new channel), and a second, separate watcher on the hub side or a different timer alerts when **no successful dump is newer than 36 hours**, so a stopped timer, a full disk or a dead script is also noticed. Both alert to the owner once per day, not per minute. A disk-space check (alert below 10 GB free) is included, because the Nano's disk filled once.
6. **Periodic restore testing.** Monthly (and after any schema migration), a timer restores the newest scheduled dump into a **throwaway** `pgvector/pgvector:pg16` container on an `--internal` network with no published ports and a random password (the same pattern as the deployment rehearsals), then checks: revision equals the live `alembic_version`; per-table row counts are within the live counts at dump time; every stored credential decrypts with the backed-up keyring; the `knowledge_items` and `knowledge_outbox` counts match. It then removes the container, network and files, records pass or fail and the elapsed time in `STATUS.json`, and alerts on failure. A restore that has never been tested is not a backup.
7. **Documentation and ownership.** The procedure, the policy numbers, the way to run a manual restore and the rule "deployment dumps stay until the owner releases them" are added to [deployment.md](deployment.md). A small verification record is written once the first full cycle (dump, encrypt, copy, alert test, restore test) has passed.

## Out of scope (kept out on purpose)

Point-in-time recovery (WAL archiving) and replication: the data is 11 MB and the recovery objective is "yesterday", not seconds. Backing up Docker images (they rebuild from git; the `reachy-rollback` tags are a separate, short-lived deployment aid). Backing up the model caches and vLLM weights. Any change to the database, PgBouncer, the application or the hub in this work.

## Risks and how the proposal handles them

| Risk | Handling |
|---|---|
| A backup job putting load on the production database | a 11 MB `pg_dump` takes about a second; it runs at 03:30 and uses one connection direct to Postgres, not the pooled path |
| Dumps leaking personal data | 0600 files, encrypted before any copy leaves the host, private key off-host, copies deleted from the working directory |
| A silent failure | two alert paths (failure hook and stale-success watcher), plus the monthly restore test |
| Deleting something that mattered | pruning is limited to `scheduled/`; existing dumps and rollback images are never touched by the job |
| A backup that cannot be decrypted because the keyring or the GPG key was lost | the restore test proves the credential keyring works; the off-host key copy is tested for readability as part of the first cycle |

## What would count as done

A dated record showing: the timer ran unattended for 7 consecutive days; a deliberately broken run produced an alert within one day; a deliberately stopped timer produced the stale-success alert; an encrypted off-host copy restored into a throwaway container passed all restore checks; retention pruned only inside `scheduled/`; the existing recovery assets were unchanged (file list and hashes before and after).

## Decisions needed from the owner before any work

1. The off-host destination (USB storage, another host, or a bucket).
2. Whether local dumps are also encrypted (item 3) or only the off-host copy.
3. The retention numbers (7 daily, 4 weekly, 6 monthly proposed).
4. Which Telegram or other channel receives backup alerts.
5. Whether, once the first full cycle has passed, the deployment-specific dump and the `pre-44h-boundary` rollback image may be released.
