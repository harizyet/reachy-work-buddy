import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Query, Request

from shared.models.accounts import (
    AccountConfigPatch,
    CalendarSelection,
    ConnectAccount,
    DesktopComplete,
    OAuthCallback,
    OAuthComplete,
    OAuthStart,
)
from shared.protocols import accounts as paths


def install_accounts(app, service_token):
    async def require_service(request: Request):
        incoming = request.headers.get(paths.SERVICE_HEADER, "")
        if not service_token or not secrets.compare_digest(incoming, service_token):
            raise HTTPException(401, "Service authentication required")
        if not getattr(app.state, "accounts", None):
            raise HTTPException(503, "Accounts unavailable")

    dependencies = [Depends(require_service)]

    async def call(action, payload=None):
        result = await app.state.accounts.execute(action, payload)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result

    @app.get(paths.ACCOUNTS, dependencies=dependencies)
    async def status():
        return await call("status")

    @app.put(paths.CONFIGURE, dependencies=dependencies)
    async def configure(body: AccountConfigPatch):
        result = await call("configure", body.model_dump(exclude_unset=True))
        app.state.conversation_store.clear()
        return result

    @app.post(paths.CONNECT, dependencies=dependencies)
    async def connect(body: OAuthStart):
        return await call("connect", body.model_dump())

    @app.post(paths.ACCOUNTS_CALLBACK, dependencies=dependencies)
    async def callback(body: OAuthCallback):
        return await call("callback", body.model_dump())

    @app.post(paths.COMPLETE, dependencies=dependencies)
    async def complete(body: OAuthComplete):
        return await call("complete", body.model_dump())

    @app.post(paths.DESKTOP_START, dependencies=dependencies)
    async def desktop_start(body: OAuthStart):
        return await call("desktop_start", body.model_dump())

    @app.post(paths.DESKTOP_COMPLETE, dependencies=dependencies)
    async def desktop_complete(body: DesktopComplete):
        return await call("desktop_complete", body.model_dump())

    @app.post(paths.TEST, dependencies=dependencies)
    async def test(body: ConnectAccount):
        return await call("test", body.model_dump())

    @app.post(paths.DISCONNECT, dependencies=dependencies)
    async def disconnect():
        result = await app.state.accounts.disconnect()
        app.state.conversation_store.clear()
        return result

    @app.get(paths.CALENDARS, dependencies=dependencies)
    async def calendars():
        return await call("calendars")

    @app.put(paths.SELECTION, dependencies=dependencies)
    async def selection(body: CalendarSelection):
        return await call("selection", body.model_dump())

    @app.get(paths.EVENTS, dependencies=dependencies)
    async def events(start: datetime, end: datetime):
        return await call("events", {"start": start, "end": end})

    @app.get(paths.FREE_BUSY, dependencies=dependencies)
    async def free_busy(start: datetime, end: datetime):
        result = await call("events", {"start": start, "end": end})
        return {"busy": [{"start": e["start"], "end": e["end"]} for e in result["events"] if e["busy"]]}

    @app.get(paths.MESSAGES, dependencies=dependencies)
    async def messages(query: str = Query("", max_length=512)):
        return await call("messages", {"query": query})

    @app.get(paths.MESSAGE, dependencies=dependencies)
    async def message(message_id: str):
        return await call("message", {"id": message_id})
