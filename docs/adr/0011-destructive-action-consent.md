# ADR 0011: Destructive-Action Consent, Voice-Exclusion, and Delayed Send

- Status: Accepted
- Date: 2026-09-22

## Context

Explicit user instruction, delivered ahead of Phase 15 (not itself a
numbered phase in docs/plan.md's roadmap): before adding support for real
external accounts (Gmail, Outlook, or any future live calendar/email
provider), this codebase needs a hard, structural safety mechanism, not a
convention or a prompt instruction to an eventual LLM. Summarized
requirements, as given:

- Interactions with real external accounts (once they exist) must be
  read-only by default.
- Any request to delete something (an appointment, an email) must be
  confirmed from a text platform (Telegram or similar) — never voice.
- Voice input must never be able to provide consent for a destructive
  action, because it is not considered secure (ambient, unauthenticated,
  easy to mishear or spoof).
- Only textual confirmation is permitted for destructive actions.
- This must be built into the system by design, not left to an LLM's
  judgment — "LLMs should not have any capability to perform destructive
  actions without hard consent."
- Sent email should have a delay (10 minutes) so a send can be undone
  before it actually goes out.
- Any action performed should always be undoable.
- Bulk/mass-destructive actions (e.g. "delete the whole mailbox") must
  always be blocked outright — there is no scenario where that should be
  allowed to proceed, confirmed or not.

At the time this ADR was written, no Gmail/Outlook/real-calendar connector
exists yet — `CalendarStore` and `EmailStore` (ADR 0010, Phase 14) are both
local, Postgres-backed, with no external write capability. The only
destructive (permanently-effect) capability that existed anywhere in this
codebase was `MemoryStore.forget()`. This ADR is deliberately written to
generalize past that one capability, since the explicit ask is for a
mechanism, not a one-off fix.

## Decisions

**Two hard rules, enforced in one place (`companion_core/consent/gate.py`),
not scattered per-feature.** `request_confirmation` refuses
`ActionScope.BULK` unconditionally — no row is ever created, so there is
no confirmation for anything to approve, by voice, by text, or otherwise.
`confirm_action`/`require_text` refuse `InputModality.VOICE`
unconditionally — a destructive action can never be authorized by
anything that arrived as spoken audio, regardless of what it transcribed
to. These are structural guarantees (direct unit tests exist proving both:
`test_consent_gate.py`), not conventions a future feature has to remember
to follow — but every destructive/consequential code path in this
codebase *does* have to actually call through this gate for the guarantee
to hold for that feature. A future connector that talks to a destructive
store method directly, bypassing the gate, would defeat this; code review
of any future destructive tool should check for that specifically.

**`InputModality` is threaded end to end, separately from `Channel`.**
`Channel` answers "which client/device" (reachy, telegram, web, phone);
`InputModality` answers "was this typed or spoken," which is a security
signal, not an identity one — voice input on the Reachy channel and a
hypothetical future typed-on-Reachy-touchscreen message would share
`channel=reachy` but must be told apart here. Only `POST /voice/turn`
(real STT transcription, in reachy-hub) ever produces `VOICE`; every other
path — `POST /messages`, the Telegram poll loop — defaults to `TEXT`. The
field travels `InboundMessage` (reachy-hub) -> `handle_inbound_message` ->
`CompanionCoreClient.send_turn` -> companion-core's
`ConversationTurnRequest`. reachy-hub does no enforcement of the two hard
rules itself; it only has to not lose the signal in transit. companion-core
enforces, since that's where every destructive tool/store lives (ADR
0001).

**Memory forgetting became this codebase's first real user of the gate,
and a soft delete.** "forget X" only *requests* a confirmation
(`memory.forget`, `SINGLE` scope — recalling a query and taking the first
match is inherently single-item, never bulk); "yes forget X" is the only
thing that actually calls `MemoryStore.forget()`, and only after
`confirm_action` has verified the confirming turn wasn't voice.
`MemoryRecord.forgotten_at` makes forgetting reversible — `recall`/
`list_memories`/`get` all treat a forgotten record the same way they
already treat an expired one (invisible, not gone), and `restore()` clears
the flag. "restore X" (and the `POST /memories/{id}/restore` API) is
**not** gated behind any confirmation and accepts any input modality,
including voice — undoing must never be harder than the destructive action
it reverses, or "always be able to be undone" becomes a promise with a
catch.

