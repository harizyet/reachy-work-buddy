"""Admission: the only place where a retrieved record can become an assertable fact.

A record is admitted for a component only if all of these hold, each decided by code from structured fields and the record's own wording:
  1 provenance parses and is internally consistent (store/record id match the ref, tz-aware timestamps, retrieval not before creation, effective period ordered, known author class)
  2 an access decision exists, grants access, is fresh, was made under the expected policy version and for the record's current ACL revision (a stale decision is not a decision)
  3 the record is not instruction-bearing content
  4 a sentence names the component's subject AND carries the relation's cue AND carries exactly one value of the relation's kind (several only for `many` relations), unhedged and un-negated
Anything that nearly passes is *ambiguous* and is reported as such: it is never admitted and never supports an assertion. A record that is authorised and well-formed but merely related (a sibling's value, an
adjacent relation) is *discovery only*. Retrieval time and record creation time are carried for audit and are never read by a decision about recency or supersession."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from companion_core.knowledge.answerability_b1.types import (
    _TOKEN,
    AUTHORITATIVE,
    AdmittedFact,
    AuthDecision,
    AuthorClass,
    Component,
    DiscoveryItem,
    FactScope,
    Provenance,
    RelationSpec,
)
from companion_core.knowledge.context import looks_like_instruction

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_HEDGE = re.compile(r"\?|\b(?:might|maybe|perhaps|probably|possibly|could be|unless|unclear|unsure|not sure|tentative|proposed|rumou?red|supposedly)\b|\bif\b", re.IGNORECASE)
_NEGATED_VALUE = re.compile(r"\b(?:not|never|no longer|isn['’]t|aren['’]t|wasn['’]t|doesn['’]t|does not|don['’]t|do not|nobody|no one)\b", re.IGNORECASE)
_PAST = re.compile(r"\b(?:formerly|previously|used to|archived|retired|no longer|originally|earlier|had been|prior to|superseded)\b|\bas of (?:january|february|march|april|may|june|july|august|september)\b[^.]*\b(?:was|were|had)\b|"
                   r"\bbefore (?:january|february|march|april|may|june|july|august|september|october|november|december)\b|\bold\b", re.IGNORECASE)
_CURRENT = re.compile(r"\b(?:currently|at present|presently|is now|are now|as of today|right now)\b", re.IGNORECASE)
_SUPERSEDES = re.compile(r"\b(?:supersedes|replaces|overrides)\s+(?:the\s+)?(?:record\s+|entry\s+|memory\s+)?([A-Za-z0-9_:#.\-]+)", re.IGNORECASE)
_TITLE_PAST = re.compile(r"archived|\(old\)|\bv\d\b", re.IGNORECASE)
_NUMWORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}
_VALUE_PATTERNS = {
    "number": re.compile(r"\b(\d+)\b|\b(" + "|".join(_NUMWORDS) + r")\b", re.IGNORECASE),
    "day": re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE),
    "month": re.compile(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", re.IGNORECASE),
    "model": re.compile(r"\b([A-Z][a-z]+-\d+B)\b"),
    "host": re.compile(r"\b((?:gpu|cpu|edge|batch) host)\b", re.IGNORECASE),
    "hours": re.compile(r"\b(\d{1,2} to \d{1,2})\b", re.IGNORECASE),
    "time": re.compile(r"\b(\d{1,2}(?::\d{2})?)\b"),
    "person": re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b"),
}


@dataclass(frozen=True)
class AdmissionPolicy:
    expected_policy_version: str
    auth_max_age: timedelta = timedelta(seconds=60)
    clock_skew: timedelta = timedelta(seconds=2)


@dataclass(frozen=True)
class AdmissionResult:
    component_id: str
    facts: tuple[AdmittedFact, ...]
    ambiguous: tuple[tuple[str, str], ...]  # (ref, reason): authorised and well-formed but not safely readable; never an assertion
    excluded: tuple[tuple[str, tuple[str, ...]], ...]  # (ref, reasons): audit only; a reply must never reveal these
    discovery_only: tuple[str, ...]  # authorised and well-formed, asserting nothing for this component


def _dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None
    return None


def parse_provenance(ref: str, raw: Mapping | None, now: datetime, policy: AdmissionPolicy) -> tuple[Provenance | None, list[str]]:
    if not isinstance(raw, Mapping):
        return None, ["provenance_missing"]
    problems: list[str] = []
    for key in ("store", "record_id", "author_class", "created_at", "retrieved_at", "acl_revision"):
        if raw.get(key) in (None, ""):
            problems.append(f"provenance_missing_{key}")
    if problems:
        return None, problems
    try:
        author = AuthorClass(raw["author_class"])
    except ValueError:
        problems.append("provenance_unknown_author_class")
        author = AuthorClass.THIRD_PARTY
    acl = raw["acl_revision"]
    if isinstance(acl, bool) or not isinstance(acl, int):
        problems.append("provenance_bad_acl_revision")
    if not (isinstance(raw["store"], str) and isinstance(raw["record_id"], str)):
        problems.append("provenance_bad_identity")
    elif ref.split("#")[0] != f"{raw['store']}:{raw['record_id']}":
        problems.append("provenance_ref_mismatch")
    created, retrieved = _dt(raw["created_at"]), _dt(raw["retrieved_at"])
    if created is None or retrieved is None:
        problems.append("provenance_bad_timestamp")
    start = _dt(raw.get("effective_start")) if raw.get("effective_start") else None
    end = _dt(raw.get("effective_end")) if raw.get("effective_end") else None
    if (raw.get("effective_start") and start is None) or (raw.get("effective_end") and end is None):
        problems.append("provenance_bad_effective_period")
    if created and retrieved and (retrieved < created or created > now + policy.clock_skew):
        problems.append("provenance_timestamps_inconsistent")
    if start and end and end < start:
        problems.append("provenance_effective_period_reversed")
    lifecycle = raw.get("lifecycle", "active")
    if lifecycle not in ("active", "archived"):
        problems.append("provenance_bad_lifecycle")
    if problems:
        return None, problems
    return Provenance(raw["store"], raw["record_id"], author, created, retrieved, acl, start, end, lifecycle), []


def check_authorization(prov: Provenance, decision: AuthDecision | None, now: datetime, policy: AdmissionPolicy) -> list[str]:
    if decision is None:
        return ["authorization_missing"]
    if not decision.authorized:
        return ["not_authorized"]
    reasons = []
    if decision.checked_at > now + policy.clock_skew:
        reasons.append("authorization_from_the_future")
    elif now - decision.checked_at > policy.auth_max_age:
        reasons.append("authorization_stale")
    if decision.policy_version != policy.expected_policy_version:
        reasons.append("authorization_policy_version_mismatch")
    if decision.acl_revision != prov.acl_revision:
        reasons.append("authorization_acl_revision_changed")
    return reasons


def _values(kind: str, sentence: str, exclude: Collection[str]) -> list[str]:
    skip = [e.lower() for e in exclude]
    found = []
    for m in _VALUE_PATTERNS[kind].finditer(sentence):
        raw = next(g for g in m.groups() if g)
        low = raw.lower()
        if kind == "person" and any(low == e or low in e or e in low for e in skip):
            continue
        if low in skip:
            continue
        found.append(_NUMWORDS.get(low, raw if kind in ("person", "model") else low))
    return found


def _alias_re(aliases: Collection[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def _fact_scope(sentence: str, prov: Provenance, title: str, now: datetime) -> FactScope:
    """Time of the fact from the record's own explicit wording or explicit effective period. Retrieval time and record creation time are never read here."""
    if prov.lifecycle == "archived" or _TITLE_PAST.search(title or "") or _PAST.search(sentence):
        return FactScope.PAST
    if prov.effective_end is not None and prov.effective_end < now:
        return FactScope.PAST
    if _CURRENT.search(sentence) or (prov.effective_start is not None and prov.effective_start <= now and (prov.effective_end is None or prov.effective_end >= now)):
        return FactScope.CURRENT
    return FactScope.UNDATED


