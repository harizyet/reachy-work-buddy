"""Postgres-backed PlannerStore. See store.py for the interface."""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from companion_core.planner.models import (
    Alarm,
    AlarmStatus,
    Note,
    Reminder,
    ReminderStatus,
    Station,
)
from shared.database import check_schema
from shared.models.receipt import ActionReceipt
from shared.models.response import Privacy

_NOTE_COLUMNS = "id, title, body, created_at, updated_at, sensitivity, project_scope"
_REMINDER_COLUMNS = "id, text, due_at, status, created_at, completed_at, notified_at, sensitivity"


def _note(row: tuple) -> Note:
    return Note(
        id=row[0], title=row[1], body=row[2], created_at=row[3], updated_at=row[4],
        sensitivity=Privacy(row[5]), project_scope=row[6],
    )


def _reminder(row: tuple) -> Reminder:
    return Reminder(
        id=row[0],
        text=row[1],
        due_at=row[2],
        status=ReminderStatus(row[3]),
        created_at=row[4],
        completed_at=row[5],
        notified_at=row[6],
        sensitivity=Privacy(row[7]),
    )

_ALARM_COLUMNS = "id, label, due_at, reminder_id, station_id, status, created_at, fired_at, delivery, volume, repeat, enabled"


def _alarm(row: tuple) -> Alarm:
    return Alarm(
        id=row[0],
        label=row[1],
        due_at=row[2],
        reminder_id=row[3],
        station_id=row[4],
        status=AlarmStatus(row[5]),
        created_at=row[6],
        fired_at=row[7],
        delivery=row[8],
        volume=row[9],
        repeat=list(row[10] or []),
        enabled=row[11],
    )

_RECEIPT_COLUMNS = (
    "id, action_type, status, at, source_channel, object_type, object_id, fields, failure_reason, notify, notified_at"
)


def _receipt(row: tuple) -> ActionReceipt:
    return ActionReceipt(
        id=row[0], action_type=row[1], status=row[2], at=row[3], source_channel=row[4], object_type=row[5],
        object_id=row[6], fields=row[7], failure_reason=row[8], notify=row[9], notified_at=row[10],
    )


_STATION_COLUMNS = "id, name, guide_id, created_at"


