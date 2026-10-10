"""Typed entity registry and relation registry for the deterministic path (Phase 44, I-2 follow-up, 2026-10-10).

Two things the earlier I-2 evaluation took from the dev15 gold labels are defined here independently of them:

ENTITIES are typed by FORM, not by a list. A type is a grammar: a model is `Name-<size>B`, a system is a capitalised name plus an infrastructure noun ("Ferry queue", "Hopper ingest service"), a host is
`<class> host`, a meeting is `<Name> [planning] meeting`, a bare capitalised word is a project, two or three capitalised words are a person or a vendor (the relation's slot decides which). A name never seen
before is therefore a known type; no instance list is needed. Explicit typed entries may be added (`with_entries`, for example from the owner's entity table); an explicit entry wins over the grammar and
also lets a lower-case spelling be recognised.

RELATIONS state what each one is: which types may be its subject, what kind of value it carries, which entity types appear as its VALUES, which types may share a sentence with its subject without competing,
which words say it in a record and which words ask for it in a question, and how a reply names it. The model-name collision of the first I-2 run is a typing problem and is solved by typing: a model is a value of
`default_model` and `decision` and the subject of `runs_on`, so it is never a competing subject for the first two and a competing subject (other models only) for the third.

`release_day`, `escalation_contact` and `approver` were held out of this registry until the final development pass (2026-10-10), which defined them from their domain meaning (see the comment above their
definitions) and froze them by hash before acceptance; the held-out slice of the earlier evaluation is therefore no longer held out for this path.
Nothing here reads dev15/dev16 gold, calls a model, or does I/O."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum

from companion_core.knowledge.answerability_b1.types import RelationSpec


class EntityType(StrEnum):
    PERSON = "person"
    PROJECT = "project"
    SYSTEM = "system"
    MODEL = "model"
    HOST = "host"
    VENDOR = "vendor"
    MEETING = "meeting"


P = EntityType
_SUBJECT_CAPABLE = frozenset({P.PROJECT, P.SYSTEM, P.MODEL, P.VENDOR, P.PERSON})

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mondays", "tuesdays", "wednesdays", "thursdays", "fridays", "saturdays", "sundays")  # the plural is the recurring form ("on Thursdays")
_KIND_NOUNS = ("queue", "scheduler", "gateway", "service", "cache", "API", "stream", "store", "dashboard", "builder", "index", "database", "pipeline", "worker", "broker", "proxy", "registry")
_FUNCTION_WORDS = frozenset(["the", "a", "an", "of", "for", "to", "in", "on", "at", "by", "with", "from", "and", "or", "is", "are", "was", "were", "has", "have", "had", "does", "do", "did", "will", "would", "can", "could", "which", "what", "who", "when", "where", "how", "that", "this", "its", "their", "not", "as", "be", "been"])
# words that can open a sentence with a capital and are never an entity name
_CLOSED_INITIAL = frozenset(["who", "whom", "whose", "what", "which", "when", "where", "why", "how", "is", "are", "was", "were", "does", "do", "did", "has", "have", "had", "can", "could", "will", "would", "should", "shall", "may", "might", "must", "tell", "show", "give", "list", "please", "and", "also", "then", "so", "but", "or", "okay", "ok", "well", "first", "second", "third", "next", "finally", "now", "yes", "no", "maybe", "could", "can", "i", "i'd", "i'm", "i'll", "let", "let's", "lets", "noted", "thanks", "thank", "hello", "hi", "hey", "remind", "explain", "summarise", "summarize", "describe", "the", "a", "an", "this", "that", "these", "those", "my", "our", "your", "their", "his", "her", "its", "some", "any", "all", "each", "every", "one", "on", "in", "at", "by", "for", "with", "from", "within", "until", "till", "through", "before", "after", "during", "of", "to", "as", "since", "between", "about", "over", "under"])

_NAME = r"[A-Z][a-z]*(?:-[A-Z][a-z]+|['’][A-Z][a-z]+)*"
_BARE = r"[A-Z][a-z]+(?:[A-Z][a-z]+)*"
_MODEL_RE = re.compile(r"\b([A-Z][a-z]+-\d+(?:\.\d+)?[Bb])\b")
_SYSTEM_RE = re.compile(rf"\b({_BARE})((?: [a-z]+)?) ({'|'.join(_KIND_NOUNS)})\b")
_MEETING_RE = re.compile(rf"\b({_BARE}) (?:planning )?meetings?\b")
_HOST_RE = re.compile(r"\b((?:gpu|cpu|edge|batch) hosts?)\b", re.IGNORECASE)
_PROPER_RE = re.compile(rf"\b({_NAME}(?: {_NAME}){{1,2}})\b")
_BARE_RE = re.compile(rf"\b({_BARE})\b")
_SENT_START = re.compile(r"(?:^|(?<=[.!?])\s+|\n+)")


@dataclass(frozen=True)
class Mention:
    """One entity mention. `types` is a SET: a bare capitalised word is a project, two capitalised words are a person or a vendor until a relation's slot says which. `alias` is the string records are searched with
    (the head word of a system, the first name of a person, the full model name); `subject` is the display form a reply uses."""

    subject: str
    alias: str
    types: frozenset[EntityType]
    start: int
    end: int
    explicit: bool = False
    initial: bool = False  # the mention opens a sentence (so its capital letter says nothing)

    def as_type(self, wanted: Collection[EntityType]) -> bool:
        return bool(self.types & set(wanted))


def _mask(text: str, spans: Iterable[tuple[int, int]]) -> str:
    out = list(text)
    for a, b in spans:
        out[a:b] = "\0" * (b - a)
    return "".join(out)


@dataclass(frozen=True)
class EntityRegistry:
    """Grammar for the entity types, plus optional explicit typed entries."""

    entries: tuple[tuple[str, EntityType, str], ...] = ()  # (name, type, alias)

    def with_entries(self, entries: Iterable[tuple[str, EntityType, str] | Mention]) -> EntityRegistry:
        """New registry with extra typed entries. A Mention with one type is registered under that type; an ambiguous (multi-type) mention is not registered (its type is not known)."""
        add = list(self.entries)
        have = {(n.casefold(), t) for n, t, _ in add}
        for e in entries:
            if isinstance(e, Mention):
                if len(e.types) != 1:
                    continue
                e = (e.subject, next(iter(e.types)), e.alias)
            if (e[0].casefold(), e[1]) not in have:
                have.add((e[0].casefold(), e[1]))
                add.append(e)
        return replace(self, entries=tuple(add))

    def mentions(self, text: str, *, initial_ok: bool = True) -> list[Mention]:
        """Typed mentions in one sentence or clause, left to right, non-overlapping. Every recogniser proposes spans; the LONGEST span wins an overlap (so "Sluice cache" beats an entry "Sluice"), and at equal
        length an explicit entry beats a model, a meeting, a system, a host, a name, a bare word, in that order. `initial_ok=False` (record text) refuses a bare capitalised word and any name that opens a sentence,
        because there the capital is only grammar."""
        starts = {m.end() for m in _SENT_START.finditer(text)}
        cands: list[tuple[int, int, int, str, str, frozenset[EntityType] | None, bool]] = []  # (start, end, priority, subject, alias, types or None for a blocker, explicit)

        for name, typ, alias in self.entries:
            for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.IGNORECASE):
                cands.append((m.start(), m.end(), 0, name, alias, frozenset([typ]), True))
        for m in _MODEL_RE.finditer(text):
            cands.append((m.start(), m.end(), 1, m.group(1), m.group(1), frozenset([P.MODEL]), False))
        for m in _MEETING_RE.finditer(text):
            if m.group(1).lower() not in _CLOSED_INITIAL:
                cands.append((m.start(), m.end(), 2, m.group(1), m.group(1), frozenset([P.MEETING]), False))
        for m in _SYSTEM_RE.finditer(text):
            mod = m.group(2).strip()
            if mod in _FUNCTION_WORDS or m.group(1).lower() in _CLOSED_INITIAL:
                continue
            cands.append((m.start(), m.end(), 3, f"{m.group(1)}{' ' + mod if mod else ''} {m.group(3)}", m.group(1), frozenset([P.SYSTEM]), False))
        for m in _HOST_RE.finditer(text):
            cands.append((m.start(), m.end(), 4, m.group(1), m.group(1), frozenset([P.HOST]), False))
        for m in _PROPER_RE.finditer(text):
            words = m.group(1).split(" ")
            a = m.start()
            if a in starts and words[0].lower() in _CLOSED_INITIAL:  # "Which Quarry Data ..." — drop the closed-class opener, keep the rest if it is still a name
                if len(words) < 3:
                    continue
                a += len(words[0]) + 1
                words = words[1:]
            if any(w.lower() in _MONTHS or w.lower() in _DAYS for w in words):
                continue
            if not initial_ok and a in starts:  # a name that opens a record sentence is kept out of the inventory (and its words must not be re-read as bare names either)
                cands.append((a, m.end(), 5, "", "", None, False))
                continue
            cands.append((a, m.end(), 5, " ".join(words), words[0], frozenset([P.PERSON, P.VENDOR]), False))
        for m in _BARE_RE.finditer(text):
            w = m.group(1)
            if w.lower() in _MONTHS or w.lower() in _DAYS or w.lower() in _CLOSED_INITIAL or w == "I" or (m.start() in starts and not initial_ok):
                continue
            cands.append((m.start(), m.end(), 6, w, w, frozenset([P.PROJECT]), False))
        taken: list[tuple[int, int]] = []
        found: list[Mention] = []
        for a, b, _prio, subject, alias, types, explicit in sorted(cands, key=lambda c: (-(c[1] - c[0]), c[2], c[0])):
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            if types is not None:
                found.append(Mention(subject, alias, types, a, b, explicit, a in starts))
        return sorted(found, key=lambda x: x.start)

    def harvest(self, texts: Iterable[str]) -> list[Mention]:
        """Entity inventory of a pool of record texts, by grammar only. Names that only ever OPEN a sentence are not taken (there the capital is grammar, "Failed Cedar jobs" is not a person); a real entity is
        found again in mid-sentence somewhere in the pool. Deduplicated by (subject, types)."""
        seen: dict[tuple[str, frozenset[EntityType]], Mention] = {}
        for text in texts:
            for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
                if sent.lstrip().startswith("#"):  # a heading line is a label, not a sentence; its words are not entities
                    continue
                sent = sent.lstrip("-*• ")
                for m in self.mentions(sent, initial_ok=False):
                    seen.setdefault((m.subject.casefold(), m.types), m)
        return list(seen.values())


# --- relations ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RelationDef:
    name: str
    subject_types: frozenset[EntityType]
    kind: str  # the RelationSpec kind of the VALUE
    cues: tuple[str, ...]  # how a RECORD states it
    qcues: tuple[str, ...]  # how a QUESTION asks for it
    label: str  # reply wording; {S} is the subject (with "the" for a system)
    answer_kinds: frozenset[str] = frozenset()  # answer types a question's wh-word may ask for; empty: the relation's own kind
    value_types: frozenset[EntityType] = frozenset()  # entity types that appear as VALUES of this relation (never competing subjects, and a candidate answer in a question is not accepted)
    co_types: frozenset[EntityType] = frozenset()  # entity types that may share the subject's sentence without competing
    many: bool = False
    negation: str | None = None
    presence: str | None = None
    text_pattern: str | None = None
    object_words: tuple[str, ...] = ()
    structured: str | None = None
    unit: str = ""
    prefix: str = ""
    holder_role: str | None = None  # the relation is about whoever holds this role of the subject ("the Marlin lead" -> vacation of the lead)
    allows_next: bool = False  # "next" is part of the relation ("next vacation"), not a period
    plural: bool = False  # the relation's noun is plural ("support hours"), so a reply says "are"/"were"
    sentence: str = ""  # reply template for a plain value ({S} subject, {V} value with its citation); for relations whose value is not a noun phrase
    sentence_past: str = ""  # the same for a value shown as past
    speaker_ok: bool = True  # a person-valued relation can be established by an authoritative first-person statement ("I will own X"); False where the speaker is not the value ("I will escalate X")

    @property
    def existence(self) -> bool:
        return self.kind == "existence"

    def asks(self) -> frozenset[str]:
        return self.answer_kinds or frozenset({self.kind})

    def spec(self) -> RelationSpec:
        words = self.name.replace("_", " ")
        # a person-valued relation can also be established by a first-person statement of an authoritative speaker ("I will fix the Cedar rollback test"); attendance by the structured attendee list
        structured = self.structured or ("speaker" if self.kind == "person" and self.speaker_ok else None)
        return RelationSpec(self.name, self.kind, self.cues, many=self.many, negation=self.negation, presence=self.presence, text_pattern=self.text_pattern, object_words=self.object_words, structured=structured,
                            co_subjects_ok=False, phrase=words, joiner="of", prefix=self.prefix, unit=self.unit, plural=self.plural, sentence=self.sentence, sentence_past=self.sentence_past)


def _fs(*items):
    return frozenset(items)


_PERSON_ASK = _fs("person")
RELATIONS: tuple[RelationDef, ...] = (
    RelationDef("owner", _fs(P.SYSTEM, P.PROJECT), "person", (r"\bown(?:s|ed|er|ers|ership)?\b", r"\bresponsib\w*", r"\baccountab\w*", r"\bin charge\b", r"\blooks? after\b", r"\bmaintain(?:s|ed|er|ers)?\b"),
                (r"\bown(?:s|ed|er|ers|ership)?\b", r"\bresponsib\w*", r"\baccountab\w*", r"\bin charge of\b", r"\blooks? after\b", r"\bmaintain(?:s|ed|er|ers)?\b"), "owner of {S}", value_types=_fs(P.PERSON, P.VENDOR)),
    RelationDef("lead", _fs(P.PROJECT), "person", (r"\blead(?:s|er|ers|ing)?\b", r"\bhead(?:s|ed)?\b", r"\bmanag(?:e|es|ed|er|ers|ing)\b", r"\bin charge\b"),
                (r"\blead(?:s|er|ers|ing)?\b", r"\bheads?\b", r"\bmanag(?:e|es|ed|er|ers|ing)\b", r"\bin charge of\b"), "lead of {S}", value_types=_fs(P.PERSON, P.VENDOR)),
    RelationDef("retry_limit", _fs(P.SYSTEM, P.PROJECT), "number", (r"\bretr(?:y|ies|ied|ying)\b", r"\battempts?\b", r"\btried\b"), (r"\bretr(?:y|ies|ied|ying)\b", r"\battempts?\b"), "retry limit of {S}", unit="retries"),
    RelationDef("default_model", _fs(P.PROJECT), "model", (r"\bdefault\b",), (r"\bdefault(?:s|ed)?\b",), "default model of {S}", value_types=_fs(P.MODEL)),
    RelationDef("decision", _fs(P.PROJECT), "text", (r"\bdecision\b", r"\bdecid(?:e|ed|es|ing)\b", r"\bagree[ds]?\b", r"\bsettled? on\b"), (r"\bdecid(?:e|ed|es|ing)\b", r"\bdecisions?\b", r"\bagree[ds]?\b", r"\bsettled? on\b"),
                "planning decision for {S}", answer_kinds=_fs("text", "model"), value_types=_fs(P.MODEL),
                sentence="The records say the decision for {S} was to {V}. They do not say whether it has been carried out.", sentence_past="Previously, the decision for {S} was to {V}.", text_pattern=r"\b(?:decision is to|decided to|agreed to)\s+(?P<value>[^.;,]{3,80}?)\s*(?:[.;]|$)"),
    RelationDef("runs_on", _fs(P.MODEL), "host", (r"\bhosts?\b", r"\bhosted\b", r"\bruns? on\b", r"\brunning on\b", r"\bserv(?:e|es|ed|ing)\b", r"\bdeployed on\b", r"\bhardware\b", r"\bmachine\b"),
                (r"\bhosts?\b", r"\bruns?\b", r"\brunning\b", r"\bserv(?:e|es|ed|ing)\b", r"\bhardware\b", r"\bmachines?\b"), "host running {S}", value_types=_fs(P.HOST), co_types=_fs(P.PROJECT, P.SYSTEM), prefix="the "),
    RelationDef("rollback_window", _fs(P.PROJECT), "number", (r"\broll(?:s|ed|ing)?[\s-]?back\b(?!\s+tests?)", r"\bundo\b", r"\brevert\w*"), (r"\broll(?:s|ed|ing)?[\s-]?back\b(?!\s+tests?)", r"\bundo\b", r"\brevert\w*"),
                "rollback window for {S}", unit="minutes"),
    RelationDef("support_hours", _fs(P.VENDOR), "hours", (r"\bsupport\b", r"\bhours\b", r"\bstaffed\b"), (r"\bsupport\b", r"\bhours\b", r"\bstaffed\b"), "weekday support hours of {S}", answer_kinds=_fs("hours", "time"), plural=True),
    RelationDef("reviews", _fs(P.PERSON), "text", (r"\breview(?:s|ed|ing)?\b",), (r"\breview(?:s|ed|ing)?\b",), "review assigned to {S}", sentence="{S} reviews {V}.", sentence_past="Previously, {S} reviewed {V}.",
                text_pattern=r"\breview(?:s|ing)?\s+(?:the\s+)?(?P<value>[A-Z][\w-]*(?: [\w-]+){0,4}?)\s*(?:[.;]|$)"),
    RelationDef("on_call", _fs(P.PROJECT), "person", (r"\bon[\s-]?call\b", r"\bpager\b", r"\bpaged\b"), (r"\bon[\s-]?call\b", r"\bpager\b", r"\bpaged\b"), "person on call for {S}", value_types=_fs(P.PERSON, P.VENDOR)),
    RelationDef("budget_through", _fs(P.PROJECT), "month", (r"\bbudget\w*", r"\bfund(?:ed|ing|s)?\b", r"\bapproved through\b"), (r"\bbudget\w*", r"\bfund(?:ed|ing|s)?\b", r"\bapproved through\b"), "last funded month for {S}", answer_kinds=_fs("month", "day")),
    RelationDef("deadline", _fs(P.PERSON), "day", (r"\bdeadline\b", r"\bdue\b", r"\bcirculate\b"), (r"\bdeadline\b", r"\bdue\b", r"\bcirculate\b", r"\bwritten summary\b"), "deadline for {S}'s written summary", answer_kinds=_fs("day", "month")),
    RelationDef("staging_env", _fs(P.PROJECT), "existence", (r"\bstaging\b",), (r"\bstaging\b",), "staging environment for {S}", negation=r"\b(?:has no|does not have|there is no|no|without)\b", presence=r"\b(?:has an?|there is an?|have an?)\b"),
    RelationDef("test_fixer", _fs(P.PROJECT), "person", (r"\bfix\w*", r"\broll[\s-]?back tests?\b"), (r"\broll[\s-]?back tests?\b",), "person fixing the {S} rollback test", value_types=_fs(P.PERSON, P.VENDOR), object_words=("rollback", "test")),
    RelationDef("security_reviewer", _fs(P.PROJECT), "person", (r"\bsecurity\b",), (r"\bsecurity(?:\s+review\w*)?\b",), "security reviewer for {S}", value_types=_fs(P.PERSON, P.VENDOR)),
    RelationDef("max_message_size", _fs(P.SYSTEM), "number", (r"\bmax(?:imum)?\b.*\bmessage", r"\bmessage size\b", r"\bmessages?\b.*\b(?:size|limit)\b"),
                (r"\bmessage size\b", r"\b(?:large|big|long)\b.*\bmessages?\b", r"\bmessages?\b.*\b(?:large|big|size)\b", r"\bmax(?:imum)?\b.*\bmessages?\b", r"\bsize limit\b"), "maximum message size of {S}"),
    RelationDef("vacation", _fs(P.PROJECT), "month", (r"\bvacation\b", r"\bholiday\b", r"\baway\b", r"\bout of (?:the )?office\b", r"\bdays? off\b", r"\bon leave\b"),
                (r"\bvacations?\b", r"\bholidays?\b", r"\baway\b", r"\bout of (?:the )?office\b", r"\bdays? off\b", r"\bon leave\b"), "next time away for the {S} lead", answer_kinds=_fs("month", "day"), holder_role="lead", allows_next=True),
    RelationDef("incident_auditor", _fs(P.PROJECT), "person", (r"\baudit\w*",), (r"\baudit(?:s|ed|ing|or|ors)?\b",), "person who audits the {S} build logs", value_types=_fs(P.PERSON, P.VENDOR)),
    RelationDef("standup", _fs(P.PROJECT), "time", (r"\bstand-?ups?\b",), (r"\bstand-?ups?\b",), "standup time for {S}", answer_kinds=_fs("time", "hours")),
    RelationDef("review_day", _fs(P.PROJECT), "day", (r"\bdesign reviews?\b", r"\breview day\b"), (r"\bdesign reviews?\b", r"\breview day\b"), "design review day for {S}"),
    # --- defined in the final development pass, from what the words mean (not from any dev16 case or bank D phrasing; see decomposition_heldout_set.py for the disclosure) ----------------------------------
    # release_day: the weekday a project's releases go out. A one-off release date ("released on Friday") and an approval day are different propositions, so the record cues are the recurring forms only.
    RelationDef("release_day", _fs(P.PROJECT), "day", (r"\brelease day\b", r"\breleases?\s+(?:go(?:es)?\s+(?:out|live)|ship|shipped|land|happen)\b", r"\breleases\s+(?:on|every|each)\b", r"\bships?\s+(?:on|every|each)\b", r"\bcuts?\s+(?:a\s+|the\s+)?releases?\b",
                                                      r"\breleases are (?:cut|shipped|published)\b", r"\bis released (?:on|every|each)\b"),
                (r"\brelease day\b", r"\bdays?\b[^?;,]*\b(?:releas(?:e|es|ed|ing)|ship(?:s|ped|ping)?)\b(?![^?;,]*\bapprov)", r"\bwhen\s+(?:does|do|will|is|are)\b(?![^?;,]*\b(?:approv|last|latest|previous|first|next|newest))[^?;,]*\b(?:releas(?:e|es)|ships?)\b", r"\bweekday\b[^?;,]*\b(?:releas\w+|ship\w*)\b"),
                "release day for {S}", answer_kinds=_fs("day")),
    # escalation_contact: the person incidents are escalated to. The speaker of "I will escalate X" is the one escalating, not the contact, so first-person statements never establish it.
    RelationDef("escalation_contact", _fs(P.PROJECT, P.SYSTEM), "person", (r"\bescalat\w*",), (r"\bescalat\w*",), "escalation contact for {S}", value_types=_fs(P.PERSON, P.VENDOR), speaker_ok=False,
                object_words=("incident", "incidents", "outage", "outages", "problem", "problems", "issue", "issues", "alert", "alerts")),
    # approver: the person who approves a RELEASE. A budget approval or any other approval is another proposition, so a record cue needs the word "release" in the same sentence; an unqualified "approver" is read as
    # the release approver, a "budget approver" is not.
    RelationDef("approver", _fs(P.PROJECT), "person", (r"\bapprov\w*\b[^.;]*\breleases?\b", r"\breleases?\b[^.;]*\bapprov\w*\b", r"\bsign(?:s|ed)? off\b[^.;]*\breleases?\b"),
                (r"(?<!budget )(?<!spending )(?<!expense )(?<!purchase )\bapprovers?\b", r"\b(?:who(?:m)?|which (?:person|people|engineers?))\b[^?;,]*?\bapprov(?:e|es|ed|ing)\b[^?;,]*\breleas\w*", r"\bwho\b[^?;,]*\bsign(?:s|ed)? off\b[^?;,]*\breleas\w*"),
                "approver of the {S} release", value_types=_fs(P.PERSON, P.VENDOR), speaker_ok=False, object_words=("release", "releases")),
    RelationDef("attends", _fs(P.MEETING), "person", (r"\battend\w*", r"\bparticipa\w*", r"\bjoined\b", r"\btook part\b", r"\bspoke\b"), (r"\battend\w*", r"\bparticipa\w*", r"\bjoined\b", r"\btook part\b", r"\bspoke\b", r"\bwho (?:was|were) (?:in|at|there)\b"),
                "attendees of the {S} planning meeting", many=True, value_types=_fs(P.PERSON, P.VENDOR), structured="attendees"),
)
RELATION_BY_NAME = {r.name: r for r in RELATIONS}


@dataclass(frozen=True)
class Registry:
    entities: EntityRegistry = field(default_factory=EntityRegistry)
    relations: tuple[RelationDef, ...] = RELATIONS

    def __post_init__(self):
        object.__setattr__(self, "_by_name", {r.name: r for r in self.relations})

    def relation(self, name: str) -> RelationDef | None:
        return self._by_name.get(name)  # type: ignore[attr-defined]

    def specs(self) -> dict[str, RelationSpec]:
        return {r.name: r.spec() for r in self.relations}

    def competitors(self, relation: str, own_aliases: Collection[str], pool: Iterable[Mention]) -> list[str]:
        """Aliases that must count as COMPETING subjects when a record sentence for `relation` names them. A pooled entity competes unless one of its types is a value type of the relation or a type allowed to share
        its subject's sentence. A two- or three-word name (person or vendor) competes only for relations whose subject is a person or a vendor."""
        r = self.relation(relation)
        if r is None:
            return []
        own = {a.casefold() for a in own_aliases}
        out: dict[str, str] = {}
        for m in pool:
            if m.alias.casefold() in own or P.MEETING in m.types or P.HOST in m.types:
                continue
            if m.types & r.value_types or m.types & r.co_types:
                continue
            if m.types <= {P.PERSON, P.VENDOR} and not (r.subject_types & {P.PERSON, P.VENDOR}):
                continue
            if not (m.types & _SUBJECT_CAPABLE):
                continue
            out.setdefault(m.alias.casefold(), m.alias)
        return sorted(out.values())

    def label(self, relation: str, mention: Mention) -> str:
        r = self.relation(relation)
        if r is None:
            return mention.subject
        s = f"the {mention.subject}" if P.SYSTEM in mention.types else mention.subject
        return r.label.replace("{S}", s)