def admit(component: Component, items: Collection[DiscoveryItem], auths: Mapping[str, AuthDecision], *, now: datetime, spec: RelationSpec | None, known_subjects: Collection[str],
          policy: AdmissionPolicy) -> AdmissionResult:
    facts: list[AdmittedFact] = []
    ambiguous: list[tuple[str, str]] = []
    excluded: list[tuple[str, tuple[str, ...]]] = []
    discovery_only: list[str] = []
    own = _alias_re(component.aliases) if component.aliases else None
    mine = {a.lower() for a in component.aliases}
    others = [s for s in known_subjects if s.lower() not in mine]
    other_re = _alias_re(others) if others else None
    cue_res = [re.compile(c, re.IGNORECASE) for c in spec.cues] if spec else []
    for item in items:
        prov, problems = parse_provenance(item.ref, item.provenance, now, policy)
        if prov is None:
            excluded.append((item.ref, tuple(problems)))
            continue
        auth_problems = check_authorization(prov, auths.get(item.ref), now, policy)
        if auth_problems:
            excluded.append((item.ref, tuple(auth_problems)))
            continue
        if looks_like_instruction(item.text):
            excluded.append((item.ref, ("instruction_bearing",)))
            continue
        if spec is None or own is None:
            discovery_only.append(item.ref)
            continue
        got_fact = False
        item_ambiguous: str | None = None
        for sentence in (s.strip() for s in _SENT.split(item.text)):
            # the subject may come from the record's own title ("Cedar architecture", "Vesper planning") when the sentence itself names no other subject
            named = own.search(sentence) or (own.search(item.title or "") and not (other_re and other_re.search(sentence)))
            if not sentence or not named or not any(c.search(sentence) for c in cue_res):
                continue
            if _HEDGE.search(sentence):
                item_ambiguous = item_ambiguous or "hedged"
                continue
            if other_re and not spec.co_subjects_ok and other_re.search(sentence):
                item_ambiguous = item_ambiguous or "competing_subject"
                continue
            if spec.kind == "existence":
                neg = bool(spec.negation and re.search(spec.negation, sentence, re.IGNORECASE))
                pres = bool(spec.presence and re.search(spec.presence, sentence, re.IGNORECASE))
                if neg and pres:
                    item_ambiguous = item_ambiguous or "contradictory_polarity"
                elif neg or pres:
                    facts.append(AdmittedFact(component.id, item.ref, "", "negates" if neg else "asserts", _fact_scope(sentence, prov, item.title, now), sentence, prov, _token=_TOKEN))
                    got_fact = True
                continue  # neither: a mention that does not say
            distinct = list(dict.fromkeys(_values(spec.kind, sentence, [*component.aliases, *others])))
            if not distinct:
                continue  # related, asserts no value
            if _NEGATED_VALUE.search(sentence):
                item_ambiguous = item_ambiguous or "negated_value"
                continue
            if len(distinct) > 1 and not spec.many:
                item_ambiguous = item_ambiguous or "multiple_values"
                continue
            scope = _fact_scope(sentence, prov, item.title, now)
            facts.extend(AdmittedFact(component.id, item.ref, v, "asserts", scope, sentence, prov, _token=_TOKEN) for v in distinct)
            got_fact = True
        if item_ambiguous:
            ambiguous.append((item.ref, item_ambiguous))  # an unreadable part never becomes an assertion; any readable part stays admitted
        elif not got_fact:
            discovery_only.append(item.ref)
    return AdmissionResult(component.id, tuple(facts), tuple(ambiguous), tuple(excluded), tuple(discovery_only))


def find_supersessions(items: Collection[DiscoveryItem], auths: Mapping[str, AuthDecision], *, now: datetime, policy: AdmissionPolicy) -> frozenset[tuple[str, str]]:
    """(newer_ref, older_ref) pairs that an AUTHORITATIVE, authorised, well-formed record explicitly states ("supersedes <ref>"). Document timestamps, retrieval times and third-party statements never count.
    Mutual claims cancel."""
    valid = {}
    for it in items:
        prov, _ = parse_provenance(it.ref, it.provenance, now, policy)
        if prov is not None and not check_authorization(prov, auths.get(it.ref), now, policy) and not looks_like_instruction(it.text):
            valid[it.ref] = (it, prov)
    pairs = set()
    for ref, (it, prov) in valid.items():
        if prov.author_class not in AUTHORITATIVE:
            continue
        for m in _SUPERSEDES.finditer(it.text):
            target = m.group(1).rstrip(".")
            if target in valid and target != ref:
                pairs.add((ref, target))
    return frozenset(p for p in pairs if (p[1], p[0]) not in pairs)
