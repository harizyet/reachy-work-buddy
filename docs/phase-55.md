# Phase 55: Supervised meeting-minutes email through a dedicated Gmail sender

Status: **deployed to the homelab 2026-10-14 15:30 UTC with the feature off (migration 036, [record](verification/phase-55-deployment-2026-10-14.md)), enabled 15:34 UTC, merged to `main` 2026-10-15, owner UAT accepted; later changes: Gmail sign-in and app-password fixes, and verified processing provenance ([ADR 0040](adr/0040-verified-processing-provenance-in-email.md), migration 037). A real Gmail send with the provenance text is still unrecorded.** Decision: [ADR 0039](adr/0039-supervised-meeting-minutes-email.md). Evidence: [verification record](verification/phase-55-meeting-minutes-email-2026-10-14.md).

The owner opens a completed meeting, chooses **Share minutes**, reviews the package (speaker names, summary, minutes, confirmed actions, PDF), chooses recipients, approves the exact package with a typed confirmation, and the message waits ten minutes (cancellable) before the existing dispatch loop sends it through a dedicated sender account. Every message needs that manual approval. Nothing is scheduled or automatic.

## Stage A: architecture and integration audit

### What already exists and is reused

| Need | Reused component | Notes |
|---|---|---|
| Draft, approval, 10-minute delay, undo | `email/models.py` `EmailDraft`, `email/workflow.py` (`queue_draft_for_sending`, `cancel_queued_draft`, `run_dispatch_loop`), `EMAIL_SEND_DELAY_SECONDS` | [ADR 0011](adr/0011-destructive-action-consent.md): approval and send are text-only (`require_text`); the loop is the only code that calls a sender |
| Credentials | `secrets.py` `PostgresSecretStore`, `SecretContext("owner","smtp","password")`, AES-256-GCM, key file outside Postgres | [ADR 0020](adr/0020-schema-and-secrets.md): no decrypt endpoint; authenticated SMTP must STARTTLS |
| SMTP transport | `aiosmtplib` already a core dependency; Mailpit in the `simulation` profile | `SMTP_SECRET_REF` provisioning existed only through an internal interface |
| Meeting content | `Meeting.summary` / `.minutes` ([ADR 0032](adr/0032-meeting-outputs-and-context.md)), `stale_outputs` and owner speaker names ([ADR 0038](adr/0038-meeting-speaker-identification.md)), `meetings.sensitivity` / `project_scope` | Outputs are plain text built from owner names and corrections |
| Decisions and actions | Phase 31 items (`meeting_analysis`): actions are `accepted` only when the owner confirmed them; decisions are `noted` (never individually confirmed) | [phase-31](phase-31.md) |
| Calendar attendee metadata | ICS feed `EventFacts.attendees` (in memory, never returned by an API today) | Only a narrow, explicit suggestion lookup is added |
| Owner session, CSRF, bearer | hub `operator.py` proxies; core service token | Same trust boundary as every other owner route |
| Mailpit | `axllent/mailpit` | Real SMTP target for automated tests |

### Limitations found (what the current code cannot do)

1. **The sender is not MIME.** `smtp_send` concatenates `From:/To:/Subject:` and the body into a string. There is no `Message-ID`, no `Date`, no attachments, one recipient only, no Cc/Bcc. **It also does not sanitise header values**: a `\r\n` in `to` or `subject` would inject headers. The conversational draft path accepts free text for both. The new sender builds messages with the stdlib `email` package under `policy.SMTP` (which rejects newlines in headers) and validates addresses first.
2. **No claim, no failure state.** `dispatch_due_drafts` lists due drafts, sends, then marks them sent. Two workers (or a restart mid-send) can send twice; an exception leaves the draft `QUEUED` so it is retried forever, and a timeout after the server accepted the message is indistinguishable from a refusal. There is no `FAILED`, no attempt count, no error text.
3. **One address, no approval binding.** Approval is a status flip on a draft id; editing the body of an approved draft is not possible today, so nothing proves what was approved is what is sent.
4. **No sender identity control.** `SMTP_FROM` is an environment string; nothing checks it matches the authenticated account, and there is no verify/disconnect/rotate/disable, no UI, and no master switch.
5. **No attachment storage.** Nothing persists or hashes a file for a draft.
6. **Phase 54 effects.** `Meeting.stale_outputs` already tells when a summary or minutes predates the current speaker names; the package must refuse stale outputs rather than mail wrong attributions.

### Minimum changes (Stage A conclusion)

- Extend `EmailDraft`/`email_drafts` (additive, migration 036) instead of a second outbox, so there is still exactly **one dispatch loop and one sender**; add attachment rows, an event log, a one-row sender config and saved recipient groups.
- Replace the string message with a stdlib MIME builder; reject unsafe addresses and header injection for **every** draft, including the older conversational ones.
- Make the loop claim atomically (`FOR UPDATE SKIP LOCKED`), classify outcomes, bound retries, and move ambiguous results to `UNKNOWN_DELIVERY`.
- Bind approval to a hash of the exact package; any change returns it to review.
- Keep the text-only consent contract: approve and queue are owner-session HTTP routes with `require_text(TEXT)`; the older conversational handlers are restricted to plain text drafts so a meeting package can never be approved or queued from voice or chat.