def _station(row: tuple) -> Station:
    return Station(id=row[0], name=row[1], guide_id=row[2], created_at=row[3])


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class PostgresPlannerStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresPlannerStore:
        pool = AsyncConnectionPool(dsn, open=False)
        await pool.open()
        store = cls(pool)
        async with pool.connection() as conn:
            await check_schema(conn)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def list_notes(self, query: str | None = None) -> list[Note]:
        async with self._pool.connection() as conn:
            if query:
                cur = await conn.execute(
                    f"SELECT {_NOTE_COLUMNS} FROM notes WHERE title ILIKE %s OR body ILIKE %s "
                    "ORDER BY updated_at DESC",
                    (_like(query), _like(query)),
                )
            else:
                cur = await conn.execute(
                    f"SELECT {_NOTE_COLUMNS} FROM notes ORDER BY updated_at DESC"
                )
            return [_note(row) for row in await cur.fetchall()]

    async def get_note(self, note_id: str) -> Note | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_NOTE_COLUMNS} FROM notes WHERE id = %s", (note_id,))
            row = await cur.fetchone()
            return _note(row) if row else None

    async def get_reminder(self, reminder_id: str) -> Reminder | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_REMINDER_COLUMNS} FROM reminders WHERE id = %s", (reminder_id,))
            row = await cur.fetchone()
            return _reminder(row) if row else None

    async def add_note(
        self, title: str, body: str, *, sensitivity: Privacy = Privacy.WORK_PRIVATE, project_scope: str | None = None
    ) -> Note:
        note = Note(title=title, body=body, sensitivity=sensitivity, project_scope=project_scope)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO notes ({_NOTE_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    note.id, note.title, note.body, note.created_at, note.updated_at,
                    note.sensitivity.value, note.project_scope,
                ),
            )
        return note

    async def update_note(self, note_id: str, title: str, body: str) -> Note | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE notes SET title = %s, body = %s, updated_at = %s WHERE id = %s RETURNING {_NOTE_COLUMNS}",
                (title, body, datetime.now(UTC), note_id),
            )
            row = await cur.fetchone()
            return _note(row) if row else None

    async def delete_note(self, note_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM notes WHERE id = %s", (note_id,))
            return cur.rowcount > 0

    async def list_reminders(self) -> list[Reminder]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_REMINDER_COLUMNS} FROM reminders ORDER BY due_at"
            )
            return [_reminder(row) for row in await cur.fetchall()]

    async def add_reminder(
        self, text: str, due_at: datetime, *, sensitivity: Privacy = Privacy.WORK_PRIVATE
    ) -> Reminder:
        reminder = Reminder(text=text, due_at=due_at, sensitivity=sensitivity)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO reminders ({_REMINDER_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    reminder.id,
                    reminder.text,
                    reminder.due_at,
                    reminder.status.value,
                    reminder.created_at,
                    reminder.completed_at,
                    reminder.notified_at,
                    reminder.sensitivity.value,
                ),
            )
        return reminder

    async def complete_reminder(self, reminder_id: str) -> Reminder | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE reminders SET status = %s, completed_at = %s WHERE id = %s RETURNING {_REMINDER_COLUMNS}",
                (ReminderStatus.DONE.value, datetime.now(UTC), reminder_id),
            )
            row = await cur.fetchone()
            return _reminder(row) if row else None

    async def delete_reminder(self, reminder_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM reminders WHERE id = %s", (reminder_id,)
            )
            return cur.rowcount > 0

    async def claim_due(self, now: datetime) -> list[Reminder]:
        # One UPDATE ... RETURNING claims each reminder exactly once even if
        # two pollers overlap.
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE reminders SET notified_at = %s WHERE status = %s AND notified_at IS NULL "
                f"AND due_at <= %s RETURNING {_REMINDER_COLUMNS}",
                (now, ReminderStatus.PENDING.value, now),
            )
            return sorted(
                (_reminder(row) for row in await cur.fetchall()), key=lambda r: r.due_at
            )

    async def list_alarms(self) -> list[Alarm]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_ALARM_COLUMNS} FROM alarms ORDER BY due_at")
            return [_alarm(row) for row in await cur.fetchall()]

    async def add_alarm(
        self,
        label: str,
        due_at: datetime,
        *,
        reminder_id: str | None = None,
        station_id: str | None = None,
        volume: int = 100,
        repeat: list[int] | None = None,
    ) -> Alarm:
        alarm = Alarm(
            label=label, due_at=due_at, reminder_id=reminder_id, station_id=station_id, volume=volume, repeat=repeat or []
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO alarms ({_ALARM_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    alarm.id,
                    alarm.label,
                    alarm.due_at,
                    alarm.reminder_id,
                    alarm.station_id,
                    alarm.status.value,
                    alarm.created_at,
                    alarm.fired_at,
                    alarm.delivery,
                    alarm.volume,
                    Jsonb(alarm.repeat),
                    alarm.enabled,
                ),
            )
        return alarm

    async def update_alarm(self, alarm_id: str, changes: dict) -> Alarm | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_ALARM_COLUMNS} FROM alarms WHERE id = %s FOR UPDATE", (alarm_id,))
            row = await cur.fetchone()
            if row is None or row[5] == AlarmStatus.CANCELLED.value:
                return _alarm(row) if row else None
            updated = Alarm.model_validate({**_alarm(row).model_dump(), **changes})
            if "due_at" in changes or changes.get("enabled") is True:
                updated.status, updated.fired_at = AlarmStatus.SCHEDULED, None
            await conn.execute(
                "UPDATE alarms SET label = %s, due_at = %s, station_id = %s, status = %s, fired_at = %s, volume = %s, "
                "repeat = %s, enabled = %s WHERE id = %s",
                (updated.label, updated.due_at, updated.station_id, updated.status.value, updated.fired_at,
                 updated.volume, Jsonb(updated.repeat), updated.enabled, alarm_id),
            )
            return updated

    async def rearm_alarm(self, alarm_id: str, due_at: datetime) -> Alarm | None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE alarms SET status = %s, due_at = %s WHERE id = %s AND status = %s AND enabled "
                "AND jsonb_array_length(repeat) > 0",
                (AlarmStatus.SCHEDULED.value, due_at, alarm_id, AlarmStatus.FIRED.value),
            )
            cur = await conn.execute(f"SELECT {_ALARM_COLUMNS} FROM alarms WHERE id = %s", (alarm_id,))
            row = await cur.fetchone()
            return _alarm(row) if row else None

    async def cancel_alarm(self, alarm_id: str) -> Alarm | None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE alarms SET status = %s WHERE id = %s AND status IN (%s, %s)",
                (AlarmStatus.CANCELLED.value, alarm_id, AlarmStatus.SCHEDULED.value, AlarmStatus.FIRED.value),
            )
            cur = await conn.execute(f"SELECT {_ALARM_COLUMNS} FROM alarms WHERE id = %s", (alarm_id,))
            row = await cur.fetchone()
            return _alarm(row) if row else None

    async def claim_due_alarms(self, now: datetime) -> list[Alarm]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE alarms SET status = %s, fired_at = %s, delivery = NULL WHERE status = %s AND enabled AND due_at <= %s "
                f"RETURNING {_ALARM_COLUMNS}",
                (AlarmStatus.FIRED.value, now, AlarmStatus.SCHEDULED.value, now),
            )
            return sorted((_alarm(row) for row in await cur.fetchall()), key=lambda a: a.due_at)

    async def record_alarm_delivery(self, alarm_id: str, delivery: str) -> Alarm | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE alarms SET delivery = %s WHERE id = %s RETURNING {_ALARM_COLUMNS}", (delivery, alarm_id)
            )
            row = await cur.fetchone()
            return _alarm(row) if row else None

    async def list_stations(self) -> list[Station]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_STATION_COLUMNS} FROM stations ORDER BY lower(name), created_at")
            return [_station(row) for row in await cur.fetchall()]

    async def add_station(self, name: str, guide_id: str) -> Station:
        station = Station(name=name, guide_id=guide_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"INSERT INTO stations ({_STATION_COLUMNS}) VALUES (%s, %s, %s, %s) "
                f"ON CONFLICT (guide_id) DO NOTHING RETURNING {_STATION_COLUMNS}",
                (station.id, station.name, station.guide_id, station.created_at),
            )
            row = await cur.fetchone()
            if row is None:
                cur = await conn.execute(f"SELECT {_STATION_COLUMNS} FROM stations WHERE guide_id = %s", (guide_id,))
                row = await cur.fetchone()
            return _station(row)

    async def delete_station(self, station_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM stations WHERE id = %s", (station_id,))
            return cur.rowcount > 0

    async def add_receipt(self, receipt: ActionReceipt) -> ActionReceipt:
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO action_receipts ({_RECEIPT_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    receipt.id, receipt.action_type, receipt.status, receipt.at, receipt.source_channel,
                    receipt.object_type, receipt.object_id, Jsonb(receipt.fields), receipt.failure_reason,
                    receipt.notify, receipt.notified_at,
                ),
            )
        return receipt

    async def list_receipts(self, limit: int = 100) -> list[ActionReceipt]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_RECEIPT_COLUMNS} FROM action_receipts ORDER BY at DESC LIMIT %s", (limit,)
            )
            return [_receipt(row) for row in await cur.fetchall()]

    async def claim_receipts_to_notify(self, now: datetime) -> list[ActionReceipt]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE action_receipts SET notified_at = %s WHERE notify AND notified_at IS NULL "
                f"RETURNING {_RECEIPT_COLUMNS}",
                (now,),
            )
            return sorted((_receipt(row) for row in await cur.fetchall()), key=lambda r: r.at)
