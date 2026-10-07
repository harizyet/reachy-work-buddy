"""HTTP client for companion-core's conversation endpoint.

Per ADR 0002, companion-core is channel-agnostic: it only ever receives a
session_id, conversation_id, and text — never "this came from Telegram" as
anything but an opaque channel label for its own optional use.
`input_modality` (ADR 0011) is a deliberate, narrow exception to that
agnosticism: whether a turn was typed or spoken is a security-relevant
signal (destructive-action confirmation refuses voice), not a
channel-identity one, so it travels alongside `channel` rather than being
folded into it.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, BinaryIO

import httpx

from shared.protocols.accounts import SERVICE_HEADER
from shared.protocols.operator_api import (
    LLM_SETTINGS,
    LLM_USAGE,
    MEETING,
    MEETING_CANCEL,
    MEETINGS,
    PERSONA_SETTINGS,
    WEBSEARCH_LOG,
    WEBSEARCH_SETTINGS,
)


class CompanionCoreClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
        service_token: str | None = None,
    ) -> None:
        token = service_token or os.environ.get("ACCOUNTS_SERVICE_TOKEN")
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout,
                                         headers={SERVICE_HEADER: token} if token else {})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_turn(
        self, session_id: str, conversation_id: str, channel: str, text: str, *, input_modality: str = "text", force_frontier: bool = False,
        context_meeting_id: str | None = None,
    ) -> dict[str, Any]:
        resp = await self._client.post(
            "/conversation",
            timeout=130.0,
            json={
                "session_id": session_id,
                "conversation_id": conversation_id,
                "channel": channel,
                "text": text,
                "input_modality": input_modality,
                "force_frontier": force_frontier,
                "context_meeting_id": context_meeting_id,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def due_reminders(self, within_minutes: int = 15) -> list[dict[str, Any]]:
        """Phase 10: events companion-core's calendar store considers due
        for a reminder right now. See companion_core/calendar/reminders.py —
        this is a pure query, not a subscription; reachy-hub calls it
        on demand."""
        resp = await self._client.get("/calendar/reminders/due", params={"within_minutes": within_minutes}, timeout=45)
        resp.raise_for_status()
        return resp.json()

    async def coding_agent_completions_due(self) -> list[dict[str, Any]]:
        """Phase 29: coding-agent sessions that just reached a terminal
        status and haven't been reported yet. See companion_core/app.py's
        /coding-agents/completions/due — a pure query that claims each
        session_id before returning it, so polling this on an interval
        (coding_agent_notify_loop) never double-notifies."""
        resp = await self._client.get("/coding-agents/completions/due", timeout=15)
        resp.raise_for_status()
        return resp.json()

    async def get_briefing(self) -> list[dict[str, Any]]:
        """Phase 18 (docs/adr/0015): the prioritized calendar/tasks/email/
        reminders/project-events list companion-core's briefing.py builds.
        Same on-demand, no-subscription shape as due_reminders above."""
        resp = await self._client.get("/briefing", timeout=90)
        resp.raise_for_status()
        return resp.json()

    async def events_in_progress(self, now: datetime) -> list[dict[str, Any]]:
        """Phase 17 (docs/adr/0014): the "calendar" signal feeding
        interruption_policy.is_occupied — reuses the existing
        GET /calendar/events range query (no new companion-core endpoint)
        with a tight window around `now` to ask "is a meeting happening
        right now", not "what's coming up"."""
        resp = await self._client.get(
            "/calendar/events",
            params={"start": now.isoformat(), "end": (now + timedelta(seconds=1)).isoformat()},
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()

    async def health(self) -> dict:
        response = await self._client.get("/health")
        response.raise_for_status()
        return response.json()

    async def get_llm_settings(self) -> dict:
        response = await self._client.get(LLM_SETTINGS)
        response.raise_for_status()
        return response.json()

    async def set_llm_settings(self, patch: dict) -> dict:
        response = await self._client.put(LLM_SETTINGS, json=patch)
        response.raise_for_status()
        return response.json()

    async def get_llm_usage(self, *, limit: int = 50, since_hours: int = 24) -> dict:
        response = await self._client.get(LLM_USAGE, params={"limit": limit, "since_hours": since_hours})
        response.raise_for_status()
        return response.json()

    async def get_persona(self, *, timeout: float = 5.0) -> dict:
        response = await self._client.get(PERSONA_SETTINGS, timeout=timeout)
        response.raise_for_status()
        return response.json()

    async def set_persona(self, patch: dict) -> dict:
        response = await self._client.put(PERSONA_SETTINGS, json=patch)
        response.raise_for_status()
        return response.json()

    async def get_websearch_settings(self) -> dict:
        response = await self._client.get(WEBSEARCH_SETTINGS)
        response.raise_for_status()
        return response.json()

    async def get_websearch_log(self) -> dict:
        response = await self._client.get(WEBSEARCH_LOG)
        response.raise_for_status()
        return response.json()

    async def set_websearch_settings(self, patch: dict) -> dict:
        response = await self._client.put(WEBSEARCH_SETTINGS, json=patch)
        response.raise_for_status()
        return response.json()

    async def create_meeting(
        self,
        *,
        title: str,
        audio_bytes: bytes | BinaryIO,
        filename: str,
        content_type: str,
        project_scope: str | None = None,
        context: str | None = None,
        participants: str = "",
        started_at: str | None = None,
    ) -> dict[str, Any]:
        """Forward the spooled upload without buffering the recording in RAM."""
        data = {"title": title, "project_scope": project_scope or "", "context": context or "", "participants": participants}
        if started_at:
            data["started_at"] = started_at
        resp = await self._client.post(
            MEETINGS,
            data=data,
            files={"audio": (filename, audio_bytes, content_type)},
            timeout=httpx.Timeout(600.0, connect=10.0, pool=10.0),
        )
        resp.raise_for_status()
        return resp.json()

    async def list_meetings(self) -> list[dict[str, Any]]:
        resp = await self._client.get(MEETINGS, timeout=30.0)
        resp.raise_for_status()
        return resp.json()

    async def get_meeting(self, meeting_id: str) -> dict[str, Any]:
        resp = await self._client.get(MEETING.format(meeting_id=meeting_id), timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    async def cancel_meeting(self, meeting_id: str) -> dict[str, Any]:
        resp = await self._client.post(MEETING_CANCEL.format(meeting_id=meeting_id), timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    async def planner_request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> Any:
        """Owner to-do/reminder/note passthrough to core's /tasks, /notes, /reminders."""
        resp = await self._client.request(method, path, json=json, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    async def reminders_due(self) -> list[dict[str, Any]]:
        """Claim-once poll, like coding_agent_completions_due."""
        return await self.planner_request("GET", "/reminders/due")

    async def accounts_request(self, method, path, *, data=None, params=None):
        response = await self._client.request(method, path, json=data, params=params, timeout=65)
        response.raise_for_status()
        return response.json()
