"""Types of the Stage B-1 pipeline. `DiscoveryItem` (untrusted, as retrieved) and `AdmittedFact` (checked, typed) are deliberately unrelated classes: there is no constructor path from one to the other except
`admission.admit`, which holds the private token an AdmittedFact requires."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

_TOKEN = object()  # held only by admission.admit


class State(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONFLICTED = "CONFLICTED"
    HISTORICAL = "HISTORICAL"
    NEGATIVE_SUPPORTED = "NEGATIVE_SUPPORTED"
    NEGATIVE_UNSUPPORTED = "NEGATIVE_UNSUPPORTED"
    ORDER_UNSUPPORTED = "ORDER_UNSUPPORTED"


class Ask(StrEnum):
    VALUE = "value"  # what is the X
    EXISTENCE = "existence"  # is there an X / does it have an X
    ORDERING = "ordering"  # which is newer, was it updated, which came first


class Scope(StrEnum):
    """What time the question is about."""

    CURRENT = "current"
    PAST = "past"
    ANY = "any"


class FactScope(StrEnum):
    """What time a record's statement is about, from the record's own explicit wording or explicit effective period. Never from retrieval or creation time."""

    PAST = "past"
    CURRENT = "current"
    UNDATED = "undated"


class AuthorClass(StrEnum):
    OWNER = "owner"
    ATTENDEE = "attendee"
    SYSTEM = "system"
    THIRD_PARTY = "third_party"


AUTHORITATIVE = frozenset({AuthorClass.OWNER, AuthorClass.SYSTEM})


@dataclass(frozen=True)
class Provenance:
    """Validated provenance. `created_at` and `retrieved_at` are kept for audit only; no decision reads them."""

    store: str
    record_id: str
    author_class: AuthorClass
    created_at: datetime
    retrieved_at: datetime
    acl_revision: int
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    lifecycle: str = "active"  # "active" | "archived"


@dataclass(frozen=True)
class AuthDecision:
    """The code-side access decision for one record in one turn."""

    authorized: bool
    checked_at: datetime
    policy_version: str
    acl_revision: int


@dataclass(frozen=True)
class DiscoveryItem:
    """A retrieved record exactly as found. `provenance` is a raw mapping from the caller and is untrusted until `admission` validates it. Holds no typed facts and can never be asserted from."""

    ref: str
    text: str
    provenance: Mapping | None = None
    title: str = ""


@dataclass(frozen=True)
class RelationSpec:
    """A reviewable description of one relation: how a sentence states it and what kind of value it carries. Supplied by the caller; nothing here is learned."""

    name: str
    kind: str  # person | number | day | month | model | host | hours | time | existence
    cues: tuple[str, ...]  # regexes: the relation words a sentence must contain
    many: bool = False  # several values may be true at once (attendees)
    negation: str | None = None  # existence kind: regex for "has no X"
    presence: str | None = None  # existence kind: regex for "has an X"
    co_subjects_ok: bool = False  # sentences of this relation naturally name a second entity ("Osprey serves Swift-6B on the edge host"); it is then not a competing subject
    phrase: str = ""  # wording used by code-written replies ("owner", "staging environment"); defaults to the relation name
    joiner: str = "of"  # "owner OF the Ferry queue", "staging environment FOR Vesper"

    @property
    def words(self) -> str:
        return self.phrase or self.name.replace("_", " ")


@dataclass(frozen=True)
class Component:
    """One independently answerable sub-claim of a question."""

    id: str
    subject: str
    aliases: tuple[str, ...]
    relation: str | None  # None: the relation could not be typed
    ask: Ask = Ask.VALUE
    scope: Scope = Scope.ANY
    label: str = ""  # human wording used by the code-written replies, e.g. "owner of the Ferry queue"


@dataclass(frozen=True)
class AdmittedFact:
    component_id: str
    ref: str
    value: str  # normalised; "" for an existence statement
    polarity: str  # "asserts" | "negates"
    scope: FactScope
    sentence: str  # the exact sentence the fact was read from (claim-level evidence)
    provenance: Provenance
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TypeError("an AdmittedFact can only be created by admission.admit")
