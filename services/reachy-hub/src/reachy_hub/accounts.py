"""Owner-only transport for core accounts; handles the Strict-cookie OAuth return."""
import os
import secrets
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from reachy_hub.operator import require_csrf
from shared.models.accounts import AccountConfigPatch, CalendarSelection, ConnectAccount
from shared.protocols import accounts as paths


def install_accounts(app, core, *, enabled):
    async def owner(request: Request):
        username = await app.state.user_store.owner() if getattr(app.state, "user_store", None) else None
        if not enabled:
            raise HTTPException(503, "Account setup is not enabled on this installation")
        if not username or request.scope.get("session", {}).get("user") != username:
            raise HTTPException(401, "Login required")
        if request.method not in {"GET", "HEAD"}:
            require_csrf(request)

    app.state.require_account_owner = owner

    async def proxy(method, path, *, data=None, params=None):
        try:
            return await core.accounts_request(method, path, data=data, params=params)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            # Core emits fixed public codes, never raw provider errors.
            if code == 422:
                raise HTTPException(422, "Invalid connection setup or request") from None
            if code == 400:
                raise HTTPException(400, exc.response.json().get("detail", "Account request failed")) from None
            raise HTTPException(502, "Account service unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Account service unavailable") from None

    dependencies = [Depends(owner)]

    @app.get(paths.ACCOUNTS, dependencies=dependencies)
    async def status():
        return await proxy("GET", paths.ACCOUNTS)

    @app.put(paths.CONFIGURE, dependencies=dependencies)
    async def configure(body: AccountConfigPatch):
        result = await proxy("PUT", paths.CONFIGURE, data=body.model_dump(exclude_unset=True))
        await app.state.notification_queue.clear_for_user(os.environ.get("OWNER_USER_ID", "default-user"))
        return result

    @app.post(paths.CONNECT, dependencies=dependencies)
    async def connect(body: ConnectAccount):
        from fastapi.responses import JSONResponse
        binding = secrets.token_urlsafe(32)
        result = await proxy("POST", paths.CONNECT, data={**body.model_dump(), "binding": binding})
        callback = urlsplit(result.pop("redirect_uri"))
        response = JSONResponse(result)
        response.set_cookie(paths.BINDING_COOKIE, binding, max_age=600, httponly=True,
                            secure=callback.scheme == "https", samesite="lax",
                            path=callback.path.removesuffix("/callback"))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get(paths.ACCOUNTS_CALLBACK)
    async def callback(request: Request, state: str = Query("", max_length=256),
                       code: str | None = Query(None, max_length=4096),
                       error: str | None = Query(None, max_length=256)):
        # No owner cookie expected on Google's cross-site redirect.
        binding = request.cookies.get(paths.BINDING_COOKIE)
        if not enabled or not binding or not state:
            return HTMLResponse("Authorization expired. Return to Accounts and try Connect again.",
                                status_code=400, headers={"Cache-Control": "no-store",
                                                         "Referrer-Policy": "no-referrer"})
        await proxy("POST", paths.ACCOUNTS_CALLBACK,
                    data={"state": state, "binding": binding, "code": code, "error": error})
        # Relative location preserves direct /ui and Caddy /hub/ui mounts.
        return RedirectResponse("../../../ui/?google=return", status_code=303,
                                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @app.post(paths.COMPLETE, dependencies=dependencies)
    async def complete(request: Request):
        binding = request.cookies.get(paths.BINDING_COOKIE, "")
        if not binding:
            raise HTTPException(400, "Authorization expired; connect again")
        from fastapi.responses import JSONResponse
        result = await proxy("POST", paths.COMPLETE, data={"binding": binding})
        response = JSONResponse(result)
        response.delete_cookie(paths.BINDING_COOKIE,
                               path=urlsplit(result["redirect_uri"]).path.removesuffix("/callback"))
        return response

    @app.post(paths.TEST, dependencies=dependencies)
    async def test(body: ConnectAccount):
        return await proxy("POST", paths.TEST, data=body.model_dump())

    @app.post(paths.DISCONNECT, dependencies=dependencies)
    async def disconnect():
        result = await proxy("POST", paths.DISCONNECT)
        await app.state.notification_queue.clear_for_user(os.environ.get("OWNER_USER_ID", "default-user"))
        return result

    @app.get(paths.CALENDARS, dependencies=dependencies)
    async def calendars():
        return await proxy("GET", paths.CALENDARS)

    @app.put(paths.SELECTION, dependencies=dependencies)
    async def selection(body: CalendarSelection):
        return await proxy("PUT", paths.SELECTION, data=body.model_dump())

    @app.get(paths.EVENTS, dependencies=dependencies)
    async def events(start: str, end: str):
        return await proxy("GET", paths.EVENTS, params={"start": start, "end": end})

    @app.get(paths.FREE_BUSY, dependencies=dependencies)
    async def free_busy(start: str, end: str):
        return await proxy("GET", paths.FREE_BUSY, params={"start": start, "end": end})

    @app.get(paths.MESSAGES, dependencies=dependencies)
    async def messages(query: str = Query("", max_length=512)):
        return await proxy("GET", paths.MESSAGES, params={"query": query})

    @app.get(paths.MESSAGE, dependencies=dependencies)
    async def message(message_id: str):
        from urllib.parse import quote
        return await proxy("GET", paths.MESSAGE.format(message_id=quote(message_id, safe="")))