### PDF attachments (decision)

The consent and email contracts stay text-only: a PDF is an attachment of an owner-approved package, produced **at preparation time**, stored with its SHA-256, shown in the preview, covered by the approval hash, and sent byte-for-byte at dispatch (never regenerated). No PDF library is installed and adding one would change the lockfile and every image, so a small deterministic stdlib writer (Courier, WinAnsi) is used; text it cannot encode fails preparation of the PDF with a clear message and the owner can send without it. A richer layout (for example fpdf2) is a later, separate change.

### Gmail transport decision

Gmail SMTP (`smtp.gmail.com:587`, STARTTLS, an app password on a **dedicated** account with 2-Step Verification) is compatible with the existing implementation and needs no new OAuth grant, so it is the implemented path. The read-only Gmail OAuth grant of [ADR 0021](adr/0021-google-accounts.md) is not touched or widened. Gmail rewrites `From` to the authenticated account (or a verified alias), so the configured sender must equal the account. **Alternative if app passwords are unavailable** (Workspace policy): a separate OAuth client and consent with only `https://www.googleapis.com/auth/gmail.send`, bound to the dedicated account, tokens in the SecretStore with ADR 0021's PKCE/state handling, sending through `users.messages.send` with the same MIME bytes. It would be a second, send-only grant, never merged with the read-only one. Not built here.

## What was built (Stages B to G)

| Layer | Where |
|---|---|
| Message construction, address validation, header safety | `companion_core/email/mime.py` (stdlib `email` under `policy.SMTP`) |
| Extended draft, states, package hash | `email/models.py`, `email/store.py`, `email/postgres_store.py` (atomic claim, guarded transitions, attachments, events) |
| Dedicated sender: settings, SecretStore credential, verify, enable, rotate, disconnect | `email/sender_config.py`, `email/sender.py` (`MailSender`: TLS and identity enforcement, typed outcomes) |
| Delivery state machine in the existing loop | `email/workflow.py` (claim, integrity check, bounded retry, unknown delivery, restart recovery) |
| Package content, PDF, recipients, groups, policies | `meeting_distribution/{package,pdf,groups,service,routes}.py` |
| Calendar invitee suggestions | `calendar/feed.py` (`attendees_for`, `owner_emails`): one nearest event, read-only |
| Routes | core `/meeting-email/*` and `/meetings/{id}/email/*` (`shared/protocols/meeting_email_api.py`), hub proxy `reachy_hub/meeting_email.py` (owner session + CSRF, no bearer) |
| Draft request by conversation | `email_intent.match_prepare_minutes` (prepare only); the older send/approve handlers are limited to plain text drafts |
| Web | `features/meetings/ShareMinutes.tsx` (+ hooks), Settings, Accounts: `features/accounts/MailSender.tsx` |
| Android | `ui/ShareMinutesScreen.kt` (in-app PDF preview), `data/MeetingEmail.kt`, `AppViewModel`, `ReachyApi` |
| Storage | migration `036_meeting_email`, `deploy/homelab/rollback-036.sql`; flag `MEETING_EMAIL_ENABLED` (Compose passes it, default false) |

Stage D (recipients): manual entry, saved groups (`meeting_recipient_groups`), suggestions offered unchecked; the complete To/Cc/Bcc list is shown in every review. Stage F (safety): see [ADR 0039](adr/0039-supervised-meeting-minutes-email.md) decisions 3 and 5. Stage G: [verification record](verification/phase-55-meeting-minutes-email-2026-10-14.md).

## Sender test (added 2026-10-14)

