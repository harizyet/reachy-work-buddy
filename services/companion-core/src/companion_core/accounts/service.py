import asyncio
import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from companion_core.accounts.provider import AccountError, GoogleProvider
from companion_core.secrets import SecretContext, SecretUnavailable

SCOPES = {
    "gmail": {"https://www.googleapis.com/auth/gmail.readonly"},
    "calendar": {"https://www.googleapis.com/auth/calendar.events.readonly",
                 "https://www.googleapis.com/auth/calendar.calendarlist.readonly"},
}
IDENTITY_SCOPES = {"openid", "email"}
CLIENT = SecretContext("owner", "google", "client_secret")
GRANT = SecretContext("owner", "google", "grant")
PENDING = SecretContext("owner", "google", "oauth_pending")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AccountService:
    def __init__(self, repository, provider=None, *, clock=time.time):
        self.repository = repository
        self.provider = provider or GoogleProvider()
        self.clock = clock
        self.cache = {}

    async def execute(self, action, payload=None):
        payload = payload or {}
        try:
            async with asyncio.timeout(45), self.repository.transaction() as tx:
                await self.expire(tx)
                try:
                    async with asyncio.timeout(30):
                        result = await getattr(self, "_" + action)(tx, payload)
                except TimeoutError:
                    # Persist a replacement refresh token even if the subsequent
                    # provider read times out; rolling back would lose that grant.
                    tx.data["health"] = dict.fromkeys(tx.data.get("enabled", []), "temporarily_unavailable")
                    self.cache.clear()
                    result = {"error": "temporarily_unavailable"}
                except AccountError as exc:
                    result = {"error": exc.code}
                except SecretUnavailable:
                    self.cache.clear()
                    tx.data["health"] = dict.fromkeys(tx.data.get("enabled", []), "credential_unavailable")
                    result = {"error": "credential_unavailable"}
            if "_revoke_token" in result:
                token = result.pop("_revoke_token")
                result["revocation"] = "not_available"
                if token:
                    try:
                        async with asyncio.timeout(12):
                            await self.provider.revoke(token)
                        result["revocation"] = "revoked"
                    except (AccountError, TimeoutError):
                        result["revocation"] = "failed_revoke_in_google"
            return result
        except TimeoutError:
            return {"error": "temporarily_unavailable"}

    async def expire(self, tx):
        for flow in list(tx.flows):
            if flow["expires_at"].timestamp() <= self.clock():
                await tx.delete(PENDING, flow["verifier_ref"])
                tx.flows.remove(flow)

    def status(self, data):
        def health(cap):
            value = data.get("health", {}).get(cap, "disconnected")
            last = data.get("last_success", {}).get(cap)
            if value == "connected" and last and self.clock() - datetime.fromisoformat(last).timestamp() > 300:
                return "stale"
            return value
        return {
            "configured": bool(data.get("client_id") and data.get("client_ref") and data.get("redirect_uri")),
            "client_id": data.get("client_id", ""),
            "client_secret": "********" if data.get("client_ref") else None,
            "redirect_uri": data.get("redirect_uri", ""),
            "identity": data.get("identity"),
            "scopes": data.get("scopes", []),
            "selected_calendars": data.get("selected_calendars", []),
            "capabilities": {
                cap: {"enabled": cap in data.get("enabled", []),
                      "status": health(cap),
                      "last_success": data.get("last_success", {}).get(cap)}
                for cap in SCOPES
            },
        }

    async def _status(self, tx, payload):
        return self.status(tx.data)

    async def remove_flows(self, tx):
        for flow in tx.flows:
            await tx.delete(PENDING, flow["verifier_ref"])
        tx.flows.clear()

    async def _configure(self, tx, patch):
        data = tx.data
        changed = any(data.get(key) != patch[key] for key in ("client_id", "redirect_uri"))
        if changed and data.get("grant_ref") and not patch.get("disconnect_existing"):
            raise AccountError("disconnect_required_for_client_change")
        removed = {}
        if changed or patch.get("disconnect_existing"):
            removed = await self._disconnect(tx, {})
        value = patch.get("client_secret")
        if "client_secret" in patch:
            if value:
                data["client_ref"] = await tx.put(CLIENT, value, data.get("client_ref"))
            else:
                await tx.delete(CLIENT, data.pop("client_ref", None))
                if data.get("grant_ref"):
                    removed = await self._disconnect(tx, {})
        elif changed and data.get("client_id") != patch["client_id"]:
            await tx.delete(CLIENT, data.pop("client_ref", None))
        data.update(client_id=patch["client_id"], redirect_uri=patch["redirect_uri"])
        data["generation"] = secrets.token_hex(16)
        await self.remove_flows(tx)
        result = self.status(data)
        if "_revoke_token" in removed:
            result["_revoke_token"] = removed["_revoke_token"]
        return result

    async def _connect(self, tx, payload):
        data = tx.data
        if not self.status(data)["configured"]:
            raise AccountError("setup_required")
        cap = payload["capability"]
        await self.remove_flows(tx)
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(32)
        ref = await tx.put(PENDING, json.dumps({"verifier": verifier}))
        tx.flows.append({
            "state_hash": digest(state), "owner": "owner",
            "binding_hash": digest(payload["binding"]), "capability": cap,
            "generation": data["generation"],
            "expires_at": datetime.fromtimestamp(self.clock(), UTC) + timedelta(minutes=10),
            "verifier_ref": ref, "code_ref": None, "error": None, "returned": False,
        })
        scopes = set(IDENTITY_SCOPES)
        for enabled in set(data.get("enabled", [])) | {cap}:
            scopes |= SCOPES[enabled]
        query = {
            "client_id": data["client_id"], "redirect_uri": data["redirect_uri"],
            "response_type": "code", "access_type": "offline", "prompt": "consent",
            "scope": " ".join(sorted(scopes)), "state": state,
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="),
            "code_challenge_method": "S256",
        }
        if data.get("identity"):
            query["login_hint"] = data["identity"]["email"]
        return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(query),
                "redirect_uri": data["redirect_uri"]}

    async def _callback(self, tx, payload):
        flow = next((f for f in tx.flows if f["state_hash"] == digest(payload["state"])
                     and f["binding_hash"] == digest(payload["binding"])), None)
        if not flow or flow["returned"] or flow["generation"] != tx.data.get("generation"):
            raise AccountError("invalid_or_expired_authorization")
        flow["returned"] = True
        if payload.get("error") or not payload.get("code"):
            flow["error"] = "authorization_cancelled"
        else:
            pending = json.loads(await tx.resolve(PENDING, flow["verifier_ref"]))
            pending["code"] = payload["code"]
            await tx.put(PENDING, json.dumps(pending), flow["verifier_ref"])
        return {"ok": True}

    async def _complete(self, tx, payload):
        flow = next((f for f in tx.flows if f["binding_hash"] == digest(payload["binding"])
                     and f["returned"]), None)
        if not flow or flow["generation"] != tx.data.get("generation"):
            raise AccountError("invalid_or_expired_authorization")
        pending = json.loads(await tx.resolve(PENDING, flow["verifier_ref"]))
        await tx.delete(PENDING, flow["verifier_ref"])
        tx.flows.remove(flow)
        if flow["error"]:
            raise AccountError(flow["error"])
        data = tx.data
        response = await self.provider.token({
            "client_id": data["client_id"], "client_secret": await tx.resolve(CLIENT, data["client_ref"]),
            "code": pending["code"], "code_verifier": pending["verifier"],
            "redirect_uri": data["redirect_uri"], "grant_type": "authorization_code",
        })
        scopes = set(response.get("scope", "").split())
        if not SCOPES[flow["capability"]] <= scopes:
            raise AccountError("permissions_not_granted")
        access = response.get("access_token")
        if not access:
            raise AccountError("invalid_provider_response")
        identity = await self.provider.identity(access)
        if data.get("identity") and data["identity"]["subject"] != identity["subject"]:
            raise AccountError("different_google_account_disconnect_first")
        old = json.loads(await tx.resolve(GRANT, data["grant_ref"])) if data.get("grant_ref") else {}
        refresh = response.get("refresh_token") or old.get("refresh_token")
        if not refresh:
            raise AccountError("offline_access_missing_reconnect")
        grant = {"access_token": access, "refresh_token": refresh,
                 "expires_at": self.clock() + min(int(response.get("expires_in", 3600)), 86400)}
        data["grant_ref"] = await tx.put(GRANT, json.dumps(grant), data.get("grant_ref"))
        data["identity"], data["scopes"] = identity, sorted(scopes)
        data["enabled"] = [cap for cap in set(data.get("enabled", [])) | {flow["capability"]}
                           if SCOPES[cap] <= scopes]
        data["health"] = {cap: "not_checked" for cap in data["enabled"]}
        self.cache.clear()
        # Consent alone is not connected: perform an actual capability read.
        return await self._test(tx, {"capability": flow["capability"]})

    async def token(self, tx, cap):
        data = tx.data
        if cap not in data.get("enabled", []) or not data.get("grant_ref"):
            raise AccountError("not_connected")
        if data.get("health", {}).get(cap) == "reconnect_required":
            raise AccountError("reconnect_required")
        grant = json.loads(await tx.resolve(GRANT, data["grant_ref"]))
        if grant["expires_at"] <= self.clock() + 60:
            try:
                response = await self.provider.token({
                    "client_id": data["client_id"], "client_secret": await tx.resolve(CLIENT, data["client_ref"]),
                    "refresh_token": grant["refresh_token"], "grant_type": "refresh_token",
                })
            except AccountError as exc:
                if exc.code == "reconnect_required":
                    data["health"] = dict.fromkeys(data.get("enabled", []), "reconnect_required")
                    self.cache.clear()
                raise
            if not response.get("access_token"):
                raise AccountError("invalid_provider_response")
            grant.update(access_token=response["access_token"],
                         refresh_token=response.get("refresh_token") or grant["refresh_token"],
                         expires_at=self.clock() + min(int(response.get("expires_in", 3600)), 86400))
            await tx.put(GRANT, json.dumps(grant), data["grant_ref"])
        return grant["access_token"]

    async def read(self, tx, cap, key, call, *, fresh=False):
        data = tx.data
        try:
            token = await self.token(tx, cap)
            # Generation and grant reference prevent serving another process's old grant.
            cache_key = (data.get("generation"), data.get("grant_ref"), key)
            cached = self.cache.get(cache_key)
            if not fresh and cached and cached[0] > self.clock():
                return cached[1]
            value = await call(token)
            data.setdefault("health", {})[cap] = "connected"
            data.setdefault("last_success", {})[cap] = datetime.fromtimestamp(self.clock(), UTC).isoformat()
            if len(self.cache) >= 16:
                self.cache.clear()
            self.cache[cache_key] = (self.clock() + 30, value)
            return value
        except AccountError as exc:
            data.setdefault("health", {})[cap] = exc.code
            if exc.code == "reconnect_required":
                data["health"] = dict.fromkeys(data.get("enabled", []), exc.code)
            self.cache.clear()
            raise

    async def _test(self, tx, payload):
        cap = payload["capability"]
        if cap == "calendar":
            await self._calendars(tx, {"fresh": True})
        else:
            profile = await self.read(tx, cap, "profile",
                                      lambda token: self.provider.request(
                                          "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", token=token),
                                      fresh=True)
            if not profile.get("emailAddress"):
                tx.data["health"][cap] = "invalid_provider_response"
                raise AccountError("invalid_provider_response")
        return self.status(tx.data)

    async def _calendars(self, tx, payload):
        return {"calendars": await self.read(tx, "calendar", "calendars", self.provider.calendars,
                                            fresh=payload.get("fresh", False))}

    async def _selection(self, tx, payload):
        calendars = (await self._calendars(tx, {"fresh": True}))["calendars"]
        selected = list(dict.fromkeys(payload["calendar_ids"]))
        if not set(selected) <= {c["id"] for c in calendars}:
            raise AccountError("unknown_calendar")
        tx.data["selected_calendars"] = selected
        self.cache.clear()
        return self.status(tx.data)

    async def _events(self, tx, payload):
        start, end = payload["start"], payload["end"]
        if not start.tzinfo or not end.tzinfo or not timedelta(0) < end - start <= timedelta(days=31):
            raise AccountError("invalid_date_range")
        calendars = (await self._calendars(tx, {}))["calendars"]
        selected = tx.data.get("selected_calendars", [])
        if not selected:
            raise AccountError("select_calendars")
        calendars = [c for c in calendars if c["id"] in selected]
        if len(calendars) != len(selected):
            raise AccountError("selected_calendar_unavailable")
        return {"events": await self.read(
            tx, "calendar", ("events", tuple(selected), start.isoformat(), end.isoformat()),
            lambda token: self.provider.events(token, calendars, start, end),
        )}

    async def _messages(self, tx, payload):
        query = payload.get("query", "")[:512]
        return {"messages": await self.read(tx, "gmail", ("messages", query),
                                            lambda token: self.provider.messages(token, query))}

    async def _message(self, tx, payload):
        mid = payload["id"].removeprefix("google:")
        if not mid.isalnum() or len(mid) > 256:
            raise AccountError("invalid_message_id")
        return await self.read(tx, "gmail", ("message", mid), lambda token: self.provider.message(token, mid))

    async def _disconnect(self, tx, payload):
        data = tx.data
        token = None
        if data.get("grant_ref"):
            try:
                token = json.loads(await tx.resolve(GRANT, data["grant_ref"]))["refresh_token"]
            except SecretUnavailable:
                pass
            await tx.delete(GRANT, data.pop("grant_ref"))
        for name in ("identity", "scopes", "enabled", "health", "last_success", "selected_calendars"):
            data.pop(name, None)
        data["generation"] = secrets.token_hex(16)
        await self.remove_flows(tx)
        self.cache.clear()
        # Local disable is committed before upstream revocation by the route/service caller.
        return {"status": self.status(data), "_revoke_token": token}

    async def disconnect(self):
        return await self.execute("disconnect")
