"""Core routes for Home (docs/phase-51.md). Read-only: they behind the service token like every core route, and the hub proxies them for the owner session only.

The caller's access comes from the ceiling header the hub sets for the authenticated channel (never from a query or a body), exactly as /conversation does; with no header it is work-private,
and a public ceiling reads nothing at all."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from companion_core.document_library.access import access_from_ceiling
from companion_core.home import build_home
from companion_core.home_brief import build_brief
from shared.protocols.document_library_api import ACCESS_CEILING_HEADER
from shared.protocols.home_api import HOME, HOME_BRIEF, SECTIONS


class BriefBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative: bool = True  # also ask the local model to reword the lines; the deterministic lines are returned either way


def install_home_routes(app: FastAPI, provider=None) -> None:
    """`provider` is the same local-model provider Notepad processing uses (returns (ask, model) or None); private records are never sent to a cloud model by this path."""

    def access_for(request: Request):
        try:
            return access_from_ceiling(request.headers.get(ACCESS_CEILING_HEADER))
        except ValueError:
            raise HTTPException(400, "Unknown access ceiling") from None

    async def snapshot(request: Request, sections: tuple[str, ...]) -> dict:
        state = app.state
        return await build_home(
            access=access_for(request), now=datetime.now(UTC), persona=await state.persona_store.get(), calendar_store=state.calendar_store, task_store=state.task_store,
            planner_store=state.planner_store, notepad_service=state.notepad_service, analysis_service=state.meeting_analysis_service, weather=getattr(state, "weather", None),
            sections=sections,
        )

    @app.get(HOME)
    async def home(request: Request, sections: str | None = Query(default=None, max_length=100)) -> dict:
        """The Home snapshot, or only the named sections (comma separated): a section refreshes on its own without rebuilding the others."""
        wanted = tuple(s.strip() for s in sections.split(",")) if sections else SECTIONS
        if not wanted or any(s not in SECTIONS for s in wanted):
            raise HTTPException(422, "Unknown section")
        return await snapshot(request, wanted)

    @app.post(HOME_BRIEF)
    async def brief(request: Request, body: BriefBody | None = None) -> dict:
        body = body or BriefBody()
        data = await snapshot(request, SECTIONS)
        ask, model = None, None
        if body.narrative and not data["restricted"] and provider is not None:
            offered = await provider()
            if offered is not None:
                ask, model = offered
        return await build_brief(data, ask=ask, model=model, want_narrative=body.narrative, now=datetime.now(UTC))