Settings > Accounts > Outbound meeting email has a **Send a test email** box: type an address, press the button, and Reachy sends one fixed short message from the dedicated sender to it and reports what happened (sent with the server's reply, failed with the reason, or delivery unknown). Rules and the one exception to the ten-minute window are in the [ADR addendum](adr/0039-supervised-meeting-minutes-email.md#addendum-2026-10-14-the-sender-test). It needs sending to be on, so verify, enable, then test. Core `POST /meeting-email/sender/test`, hub proxy, `MailSender`/`MeetingEmailService.send_test`, web `MailSender.tsx`. Android has no sender setup (web only), so no Android test button.

## Stage H: deployment proposal (nothing below is authorised)

Nothing is deployed, no production credential is configured and no real email has been sent. Production stays at schema `035_meeting_speaker_identity` with no sender until the owner approves each step separately.

1. **Merge** the branch (owner decision).
2. **Backup**: `pg_dump` of the homelab database and `deploy/homelab/.env`; confirm the SecretStore key file (`SECRET_KEY_FILE`) is backed up, because the sender credential is encrypted with it. Read the Phase 48 capture counters first (core token) and save them.
3. **Preserve** the running images (`reachy-rollback/*:pre-036`), build core + hub + coding-agent + migrate together (`SCHEMA_REVISION` moves to `036_meeting_email`), stop the application services, dump, apply the migration job, start them. `MEETING_EMAIL_ENABLED` stays **false** (the default): no route, no service, no sender. Expect about 2 minutes of downtime and a new Phase 48 segment (core restarts).
4. **Smoke** (flag off): revision `036`, the new tables empty, existing meetings, tasks, reminders, documents and calendar answer, `GET /meeting-email/config` answers `{"enabled": false}` through the hub and `/meeting-email/*` is 404.
5. **Enable the feature** (separate approval): set `MEETING_EMAIL_ENABLED=true` in `.env`, recreate **core only**. Still no sender, so nothing can be queued.
6. **Configure the dedicated Gmail account** (separate approval, by the owner in Settings, Accounts, Outbound meeting email): a *dedicated* account with 2-Step Verification and an app password; `smtp.gmail.com`, 587, the account address as sender and username. The password goes through the form once and is never shown again. **Verify** (signs in, sends nothing), then turn sending on.
7. **First UAT**: send only to an owner-controlled test address ([checklist](#uat-checklist)). Widening to real recipients is the owner's decision afterwards.

**Rollback.** *Stop sending at once:* turn the sender off in Settings (or Remove sender, which deletes the credential); messages waiting in the window then fail safely instead of sending. *Feature off:* set `MEETING_EMAIL_ENABLED=false` and recreate core (routes vanish; drafts stay). *Schema:* with the services stopped run `deploy/homelab/rollback-036.sql` in one transaction (it deletes meeting-minutes drafts, attachments, history, the sender settings, the saved groups and the sender's stored credential; **a message already sent stays sent**), tag the `pre-036` images back and start them; the final line must print `035_meeting_speaker_identity`. A sent email cannot be recalled: the ten-minute window is the only undo.

**Keep out of production until separately approved:** the real sender credential, enabling sending, any non-test recipient, scheduled or automatic sending (deferred: the initial release needs the owner's approval for every message).

## UAT checklist

Prerequisite: the deployment above through step 5, a dedicated Gmail account, and an inbox you own for testing. Check each box before widening anything.

1. **Setup and test email.** Settings > Accounts > Outbound meeting email: enter host, port, sender, username, app password; Save. The password field empties and only "A credential is saved." shows. Sending is OFF. Verify connection: it says nothing was sent and your test inbox received nothing. Turn sending on, then type your own test address in **Send a test email** and press the button: one short message arrives from the dedicated account (check spam too), with no meeting content and no attachment; the page shows the server's reply. Pressing it more than five times in an hour is refused. Turn sending off: the test button is disabled. Change any field: sending turns off again.
2. **Wrong credential.** Save a wrong password, Verify: it fails with "authentication failed" and the password is not echoed. Restore the right one.
3. **Prepare.** Open a finished meeting with confirmed speaker names, Share minutes, Prepare message. The body has the right title, date and time zone, participant names, the summary, the confirmed actions only, decisions labelled as not individually confirmed, and **no transcript text and no audio**.
4. **Speaker names.** Rename a speaker (Identify speakers): Share minutes tells you the summary predates the names and refuses to prepare until you write it again. After rewriting, the new name appears.
5. **Recipients.** Add your test address as To; try an invalid address (refused). Add a Cc and a Bcc (your second test address). Nothing is added by suggestions or groups until you choose it. The review lists To, Cc and Bcc in full.
6. **Attachment.** Preview the PDF (web link, Android in-app): it is the minutes. A name with characters the PDF cannot hold reports why and the message can go without it.
7. **Approval.** Approve is disabled until you type SEND and have saved your changes. Edit the subject after approving: it returns to review and must be approved again.
8. **Window and cancel.** Approve and queue; it says when it will be sent. Cancel sending before the time: nothing arrives. Queue again and wait.
9. **Delivery.** The test inbox receives one message: subject, body and PDF match what you approved; the Bcc address received it without appearing in any header; the History shows Prepared, Approved, Queued, Sending, Sent.
10. **Android.** Repeat 3 to 9 on the phone (and rotate or switch apps while a message is queued: it still sends once and the screen catches up).
11. **Failure and unknown.** Turn sending off while a message is queued: it fails with "turned off" and nothing is sent. (If you can, interrupt the network mid-send: the message becomes "Delivery unknown", is not retried, and you can mark it arrived or send it again with a new approval.)
12. **Voice and chat.** Say "Reachy, prepare an email with the minutes of <meeting>": a draft appears with no recipients. Try to approve or send it by voice and by typing in chat: it refuses; only the app's typed approval works.
13. **Disconnect.** Remove sender: the credential is gone, a new send is refused, and the settings show it is not set up.
14. **Sensitive meeting** (if you have one): preparing needs the explicit acknowledgement.
