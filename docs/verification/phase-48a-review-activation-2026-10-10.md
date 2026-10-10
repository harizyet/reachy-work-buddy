# Phase 48A: memory candidate review, rehearsal and production activation, 2026-10-10

**Status: 48A COMPLETE. Rehearsal PASSED on a disposable stack; review-only ENABLED in production (core recreated); the owner confirmed in a production browser that the Memory page renders correctly (2026-10-10). Capture was OFF at this point and was enabled later under 48B ([trial log](phase-48b-capture-trial-2026-10-10.md)).** The robot was not involved at any point.

## 1. Rehearsal (disposable, then removed)

Real production images (`reachy-homelab-{migrate,companion-core,reachy-hub}:latest` = commit `ca21d72`), a new `pgvector/pgvector:pg16` container, a new keyring and random passwords on a private Docker network (`reachy-p48a-rehearsal`; only the hub published, on 127.0.0.1). Migration run from zero to `028_memory_candidates`. The language model was not present (the image answers "heard: ..."), so this proves the review workflow and the capture-off behaviour, not reply quality. Candidates were seeded with the real store and digester inside the core image (capture was off, so there was no other way to make them); production received no such rows.

| Check | Result |
|---|---|
| Flags off (production state) | `GET /memory-candidates` through the hub: 404; table empty |
| Review on, capture off | list 200, empty, `capture_enabled: false` |
| Change without CSRF header | 403 |
| Accept: 6 concurrent requests for one candidate | exactly one 200, five 409 "in progress"; one memory (`candidate:<id>`), one `memory.created` receipt; a later repeat accept returns 200 with the same memory (idempotent) |
| Edit and accept | edited text, type and 60-day expiry stored; `edited-accepted`; own memory and receipt |
| Reject | `rejected`, memory count unchanged; accept after reject refused (409) |
| Suppress ("never suggest") | `suppressed`; re-proposing the same text is refused (`suppressed`) while other text is proposed |
| Candidate text after any decision | none retained (0 rows with text) |
| Forget a candidate-sourced memory | existing two-step path: "forget X" asks, "yes forget X" sets `forgotten_at` |
| Capture off, normal conversation | two typical preference statements through `/conversation`: 0 candidates, 0 memories |
| UI (real Chromium, real hub, built React bundle) | sign-in, Memory page lists the pending suggestion with provenance, "Suggestions are not being collected right now" notice, "Save to memory" produces a durable memory and "No suggestions are waiting"; no page errors except the expected 401 from the pre-login session probe |
| Rollback | flag off again: route 404, candidate rows and memories kept |

Not covered: Android, a real Telegram message, the hub's real remote-access path (Caddy), a real language model, and the owner's own browser.

## 2. Production change

Backup of the environment file: `~/reachy-backups/.env.before-p48a` (0600). Two lines appended to `deploy/homelab/.env`: `MEMORY_CANDIDATES_ENABLED=true`, `MEMORY_CANDIDATES_CAPTURE_ENABLED=false`. `up -d --no-build --no-deps companion-core` at 13:43:49 UTC; image unchanged (`966642fe0c5a`), core back and healthy within 12 s, hub, database and every other service untouched. Before: no meeting in progress, 0 candidates, revision 028. After: core reports `capture_enabled: false`; the candidate table is empty (0 rows).

Rollback: set `MEMORY_CANDIDATES_ENABLED=false` (or remove the two lines) and repeat the same `up -d` for core. No schema rollback.

## 3. Open

1. ~~Owner browser check of `/web/#/memory` in production~~ DONE: the owner confirmed the page renders correctly.
2. ~~Capture eligibility must stop depending on robot wake-arm state~~ DONE under 48B.
