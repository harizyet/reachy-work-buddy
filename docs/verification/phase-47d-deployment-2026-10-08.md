# Phase 47D deployment (2026-10-08)

Owner-approved deployment of main `6aa160d` (images `reachy-core:47d-test`, `reachy-hub:47d-test`, built from the merged tree) to the homelab. No migration (revision stays `027_knowledge_index`), `KNOWLEDGE_INDEXING_ENABLED=false`, 80 index rows unchanged. The first attempt stopped core, hub and coding-agent (about 3 minutes), took the backup, then was blocked before the image swap; the old containers were restarted. The second attempt recreated core and hub (coding-agent unchanged).

- Backup: `~/reachy-backups/reachy-before-phase47d-20261008-220617.dump` (276,527 bytes, 0600; not restore-verified). Rollback tags `reachy-rollback/*:027-pre47d` and `*:027-pre47d-container`; env copy `~/reachy-backups/env-before-phase47d`. Previous images: core `3dfd299d5e3b`, hub `68d9733ca8de`.
- Checks: core `/health` 200; hub serves `/web/` (200); hub `/brain/summary` without a session 401; revision 027; flag false.
- Production holds one meeting and no tasks, notes, reminders, memories or documents, so the Brain should list one record.
- Not done: the owner-session check of `#/brain` (needs the owner's login), robot, voice, Telegram.
- Rollback: retag the `:027-pre47d` images to `:latest` and `docker compose -p reachy-homelab --env-file .env up -d --no-build companion-core reachy-hub`.
