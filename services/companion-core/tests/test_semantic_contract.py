"""Phase 44A contract (docs/phase-44.md section 4): shapes, access rules, and that AccessContext can never arrive from a client."""

import json

import pytest
from companion_core.app import create_app
from companion_core.calendar.store import InMemoryCalendarStore
from companion_core.consent.store import InMemoryConfirmationStore
from companion_core.email.store import InMemoryEmailStore
from companion_core.llm.store import InMemoryLLMSettingsStore, InMemoryLLMUsageStore
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.memory.store import InMemoryMemoryStore
from companion_core.persona.store import InMemoryPersonaStore
from companion_core.planner.store import InMemoryPlannerStore
from companion_core.rag.store import InMemoryDocumentStore
from companion_core.semantic import access
from companion_core.semantic.model import (
    AccessContext,
    ContextBundle,
    KnowledgeItem,
    Provenance,
    SourceRef,
)
from companion_core.tasks.store import InMemoryTaskStore
from companion_core.websearch.store import InMemorySearchSettingsStore
from pydantic import ValidationError

from shared.models.response import Privacy


def item(**overrides) -> KnowledgeItem:
    ref = SourceRef(source_type="memory", source_id="m1")
    base = {"ref": ref, "kind": "memory", "text": "t", "provenance": Provenance(ref=ref)}
    return KnowledgeItem(**{**base, **overrides})


def test_source_ref_key_is_stable_and_ignores_the_version() -> None:
    plain = SourceRef(source_type="meeting", source_id="abc")
    segment = SourceRef(source_type="meeting", source_id="abc", locator="12", source_version="v1")
    assert plain.key == "meeting:abc"
    assert segment.key == "meeting:abc#12"
    assert segment.key == segment.model_copy(update={"source_version": "v2"}).key
    assert hash(plain) == hash(SourceRef(source_type="meeting", source_id="abc"))  # frozen, usable as a dict key


def test_contract_types_are_frozen_and_reject_unknown_fields() -> None:
    ref = SourceRef(source_type="note", source_id="n")
    with pytest.raises(ValidationError):
        ref.source_id = "other"
    with pytest.raises(ValidationError):
        SourceRef(source_type="note", source_id="n", bogus=1)
    with pytest.raises(ValidationError):
        SourceRef(source_type="email", source_id="n")  # not a Phase 44 source
    with pytest.raises(ValidationError):
        item().text = "changed"


def test_unclassified_items_are_work_private_and_unscoped_is_not_public() -> None:
    it = item()
    assert it.sensitivity == Privacy.WORK_PRIVATE
    assert it.project_scope is None and it.local_only is False
    assert ContextBundle().max_sensitivity == Privacy.PUBLIC and ContextBundle().items == []


def test_owner_context_ceilings() -> None:
    assert access.access_for_owner("o", channel_private=False).sensitivity_ceiling == Privacy.PUBLIC
    assert access.access_for_owner("o", channel_private=True).sensitivity_ceiling == Privacy.WORK_PRIVATE
    assert (
        access.access_for_owner("o", channel_private=True, allow_sensitive=True).sensitivity_ceiling == Privacy.SENSITIVE
    )
    # A shared channel never reaches private data even when the caller asks for sensitive access.
    assert access.access_for_owner("o", channel_private=False, allow_sensitive=True).sensitivity_ceiling == Privacy.PUBLIC


def test_context_is_frozen_and_narrowing_cannot_widen() -> None:
    wide = access.access_for_owner(
        "o", channel_private=True, allow_sensitive=True, destinations=frozenset({"local", "cloud"}),
        project_scopes=frozenset({"a", "b"}),
    )
    with pytest.raises(ValidationError):
        wide.sensitivity_ceiling = Privacy.PUBLIC
    narrow = access.narrowed(wide, sensitivity_ceiling=Privacy.PUBLIC, destinations=frozenset({"local"}), project_scopes=frozenset({"a"}))
    assert (narrow.sensitivity_ceiling, narrow.destinations, narrow.project_scopes) == (Privacy.PUBLIC, frozenset({"local"}), frozenset({"a"}))
    modest = access.access_for_owner("o", channel_private=True, destinations=frozenset({"local"}), project_scopes=frozenset({"a"}))
    same = access.narrowed(
        modest, sensitivity_ceiling=Privacy.SENSITIVE, destinations=frozenset({"local", "cloud"}), project_scopes=frozenset({"a", "z"})
    )
    assert same.sensitivity_ceiling == Privacy.WORK_PRIVATE
    assert same.destinations == frozenset({"local"})
    assert same.project_scopes == frozenset({"a"})
    assert wide.sensitivity_ceiling == Privacy.SENSITIVE  # the original is untouched


