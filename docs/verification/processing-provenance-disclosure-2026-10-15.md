# Verified processing provenance and fixed email disclosures: verification (2026-10-15)

Branch `feature/processing-provenance-disclosure`, on top of `fix/gmail-app-password`. Decision: [ADR 0040](../adr/0040-verified-processing-provenance-in-email.md). Not merged, not deployed, no migration applied
outside disposable databases. Mocks, real SMTP and real database results are labelled separately.

## What was verified, and how

| Claim | Evidence | Kind |
| --- | --- | --- |
| Each processing step records where it ran, from the real code path (worker stages, outputs, title, corrections, analysis runner, cloud question) | `tests/test_meeting_provenance.py` drives the real worker functions and the real routes against in-memory stores and a scripted model endpoint | in-process, mocked model |
| A cloud call is recorded before any content leaves (a failed attempt still counts) | the model endpoint inspects the meeting's record at request time, for outputs and for analysis | in-process |
| Endpoint classification | parametrised table: Compose names, localhost, RFC 1918, Tailscale, link-local, `.lan/.internal` are local; public names, public IPs, empty and malformed are unverified | unit |
| Verdicts: local-only, cloud escalation, mixed, missing, regenerated, analysis run, generated title | same file; a regenerated local summary keeps the earlier cloud record; old meetings with no record are unverified | in-process |
| The email text follows the verdict and the owner cannot edit the disclosures away | same file: required local-only sentence, external naming only the step, neutral statement, delivery sentence always present (Gmail and other host, with and without attachment), body edits leave fixed text intact, sent text equals the approved preview | in-process |
| Approval, hash and delay unchanged | typed `SEND` still required, wrong word refused, nothing sent before the delay; a different verdict is a different package hash; a forged frame no longer matches its hash | in-process |
| Provenance changes after preparation or approval stop the send | cloud regeneration or a cloud question after preparing blocks queueing; external processing inside the undo window makes the sender refuse and nothing goes out | in-process |
| Real SMTP | `test_meeting_email_mailpit.py` (19 passed with `MAILPIT_TEST=1`): the delivered message is the rendered text with identity, neutral statement and "external email provider" delivery sentence, PDF intact | real SMTP with TLS and auth (Mailpit) |
| Real PostgreSQL | `test_meeting_provenance_postgres.py` (6 passed): migration, repeat, rollback, events appended in the same statement, cleared outputs cannot hide a cloud record, owner name; every older migration test updated for head 037 (125 passed, 1 skipped on a disposable `pgvector/pgvector:pg16`) | real database |
| Web | vitest 376 passed; Playwright `meeting-email.spec.ts` desktop 3 passed (delivered text asserted); `tsc --noEmit` clean | real browser, fixture SMTP |
| Android | JVM 170 passed (2 new, untracked because of the `.gitignore` `test/` rule); screen compiled | JVM, no emulator run for this change |

Core full suite: see the final line in the handover. Known unchanged failures: `test_knowledge_index` reconcile and `test_knowledge_retrieval` historical mode (both fail on `main`), nine Playwright specs (notepad, planner).

## Findings fixed on the way

- The hub's sender body (`extra="forbid"`) would have rejected the new `owner_name` with 422 in production; the hub test now sends it.
- An external step was counted as "missing local evidence", so a cloud summary hid the fact that every other step was private; the rule now skips steps that are themselves external.

## Not verified

- No real Gmail message with the new text has been sent; the owner has not seen it. First send after deploy must go to the owner's own address.
- No Android emulator run of the new fixed-text cards.
- Behaviour of the live local-model endpoint classification: the production `llm` local URL has not been read here; if it is a public host name, summaries will be recorded `unverified` and emails will carry the neutral statement.
