# Phase 25 foundation and benchmark portal (2026-09-28)

Consolidated from the session handover on 2026-09-28. These are previously
reported checks, not new runs or current health claims. Requirements and
remaining work belong in [Phase 25](../phase-25.md); the biometric storage
policy belongs in [Phase 26d](../phase-26.md#26d-addendum-benchmark-vs-operational-data-policy-owner-decision-2026-09-28).

## Local verification

| Change | Reported evidence | Limits |
|---|---|---|
| 25.0 contracts and deterministic trust engine | 50 new unit tests; hub/core suite 716 passed, 29 skipped; Ruff passed | Fake evidence only; no biometric integration |
| Raw-capture portal skeleton | 16 backend tests; full services/shared suite 883 passed; Ruff and JS syntax checks passed | No browser capture check; a recorder closure bug was found by code review and fixed |
| Encrypted benchmark store, explicit opt-in, export | 41 store/route tests; full suite 896 passed; Ruff and Compose configuration passed | Backend checks only |
| 25a.3 speaker-verification wiring | 6 new tests; full suite 902 passed; Ruff passed | `NoSpeakerVerifier` only; no real model |
| 25a.4 sensitivity gate (`294a1b6`) | 11 new classifier/wiring tests; full suite 925 passed; Ruff passed | Gate defaults off; no redeploy after this change |

The separate [speaker pipeline smoke test](phase-25a1-voice-benchmark-2026-09-28.md)
owns model versions, timing and accuracy limitations. Historical suite counts
above describe successive revisions, not today's test health.

## Homelab deployment

The initial capture-volume deployment at `ef40307` (05:29 UTC) established
sample persistence across a hub restart. It was superseded by encrypted
benchmark capture at `19c6545` (06:34 UTC), after a database backup and
launcher `--check`/`--build`. Hub/core health became ready in two seconds.
The schema remained `009_wake_arm`; the capture volume was empty before
the format change, so no plaintext-data migration was exercised.

The encrypted deployment was checked with curl against the live stack:

- Owner login and fresh password reauthentication succeeded.
- Upload returned 403 before benchmark mode was enabled.
- After enabling, a sample upload succeeded and reported the correct size.
- The on-disk capture contained AESGCM ciphertext rather than plaintext.
- The export zip decrypted to the original bytes and correct manifest.
- A hub restart retained both the sample and benchmark-enable flag.
- Cleanup deleted the sample, disabled benchmark mode and logged out.

The hub had `SECRET_KEY_FILE=/run/secrets/credential_keys` and the key
secret mounted. The store was left empty and off. Backup location and
host-specific continuation details remain in [HANDOVER](../../HANDOVER.md).

## Unverified

The real browser flow (permissions, MediaRecorder, canvas capture, opt-in,
sizes, deletion and export download) was not exercised. No real owner or
non-owner dataset, operational template store, calibrated model, visual
verification or physical recognition acceptance exists. The backend deploy
does not establish those capabilities.
