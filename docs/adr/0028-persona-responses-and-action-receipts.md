# ADR 0028: Persona-aware responses and authoritative action receipts

- Status: **Accepted 2026-10-06** for [Phase 39](../phase-39.md).
- Date: 2026-10-06

## Context

The persona tone preset (migration 017) only reaches the generic LLM branch. The deterministic handlers (alarms, tasks, reminders, memory) answer with fixed strings, so "cheery" or "formal" is ignored exactly where the assistant confirms an action. The obvious fix, routing every reply through the LLM, would let model wording stand in for what actually happened.

## Decision

1. **System truth is a structured receipt, not prose.** When a deterministic handler changes state it records an `ActionReceipt` (`shared/models/receipt.py`): action type, status, time, source channel, object type/id, display fields, optional failure reason, and a `notify` flag with a claim-once `notified_at`. The receipt is built from the persisted object, never from reply wording. Failing to record a receipt must not undo or hide the action.
2. **Wording is a renderer over facts.** Simple acknowledgements (response class B) use per-tone templates in `companion_core/persona/render.py`. The `default` tone is the original wording, so an unset persona is unchanged. No model call: no latency and no way to alter a fact.
3. **Protocol, security and consent replies stay fixed (class A).** Confirmation prompts, destructive-action gates, privacy and command errors are not tone-rendered. The LLM has no authority over any action gate (ADR 0011, 0018).
4. **Telegram and the web read the same receipts.** The hub loop claims `GET /receipts/pending` once and pushes the receipt text (built from the structured fields only). The operator UI Activity tab lists `GET /receipts` read-only.
5. **Creation and delivery are separate receipts.** Setting an alarm records `alarm.created`; `alarm.delivered` is recorded from the hub's delivery report (`POST /alarms/{id}/delivery`) and is `failed` unless the robot actually played it.
6. **No echo into the same chat.** A receipt is flagged `notify` only for non-Telegram, non-slash-command turns (voice/web natural language); a Telegram turn already has its reply in Telegram. Delivery receipts notify only when played or stopped, since failures already produce the hub's Telegram fallback.
7. **Memory receipts carry no memory content**, only the sensitivity label.

## Consequences

- One new table (migration 018) and three planner-store methods; additive.
- The LLM verbalizer for richer replies (class C) is not part of this decision's first delivery; it must keep the invariant: the LLM may describe system truth, never define it, with the deterministic text as fallback.
- Receipts grow without a retention policy yet; `GET /receipts` is capped at 500.
