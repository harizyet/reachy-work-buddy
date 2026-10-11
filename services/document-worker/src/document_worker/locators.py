"""Backend locators look like `doc:d59e103/tier:flash/page:2/block:2`. The worker only ever hands back locators for the
document a request named, and the page it reports is the one in the locator, never a position computed from text."""

from __future__ import annotations

import re

_LOCATOR_RE = re.compile(r"^doc:([0-9a-f]{4,64})/tier:(flash|basic|standard|advanced)(?:/page:(\d+)(?:/block:(\d+))?)?$")


class InvalidLocator(ValueError):
    pass


def parse(locator: str) -> tuple[str, str, int | None, int | None]:
    match = _LOCATOR_RE.match(locator)
    if match is None:
        raise InvalidLocator("malformed locator")
    doc, tier, page, block = match.groups()
    return doc, tier, int(page) if page else None, int(block) if block else None


def belongs_to(locator: str, backend_ref: str) -> bool:
    try:
        return parse(locator)[0] == backend_ref
    except InvalidLocator:
        return False


def page_locator(backend_ref: str, tier: str, page: int) -> str:
    return f"doc:{backend_ref}/tier:{tier}/page:{page}"
