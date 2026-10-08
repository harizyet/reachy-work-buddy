"""Pure access rules for the knowledge layer (docs/phase-44.md D2, D6, D8). No I/O; the retriever applies these to the state
it just read from the authoritative store, after it has checked the record still exists and is visible."""

from __future__ import annotations

from companion_core.semantic.model import (
    AccessContext,
    Destination,
    DropReason,
    KnowledgeItem,
)
from shared.models.response import Privacy

_RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}
_LOCAL: frozenset[Destination] = frozenset({"local", "deep_local"})


def access_for_owner(
    principal: str,
    *,
    channel_private: bool,
    allow_sensitive: bool = False,
    destinations: frozenset[Destination] = frozenset({"local"}),
    project_scopes: frozenset[str] | None = None,
) -> AccessContext:
    """Build the owner's access context from trusted request state. A non-private channel (a shared speaker) is capped at
    public so private records are never read out loud. A private channel reaches work-private records; sensitive ones only
    when the trusted caller says so (`allow_sensitive`, decided from the hub's trust level, never from the request text)."""
    ceiling = Privacy.PUBLIC
    if channel_private:
        ceiling = Privacy.SENSITIVE if allow_sensitive else Privacy.WORK_PRIVATE
    return AccessContext(
        principal=principal,
        sensitivity_ceiling=ceiling,
        project_scopes=project_scopes,
        destinations=destinations,
        channel_private=channel_private,
    )


def narrowed(
    access: AccessContext,
    *,
    sensitivity_ceiling: Privacy | None = None,
    destinations: frozenset[Destination] | None = None,
    project_scopes: frozenset[str] | None = None,
) -> AccessContext:
    """A context that can only be as wide as `access` or narrower; widening is not expressible here."""
    ceiling = access.sensitivity_ceiling
    if sensitivity_ceiling is not None and _RANK[sensitivity_ceiling] < _RANK[ceiling]:
        ceiling = sensitivity_ceiling
    allowed = access.destinations if destinations is None else access.destinations & destinations
    scopes = access.project_scopes
    if project_scopes is not None:
        scopes = project_scopes if scopes is None else scopes & project_scopes
    return access.model_copy(update={"sensitivity_ceiling": ceiling, "destinations": allowed, "project_scopes": scopes})


def effective_sensitivity(*labels: Privacy) -> Privacy:
    """The most restrictive of several labels (an index copy and the source now, or the evidence of a derived item)."""
    return max(labels, key=_RANK.__getitem__)


def within_ceiling(sensitivity: Privacy, ceiling: Privacy) -> bool:
    return _RANK[sensitivity] <= _RANK[ceiling]


def scope_permits(access: AccessContext, project_scope: str | None) -> bool:
    """Unscoped records (None) are owner-accessible while Reachy is single-owner, still subject to sensitivity. When scope
    control exists they need an explicit policy (D8), so this is the single place to change."""
    if project_scope is None or access.project_scopes is None:
        return True
    return project_scope in access.project_scopes


def destination_permits(access: AccessContext, local_only: bool) -> bool:
    """A local-only item is withheld when the caller may route to the cloud; it cannot be admitted and trusted to be routed
    locally later. With no destination at all nothing is admitted."""
    if not access.destinations:
        return False
    return not (local_only and not access.destinations <= _LOCAL)


def decide(access: AccessContext, item: KnowledgeItem) -> DropReason | None:
    """Why `item` must not be returned to this caller, or None. Validity (forgotten, expired, deleted) is checked against the
    store before this runs and is reported under those reasons by the retriever."""
    if not within_ceiling(item.sensitivity, access.sensitivity_ceiling):
        return "over_ceiling"
    if not scope_permits(access, item.project_scope):
        return "out_of_scope"
    if not destination_permits(access, item.local_only):
        return "destination"
    return None
