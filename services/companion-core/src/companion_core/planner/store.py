"""Note and reminder storage. Single owner, not scoped per user (same
precedent as tasks)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from companion_core.planner.models import (
    Alarm,
    AlarmStatus,
    Note,
    Reminder,
    ReminderStatus,
    Station,
)


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
    async def list_alarms(self) -> list[Alarm]: ...
    async def add_alarm(
        self,
        label: str,
        due_at: datetime,
        *,
        reminder_id: str | None = None,
        station_id: str | None = None,
        volume: int = 100,
    ) -> Alarm: ...
    async def cancel_alarm(self, alarm_id: str) -> Alarm | None: ...
    async def claim_due_alarms(self, now: datetime) -> list[Alarm]: ...
    async def record_alarm_delivery(self, alarm_id: str, delivery: str) -> Alarm | None: ...
    async def list_stations(self) -> list[Station]: ...
    async def add_station(self, name: str, guide_id: str) -> Station: ...
    async def delete_station(self, station_id: str) -> bool: ...


class InMemoryPlannerStore:
    def __init__(self) -> None:
        self._notes: dict[str, Note] = {}
        self._reminders: dict[str, Reminder] = {}
        self._alarms: dict[str, Alarm] = {}
        self._stations: dict[str, Station] = {}

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

    async def list_alarms(self) -> list[Alarm]:
        return sorted(self._alarms.values(), key=lambda a: a.due_at)

    async def add_alarm(
        self,
        label: str,
        due_at: datetime,
        *,
        reminder_id: str | None = None,
        station_id: str | None = None,
        volume: int = 100,
    ) -> Alarm:
        alarm = Alarm(label=label, due_at=due_at, reminder_id=reminder_id, station_id=station_id, volume=volume)
        self._alarms[alarm.id] = alarm
        return alarm

    async def cancel_alarm(self, alarm_id: str) -> Alarm | None:
        alarm = self._alarms.get(alarm_id)
        if alarm is None:
            return None
        if alarm.status is AlarmStatus.SCHEDULED:
            alarm.status = AlarmStatus.CANCELLED
        return alarm

    async def claim_due_alarms(self, now: datetime) -> list[Alarm]:
        due = [a for a in self._alarms.values() if a.status is AlarmStatus.SCHEDULED and a.due_at <= now]
        for alarm in due:
            alarm.status, alarm.fired_at = AlarmStatus.FIRED, now
        return sorted(due, key=lambda a: a.due_at)

    async def record_alarm_delivery(self, alarm_id: str, delivery: str) -> Alarm | None:
        alarm = self._alarms.get(alarm_id)
        if alarm is None:
            return None
        alarm.delivery = delivery
        return alarm

    async def list_stations(self) -> list[Station]:
        return sorted(self._stations.values(), key=lambda st: (st.name.lower(), st.created_at))

    async def add_station(self, name: str, guide_id: str) -> Station:
        for existing in self._stations.values():
            if existing.guide_id == guide_id:
                return existing
        station = Station(name=name, guide_id=guide_id)
        self._stations[station.id] = station
        return station

    async def delete_station(self, station_id: str) -> bool:
        return self._stations.pop(station_id, None) is not None