**Email send became delay-queued, and approval/send-triggering became
text-only.** "send draft X" no longer dispatches immediately even once
approved — it moves the draft to a new `QUEUED` status with `dispatch_at`
~10 minutes out (`email/workflow.py`'s `queue_draft_for_sending`); a
background loop (`run_dispatch_loop`, started from `create_app`'s
lifespan, same pattern as reachy-hub's heartbeat loop) is the *only* code
that actually calls an `EmailSender`, and only for what `EmailStore.list_due`
says has passed its `dispatch_at`. "cancel send X" (and
`POST /emails/drafts/{id}/cancel-send`) reverts `QUEUED` back to
`APPROVED`, clearing `dispatch_at` — again, not gated, any modality, since
cancelling is the safe direction. Both "approve draft X" and the
"send draft X" trigger call `require_text` first and refuse voice, on the
reasoning that authorizing an outbound communication is exactly the kind
of consequential, hard-to-fully-reverse action (once actually sent, it's
sent) this ADR's rules are meant to cover, even though the user's own
examples were phrased around *deletion* specifically — a deliberately
broader reading, called out here so it's reviewable rather than assumed.

**Read-only-by-default for future external accounts is a rule for
whichever phase adds them, not code written now.** No Gmail/Outlook/real-
calendar connector exists in this codebase yet, so there is nothing to
refactor into read-only-by-default today. The binding rule this ADR
establishes: when such a connector is added, its write-capable methods
(delete, send, modify) MUST route through `companion_core/consent/gate.py`
exactly as `memory.forget` and email-send do here — request_confirmation,
text-only confirm, no bulk path — and MUST default every account
connection to read-only until that specific capability is deliberately
wired through the gate. Because gating happens at the app.py/workflow
layer calling store methods, not inside store implementations, any future
store that implements `CalendarStore`/`EmailStore` (a `GmailEmailStore`,
say) automatically inherits this — provided its write methods are only
ever invoked through the same gated call sites, not through some new,
ungated shortcut.

**Direct API confirmation endpoints assume `InputModality.TEXT`, not a
caller-supplied claim.** `POST /memories/{id}/forget/confirm` and the
email approve/send endpoints call `require_text`/`confirm_action` with a
hardcoded `InputModality.TEXT`, on the reasoning that only `/voice/turn`'s
transcribed conversational path can ever produce `VOICE`, and a direct
HTTP call to these endpoints is by construction not that. This is an
assumption, not a proof; if a future voice-capable direct-API client ever
existed, it would need to actually pass its modality through rather than
have it assumed, and this comment is left in the code specifically so that
assumption doesn't silently stop holding unnoticed.

## Consequences

- `shared/models/session.py` gained `InputModality`; `ConversationTurnRequest`
  (companion-core), `InboundMessage`/`MessageResponse` (reachy-hub), and
  `CompanionCoreClient.send_turn` all carry it now.
- `MemoryRecord` gained `forgotten_at`; `EmailDraft` gained `dispatch_at`
  and two new statuses (`QUEUED`, `CANCELLED`). Both Postgres migrations
  are additive columns on existing tables (see the "Known limitation" note
  in `deploy/homelab/README.md` about these being `CREATE TABLE IF NOT
  EXISTS`, not real migrations — an existing deployed table predating this
  ADR needs a manual `ALTER TABLE ... ADD COLUMN` before upgrading, since
  there's no migration tool yet).
- `companion_core/consent/` is a new module (`models.py`, `store.py`,
  `postgres_store.py`, `gate.py`) with its own Postgres table
  (`confirmation_requests`).
- `DELETE /memories/{memory_id}` no longer exists — replaced by
  `POST /memories/{id}/request-forget`, `POST /memories/{id}/forget/confirm`,
  and `POST /memories/{id}/restore`. This is a breaking API change; nothing
  in this codebase's own web/PWA client exists yet to be affected by it
  (`clients/web-pwa/` is unimplemented per the root README), so no other
  service needed updating.
- `POST /emails/drafts/{id}/send` now returns a `QUEUED` draft, not `SENT`
  — any caller that assumed synchronous send (there were none inside this
  codebase; Phase 14's own tests were updated) needs to poll
  `GET /emails/drafts` or wait for the dispatch loop.
- `deploy/homelab`'s `companion-core` service needs no new environment
  variables for this — `EMAIL_SEND_DELAY_SECONDS`-equivalent behavior is a
  `create_app()` constructor parameter (`email_send_delay_seconds`,
  default 600), not read from the environment, since nothing yet needs it
  configurable per-deployment.
