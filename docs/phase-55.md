# Phase 55: Supervised meeting-minutes email through a dedicated Gmail sender

Status: **built on branch `feature/meeting-minutes-email`; not merged, not deployed, no production credential configured, no real email sent.** Decision: [ADR 0039](adr/0039-supervised-meeting-minutes-email.md). Evidence: [verification record](verification/phase-55-meeting-minutes-email-2026-10-14.md).

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
