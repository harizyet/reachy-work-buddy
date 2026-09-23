"""Bounded Google HTTP adapter. Only OAuth uses POST; work data is GET-only."""
import asyncio
import base64
from datetime import UTC, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx


class AccountError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class GoogleProvider:
    def __init__(self, transport=None):
        self.transport = transport

    async def request(self, method, url, *, token=None, data=None, params=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=10, follow_redirects=False,
            ) as client:
                for attempt in range(3):
                    async with client.stream(method, url, headers=headers, data=data, params=params) as resp:
                        if resp.status_code in {429, 500, 502, 503, 504}:
                            if attempt == 2:
                                raise AccountError("temporarily_unavailable")
                            await asyncio.sleep(0.25 * (2 ** attempt))
                            continue
                        if resp.status_code == 401:
                            raise AccountError("reconnect_required")
                        if resp.status_code == 403:
                            raise AccountError("permission_denied")
                        raw = bytearray()
                        async for chunk in resp.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 2_000_000:
                                raise AccountError("response_too_large")
                        import json
                        result = json.loads(raw) if raw else {}
                        if not 200 <= resp.status_code < 300:
                            raise AccountError("reconnect_required" if result.get("error") == "invalid_grant"
                                               else "provider_request_failed")
                        if not isinstance(result, dict):
                            raise AccountError("invalid_provider_response")
                        return result
        except (httpx.HTTPError, ValueError, TypeError):
            raise AccountError("temporarily_unavailable") from None

    async def token(self, data):
        result = await self.request("POST", "https://oauth2.googleapis.com/token", data=data)
        try:
            if not isinstance(result.get("access_token"), str) or not result["access_token"]:
                raise ValueError("access token")
            result["expires_in"] = int(result.get("expires_in", 3600))
            if not 0 < result["expires_in"] <= 86400:
                raise ValueError("expiry")
            if "scope" in result and not isinstance(result["scope"], str):
                raise TypeError("scope")
            if "refresh_token" in result and not isinstance(result["refresh_token"], str):
                raise TypeError("refresh token")
        except (ValueError, TypeError):
            raise AccountError("invalid_provider_response") from None
        return result

    async def identity(self, token):
        value = await self.request("GET", "https://openidconnect.googleapis.com/v1/userinfo", token=token)
        if not value.get("sub") or not value.get("email") or value.get("email_verified") is not True:
            raise AccountError("identity_unverified")
        return {"subject": value["sub"], "email": value["email"]}

    async def revoke(self, token):
        await self.request("POST", "https://oauth2.googleapis.com/revoke", data={"token": token})

    async def pages(self, url, token, params, key, *, max_pages=5, allow_partial=False):
        rows = []
        seen = set()
        for _ in range(max_pages):
            value = await self.request("GET", url, token=token, params=params)
            rows.extend(value.get(key, []))
            cursor = value.get("nextPageToken")
            if not cursor:
                return rows
            if cursor in seen:
                raise AccountError("invalid_pagination")
            seen.add(cursor)
            params = {**params, "pageToken": cursor}
        if allow_partial:
            return rows
        # Do not misrepresent partial calendars/free-busy as complete.
        raise AccountError("result_limit_exceeded")

    async def calendars(self, token):
        rows = await self.pages("https://www.googleapis.com/calendar/v3/users/me/calendarList",
                                token, {"maxResults": 100}, "items")
        return [{"id": r["id"], "name": r.get("summary", r["id"]),
                 "timezone": r.get("timeZone", "UTC"), "primary": bool(r.get("primary"))}
                for r in rows if not r.get("deleted")]

    async def events(self, token, calendars, start, end):
        events = {}
        occurrences = set()
        for calendar in calendars:
            rows = await self.pages(
                f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar['id'], safe='')}/events",
                token, {"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                        "singleEvents": "true", "orderBy": "startTime", "maxResults": 100}, "items",
            )
            for row in rows:
                if row.get("status") == "cancelled":
                    continue
                def timestamp(value, timezone=calendar["timezone"]):
                    if "dateTime" in value:
                        result = datetime.fromisoformat(value["dateTime"])
                        return result if result.tzinfo else result.replace(tzinfo=ZoneInfo(
                            value.get("timeZone", timezone)))
                    return datetime.fromisoformat(value["date"]).replace(
                        tzinfo=ZoneInfo(timezone))
                try:
                    begin, finish = timestamp(row["start"]), timestamp(row["end"])
                    occurrence = (row.get("iCalUID") or calendar["id"] + ":" + row["id"],
                                  begin.astimezone(UTC).isoformat())
                    if occurrence in occurrences:
                        continue
                    occurrences.add(occurrence)
                    event_id = "google:" + calendar["id"] + ":" + row["id"]
                    events[event_id] = {
                        "id": event_id, "title": row.get("summary", "(Untitled)"),
                        "start": begin.isoformat(), "end": finish.isoformat(),
                        "location": row.get("location"), "provider": "google",
                        "calendar_id": calendar["id"], "all_day": "date" in row["start"],
                        "busy": row.get("transparency") != "transparent",
                    }
                except (KeyError, ValueError):
                    raise AccountError("invalid_event") from None
        return sorted(events.values(), key=lambda e: datetime.fromisoformat(e["start"]))

    async def messages(self, token, query=""):
        rows = await self.pages("https://gmail.googleapis.com/gmail/v1/users/me/messages",
                                token, {"q": query, "maxResults": 20}, "messages", max_pages=3, allow_partial=True)
        return [await self.message(token, row["id"], body=False) for row in rows[:60]]

    async def message(self, token, message_id, *, body=True):
        row = await self.request(
            "GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id, safe='')}",
            token=token, params={"format": "full" if body else "metadata"},
        )
        payload = row.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        def plain(part, depth=0):
            if depth > 10:
                return ""
            if part.get("mimeType") == "text/plain" and not part.get("filename"):
                value = part.get("body", {}).get("data", "")
                try:
                    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode(
                        "utf-8", errors="replace")[:20000]
                except ValueError:
                    return ""
            return "\n".join(plain(p, depth + 1) for p in part.get("parts", [])[:50])[:20000]
        return {
            "id": "google:" + row["id"], "provider": "google",
            "sender": headers.get("from", ""), "subject": headers.get("subject", "(No subject)"),
            "received_at": datetime.fromtimestamp(int(row["internalDate"]) / 1000,
                                                  tz=ZoneInfo("UTC")).isoformat(),
            "body": plain(payload) if body else "",
            "snippet": row.get("snippet", "")[:2000],
        }
