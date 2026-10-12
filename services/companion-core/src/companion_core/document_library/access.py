"""The caller's access context for document content, from the ceiling the hub established for the authenticated channel (never from a request body or from the document)."""

from __future__ import annotations

import os

from companion_core.semantic.access import access_for_owner
from companion_core.semantic.model import AccessContext
from shared.models.response import Privacy


def access_from_ceiling(header: str | None, *, voice: bool = False) -> AccessContext:
    """`header` is the hub's X-Reachy-Access-Ceiling (absent: work-private). A spoken turn is a shared speaker and is capped at public whatever the header says. Raises ValueError on an unknown value."""
    ceiling = Privacy(header) if header else Privacy.WORK_PRIVATE
    if voice:
        ceiling = Privacy.PUBLIC
    return access_for_owner(
        os.environ.get("OWNER_USER_ID", "default-user"), channel_private=ceiling is not Privacy.PUBLIC, allow_sensitive=ceiling is Privacy.SENSITIVE, destinations=frozenset({"local"})
    )
