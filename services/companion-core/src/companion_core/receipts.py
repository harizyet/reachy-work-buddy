"""Builds the action receipts (Phase 39, ADR 0028) for deterministic handlers.

Receipts are produced from the persisted object, never from reply wording. A
failure to record one must not undo or hide the action it describes."""

from __future__ import annotations

import logging

from shared.models.receipt import ActionReceipt

log = logging.getLogger(__name__)

# Channels whose reply already reaches the owner in the same chat; an extra
# Telegram receipt there would just duplicate the confirmation.
_NO_ECHO_CHANNELS = frozenset({"telegram"})


def conversation_notify(channel: str, *, explicit_command: bool) -> bool:
    """Telegram receipt for voice/web natural language, not for slash
    commands or Telegram turns (the reply is already in Telegram)."""
    return not explicit_command and channel not in _NO_ECHO_CHANNELS


async def record(store, receipt: ActionReceipt) -> None:
    try:
        await store.add_receipt(receipt)
    except Exception:
        log.exception("could not record action receipt %s", receipt.action_type)


def describe(receipt: ActionReceipt) -> str:
    """Telegram text, built only from the structured fields."""
    titles = {
        "alarm.created": "Alarm set",
        "alarm.cancelled": "Alarm cancelled",
        "alarm.delivered": "Alarm fired",
        "reminder.created": "Reminder set",
        "task.created": "Task added",
        "task.completed": "Task completed",
        "memory.created": "Saved to memory",
    }
    title = titles.get(receipt.action_type, receipt.action_type)
    if receipt.status == "failed":
        title += " (failed)"
    lines = [f"{title}."]
    if receipt.failure_reason:
        lines += ["", f"Reason: {receipt.failure_reason}"]
    if receipt.fields:
        lines.append("")
        lines += [f"{key}: {value}" for key, value in receipt.fields.items()]
    return "\n".join(lines)
