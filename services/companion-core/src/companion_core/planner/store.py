"""Note and reminder storage. Single owner, not scoped per user (same
precedent as tasks)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from companion_core.planner.models import Note, Reminder, ReminderStatus


class PlannerStore(Protocol):
    async def list_notes(self, query: str | None = None) -> list[Note]: ...
    async def add_note(self, title: str, body: str) -> Note: ...
    async def update_note(self, note_id: str, title: str, body: str) -> Note | None: ...
    async def delete_note(self, note_id: str) -> bool: ...
    async def list_reminders(self) -> list[Reminder]: ...
    async def add_reminder(self, text: str, due_at: datetime) -> Reminder: ...
    async def complete_reminder(self, reminder_id: str) -> Reminder | None: ...
    async def delete_reminder(self, reminder_id: str) -> bool: ...
    async def claim_due(self, now: datetime) -> list[Reminder]: ...


class InMemoryPlannerStore:
    def __init__(self) -> None:
        self._notes: dict[str, Note] = {}
        self._reminders: dict[str, Reminder] = {}

    async def list_notes(self, query: str | None = None) -> list[Note]:
        notes = list(self._notes.values())
        if query:
            lowered = query.lower()
            notes = [
                n
                for n in notes
                if lowered in n.title.lower() or lowered in n.body.lower()
            ]
        return sorted(notes, key=lambda n: n.updated_at, reverse=True)

    async def add_note(self, title: str, body: str) -> Note:
        note = Note(title=title, body=body)
        self._notes[note.id] = note
        return note

    async def update_note(self, note_id: str, title: str, body: str) -> Note | None:
        note = self._notes.get(note_id)
        if note is None:
            return None
        note.title, note.body, note.updated_at = title, body, datetime.now(UTC)
        return note

    async def delete_note(self, note_id: str) -> bool:
        return self._notes.pop(note_id, None) is not None

    async def list_reminders(self) -> list[Reminder]:
        return sorted(self._reminders.values(), key=lambda r: r.due_at)

    async def add_reminder(self, text: str, due_at: datetime) -> Reminder:
        reminder = Reminder(text=text, due_at=due_at)
        self._reminders[reminder.id] = reminder
        return reminder

    async def complete_reminder(self, reminder_id: str) -> Reminder | None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return None
        reminder.status = ReminderStatus.DONE
        reminder.completed_at = datetime.now(UTC)
        return reminder

    async def delete_reminder(self, reminder_id: str) -> bool:
        return self._reminders.pop(reminder_id, None) is not None

    async def claim_due(self, now: datetime) -> list[Reminder]:
        due = [
            r
            for r in self._reminders.values()
            if r.status is ReminderStatus.PENDING
            and r.notified_at is None
            and r.due_at <= now
        ]
        for reminder in due:
            reminder.notified_at = now
        return sorted(due, key=lambda r: r.due_at)