def test_classification_is_never_downgraded() -> None:
    assert access.effective_sensitivity(Privacy.PUBLIC, Privacy.WORK_PRIVATE) == Privacy.WORK_PRIVATE
    assert access.effective_sensitivity(Privacy.SENSITIVE, Privacy.PUBLIC) == Privacy.SENSITIVE
    assert access.effective_sensitivity(Privacy.PUBLIC) == Privacy.PUBLIC


@pytest.mark.parametrize(
    ("ceiling", "sensitivity", "expected"),
    [
        (Privacy.PUBLIC, Privacy.PUBLIC, "ok"),
        (Privacy.PUBLIC, Privacy.WORK_PRIVATE, "over_ceiling"),
        (Privacy.WORK_PRIVATE, Privacy.WORK_PRIVATE, "ok"),
        (Privacy.WORK_PRIVATE, Privacy.SENSITIVE, "over_ceiling"),
        (Privacy.SENSITIVE, Privacy.SENSITIVE, "ok"),
    ],
)
def test_decide_applies_the_sensitivity_ceiling(ceiling, sensitivity, expected) -> None:
    ctx = AccessContext(principal="o", sensitivity_ceiling=ceiling)
    assert (access.decide(ctx, item(sensitivity=sensitivity)) or "ok") == expected


def test_decide_scope_rules_unscoped_is_owner_accessible_but_not_public() -> None:
    unrestricted = AccessContext(principal="o", sensitivity_ceiling=Privacy.WORK_PRIVATE)
    scoped = AccessContext(principal="o", sensitivity_ceiling=Privacy.WORK_PRIVATE, project_scopes=frozenset({"alpha"}))
    assert access.decide(unrestricted, item(project_scope="beta")) is None
    assert access.decide(scoped, item(project_scope="alpha")) is None
    assert access.decide(scoped, item(project_scope="beta")) == "out_of_scope"
    assert access.decide(scoped, item(project_scope=None)) is None  # interim single-owner policy (D8)
    # Unscoped does not bypass sensitivity.
    public_only = AccessContext(principal="o", sensitivity_ceiling=Privacy.PUBLIC)
    assert access.decide(public_only, item(project_scope=None, sensitivity=Privacy.WORK_PRIVATE)) == "over_ceiling"


def test_local_only_items_are_withheld_when_the_cloud_is_a_possible_destination() -> None:
    local = AccessContext(principal="o", sensitivity_ceiling=Privacy.WORK_PRIVATE, destinations=frozenset({"local", "deep_local"}))
    cloud = AccessContext(principal="o", sensitivity_ceiling=Privacy.WORK_PRIVATE, destinations=frozenset({"local", "cloud"}))
    none = AccessContext(principal="o", sensitivity_ceiling=Privacy.WORK_PRIVATE, destinations=frozenset())
    meeting = item(local_only=True)
    assert access.decide(local, meeting) is None
    assert access.decide(cloud, meeting) == "destination"
    assert access.decide(cloud, item(local_only=False)) is None
    assert access.decide(none, item(local_only=False)) == "destination"


def test_access_context_is_never_part_of_any_client_visible_schema() -> None:
    """The context is built by trusted code from the authenticated request. If it, or any of its distinctive fields, ever
    appears in an HTTP schema, a client could choose its own ceiling."""
    app = create_app(
        calendar_store=InMemoryCalendarStore(),
        task_store=InMemoryTaskStore(),
        planner_store=InMemoryPlannerStore(),
        meeting_store=InMemoryMeetingStore(),
        run_meeting_worker_task=False,
        memory_store=InMemoryMemoryStore(),
        rag_store=InMemoryDocumentStore(),
        email_store=InMemoryEmailStore(),
        confirmation_store=InMemoryConfirmationStore(),
        llm_settings_store=InMemoryLLMSettingsStore(),
        llm_usage_store=InMemoryLLMUsageStore(),
        persona_store=InMemoryPersonaStore(),
        search_settings_store=InMemorySearchSettingsStore(),
        run_email_dispatch_task=False,
    )
    schema = json.dumps(app.openapi())
    for forbidden in ("AccessContext", "sensitivity_ceiling", "project_scopes", "destinations", "channel_private"):
        assert forbidden not in schema, forbidden


def test_ontology_does_not_depend_on_the_ossie_adapter() -> None:
    import ast
    import pathlib

    import companion_core.semantic as package

    root = pathlib.Path(package.__file__).parent
    for name in ("model.py", "access.py"):
        for node in ast.walk(ast.parse((root / name).read_text())):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any("ossie" in m for m in modules), name
