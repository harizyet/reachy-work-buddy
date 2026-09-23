"""Provider reads compose with local stores; local write methods stay local."""
from datetime import timedelta

from companion_core.accounts.provider import AccountError
from companion_core.calendar.models import CalendarEvent
from companion_core.email.models import EmailMessage


async def enabled(service, cap):
    status = await service.execute("status")
    if "error" in status:
        raise AccountError(status["error"])
    return status["capabilities"][cap]["enabled"]


async def checked(service, action, payload=None):
    result = await service.execute(action, payload)
    if "error" in result:
        raise AccountError(result["error"])
    return result


class AccountCalendar:
    def __init__(self, local, service):
        self.local, self.service = local, service

    async def add_event(self, event):
        if event.id.startswith("google:"):
            raise AccountError("provider_records_are_read_only")
        return await self.local.add_event(event)

    async def list_events(self, start, end):
        local = await self.local.list_events(start, end)
        if not await enabled(self.service, "calendar"):
            return local
        result = await checked(self.service, "events", {"start": start, "end": end})
        return sorted(local + [CalendarEvent.model_validate(e) for e in result["events"]],
                      key=lambda e: e.start)

    async def next_event(self, now):
        events = await self.list_events(now, now + timedelta(days=31))
        return next((event for event in events if event.start >= now), None)

    async def close(self):
        await self.local.close()


class AccountEmail:
    def __init__(self, local, service):
        self.local, self.service = local, service

    def __getattr__(self, name):
        # Local draft/consent/dispatch operations are never forwarded to Google.
        return getattr(self.local, name)

    async def list_received(self):
        local = await self.local.list_received()
        if not await enabled(self.service, "gmail"):
            return local
        result = await checked(self.service, "messages", {"query": "newer_than:1d"})
        return local + [EmailMessage.model_validate(m) for m in result["messages"]]
