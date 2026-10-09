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
    AttendeeRecord,
    AuthDecision,
    AuthorClass,
    Component,
    DiscoveryItem,
    FactScope,
    Provenance,
    RelationSpec,
    SpeakerSegment,
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
    allow_context: bool = True  # the bounded one-sentence subject context; switchable so its effect can be ablated
    # Authoritative equivalences the caller supplies: lowercase noun phrases that ARE the subject for admission purposes ("ferry queue schedule" is not one unless an authority says so). Empty by default.
    equivalences: frozenset[str] = frozenset()
    qualified_object_check: bool = True  # switchable only so the tightening can be measured against the previous behaviour


@dataclass(frozen=True)
class AdmissionResult:
    component_id: str
    facts: tuple[AdmittedFact, ...]
    ambiguous: tuple[tuple[str, str], ...]  # (ref, reason): authorised and well-formed but not safely readable; never an assertion
    excluded: tuple[tuple[str, tuple[str, ...]], ...]  # (ref, reasons): audit only; a reply must never reveal these
    discovery_only: tuple[str, ...]  # authorised and well-formed, asserting nothing for this component
    ambiguous_scopes: tuple[FactScope, ...] = ()  # the time scope of each ambiguous sentence, parallel to `ambiguous`


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


_FIRST_PERSON = re.compile(r"^\s*I(?:['’]ll| will| am going to|['’]m going to| have| will be)\b")
_PERSON_NAME = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$")
_TEXT_MAX_WORDS = 10
_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _units(text: str) -> list[tuple[str, int]]:
    """(sentence, paragraph id). A blank line, a heading line ("# ...") and every list item start a new paragraph, so the one-sentence context lookback never crosses them."""
    out: list[tuple[str, int]] = []
    para = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            para += 1
            continue
        if stripped.startswith("#"):
            para += 1
            continue
        if stripped[0] in "-*•":
            para += 1
            stripped = stripped.lstrip("-*• ").strip()
        out.extend((s.strip(), para) for s in re.split(r"(?<=[.!?])\s+", stripped) if s.strip())
    return out


def _text_values(spec: RelationSpec, sentence: str) -> list[str] | None:
    """Conservative free-text value: only what the relation's reviewed `text_pattern` captures as group `value`, short, unhedged. None: a match that cannot be trusted (too long, hedged)."""
    found = []
    for m in re.finditer(spec.text_pattern or "(?!)", sentence, re.IGNORECASE):
        raw = m.group("value").strip(" ,;:")
        if not raw or len(raw.split()) > _TEXT_MAX_WORDS or _HEDGE.search(raw) or _NEGATED_VALUE.search(raw) or re.search(r"[.!?]", raw):
            return None
        found.append(raw)
    return found


_OBJECT_FUNCTION_WORDS = frozenset({"the", "a", "an", "of", "for", "this", "that", "to", "s"})


def _object_covered(sentence: str, component: Component, spec: RelationSpec) -> bool:
    """A first-person statement answers the relation only if everything after its verb is the subject, the relation's own words or function words. "I will own the Conduit stream schedule" is about the
    schedule, not about the Conduit stream, so it asserts nothing for "who owns the Conduit stream"."""
    match = _FIRST_PERSON.match(sentence)
    rest = re.findall(r"[A-Za-z0-9]+", sentence[match.end():] if match else sentence)
    allowed = set(_OBJECT_FUNCTION_WORDS)
    for phrase in (component.subject, *component.aliases, spec.words, *spec.object_words):
        allowed |= {w.lower() for w in re.findall(r"[A-Za-z0-9]+", phrase)}
    return all(tok.lower() in allowed for tok in rest[1:])  # rest[0] is the verb


_NP_BOUNDARY = frozenset(["is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "will", "would", "can", "could", "may", "might", "shall", "should", "and", "or", "but", "nor", "of", "for", "in", "on", "at", "by", "with", "to", "from", "as", "than", "that", "this", "these", "those", "the", "a", "an", "it", "its", "their", "his", "her", "not", "no", "also", "still", "now", "currently", "then", "so", "who", "which", "when", "where", "while", "after", "before", "until", "since", "because", "if", "up", "down", "out", "over", "under", "through", "into", "about", "per", "via", "each", "every", "all", "both"])


def _qualified_object(sentence: str, own: re.Pattern, component: Component, spec: RelationSpec, policy: AdmissionPolicy, cue_res: list[re.Pattern]) -> bool:
    """True when EVERY mention of the subject in the sentence is the beginning of a longer qualified object ("owns the Ferry queue **schedule**", "the Ferry queue **schedule** is owned by", "the Ferry queue's
    **runbook**"), so the sentence is about the schedule, not about the Ferry queue. Two structural cases only, no coreference and no parsing:
      object position (a relation cue precedes the subject): a head noun that is not a boundary or relation word follows the subject, or a possessive does;
      subject position: such a word is followed by a copula/auxiliary, punctuation, the end, or a relation word.
    A caller-supplied authoritative equivalence (`policy.equivalences`) lifts the rule for that exact phrase."""
    subject_words = {w.lower() for phrase in (component.subject, *component.aliases) for w in re.findall(r"[A-Za-z0-9]+", phrase)}
    relation_words = {w.lower() for phrase in (spec.words, *spec.object_words) for w in re.findall(r"[A-Za-z0-9]+", phrase)}
    stems = [s.lower() for c in spec.cues for s in re.findall(r"[A-Za-z]{3,}", c)]

    def is_relation(word: str) -> bool:
        return word in relation_words or any(word.startswith(s) for s in stems)

    qualified_any = False
    for m in own.finditer(sentence):
        toks = re.findall(r"['’]s\b|[A-Za-z0-9][A-Za-z0-9\-]*|[^\sA-Za-z0-9]", sentence[m.end():])
        i = 0
        phrase = [m.group(0).lower()]
        while i < len(toks) and toks[i].lower() in subject_words:  # the rest of the subject's own name ("queue" in "Ferry queue")
            phrase.append(toks[i].lower())
            i += 1
        if i >= len(toks):
            return False
        tok = toks[i]
        if tok in ("'s", "’s"):
            nxt = toks[i + 1].lower() if i + 1 < len(toks) else ""
            if nxt and nxt not in _NP_BOUNDARY and not is_relation(nxt) and " ".join([*phrase, nxt]) not in policy.equivalences:
                qualified_any = True
                continue
            return False
        low = tok.lower()
        if not (tok[0].isalnum()) or low in _NP_BOUNDARY or is_relation(low):
            return False
        phrase.append(low)
        if " ".join(phrase) in policy.equivalences:
            return False
        cue_before = any(c.search(sentence[: m.start()]) for c in cue_res)
        if cue_before:
            qualified_any = True
            continue
        # subject position: a run of up to four plain words after the subject that ends at a boundary, punctuation, the end or a relation word is a qualifier ("rollout plan belongs", "schedule is owned");
        # a capitalised or numeric token inside the run means a verb followed by its value ("serves Swift-20B"), which is not a qualifier
        run = [tok]
        j = i + 1
        while j < len(toks) and len(run) <= 4 and toks[j][0].isalnum() and toks[j].lower() not in _NP_BOUNDARY and not is_relation(toks[j].lower()):
            run.append(toks[j])
            j += 1
        if len(run) > 4 or any(w[0].isupper() or any(ch.isdigit() for ch in w) for w in run[1:]):
            return False
        qualified_any = True
    return qualified_any


@dataclass(frozen=True)
class _Amb:
    reason: str
    scope: FactScope


def admit(component: Component, items: Collection[DiscoveryItem], auths: Mapping[str, AuthDecision], *, now: datetime, spec: RelationSpec | None, known_subjects: Collection[str],
          policy: AdmissionPolicy, structured: Collection[AttendeeRecord | SpeakerSegment] = ()) -> AdmissionResult:
    facts: list[AdmittedFact] = []
    ambiguous: list[tuple[str, str, FactScope]] = []
    excluded: list[tuple[str, tuple[str, ...]]] = []
    discovery_only: list[str] = []
    own = _alias_re(component.aliases) if component.aliases else None
    mine = {a.lower() for a in component.aliases}
    others = [s for s in known_subjects if s.lower() not in mine]
    other_re = _alias_re(others) if others else None
    cue_res = [re.compile(c, re.IGNORECASE) for c in spec.cues] if spec else []

    def fact(ref, value, polarity, scope, sentence, prov, binding):
        facts.append(AdmittedFact(component.id, ref, value, polarity, scope, sentence, prov, binding, _token=_TOKEN))

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
        item_amb: _Amb | None = None
        units = _units(item.text)
        for k, (sentence, para) in enumerate(units):
            direct = bool(own.search(sentence))
            titled = (not direct) and bool(own.search(item.title or "")) and not (other_re and other_re.search(sentence))
            # bounded context: the ONE previous sentence of the same paragraph names this subject and no other, and this sentence names no subject at all
            context_prev = None
            if policy.allow_context and not direct and not titled and k > 0 and not (other_re and other_re.search(sentence)):
                prev, prev_para = units[k - 1]
                if prev_para == para and own.search(prev) and not (other_re and other_re.search(prev)) and not _HEDGE.search(prev):
                    context_prev = prev
            if not (direct or titled or context_prev) or not any(c.search(sentence) for c in cue_res):
                continue
            binding = "sentence" if direct else "title" if titled else "context"
            if direct and policy.qualified_object_check and spec.kind != "existence" and _qualified_object(sentence, own, component, spec, policy, cue_res):
                continue  # about a qualified object of the subject (its schedule, plan, runbook...), not about the subject: asserts nothing for it
            evidence = f"{context_prev} {sentence}" if context_prev else sentence
            scope = _fact_scope(evidence, prov, item.title, now)
            if _HEDGE.search(sentence):
                item_amb = item_amb or _Amb("hedged", scope)
                continue
            probe = sentence
            if spec.kind == "text" and spec.text_pattern:
                # the captured phrase is the value, so another entity named INSIDE it ("reviewing the Sluice settings") is not a competing subject; the rest of the sentence still is checked
                probe = re.sub(spec.text_pattern, lambda m: m.group(0).replace(m.group("value"), " "), sentence, flags=re.IGNORECASE)
            if other_re and not spec.co_subjects_ok and other_re.search(probe):
                item_amb = item_amb or _Amb("competing_subject", scope)
                continue
            if spec.kind == "existence":
                neg = bool(spec.negation and re.search(spec.negation, sentence, re.IGNORECASE))
                pres = bool(spec.presence and re.search(spec.presence, sentence, re.IGNORECASE))
                if neg and pres:
                    item_amb = item_amb or _Amb("contradictory_polarity", scope)
                elif neg or pres:
                    fact(item.ref, "", "negates" if neg else "asserts", scope, evidence, prov, binding)
                    got_fact = True
                continue  # neither: a mention that does not say
            if spec.kind == "text":
                vals = _text_values(spec, sentence)
                if vals is None:
                    item_amb = item_amb or _Amb("unreadable_text_value", scope)
                    continue
                distinct = list(dict.fromkeys(vals))
            else:
                distinct = list(dict.fromkeys(_values(spec.kind, sentence, [*component.aliases, *others])))
            if not distinct:
                continue  # related, asserts no value
            if _NEGATED_VALUE.search(sentence):
                item_amb = item_amb or _Amb("negated_value", scope)
                continue
            if len({_ARTICLE.sub("", d).casefold() for d in distinct}) > 1 and not spec.many:
                item_amb = item_amb or _Amb("multiple_values", scope)
                continue
            for v in distinct:
                fact(item.ref, v, "asserts", scope, evidence, prov, binding)
            got_fact = True
        if item_amb:
            ambiguous.append((item.ref, item_amb.reason, item_amb.scope))  # an unreadable part never becomes an assertion; any readable part stays admitted
        elif not got_fact:
            discovery_only.append(item.ref)

    # authoritative structured input: attendee lists and speaker-attributed segments (a reviewed speaker map). The same provenance and authorisation checks apply, and the author must be authoritative.
    for rec in structured:
        prov, problems = parse_provenance(rec.ref, rec.provenance, now, policy)
        if prov is None:
            excluded.append((rec.ref, tuple(problems)))
            continue
        auth_problems = check_authorization(prov, auths.get(rec.ref), now, policy)
        if auth_problems:
            excluded.append((rec.ref, tuple(auth_problems)))
            continue
        if prov.author_class not in AUTHORITATIVE:
            excluded.append((rec.ref, ("structured_input_not_authoritative",)))
            continue
        if spec is None or own is None or spec.structured is None:
            discovery_only.append(rec.ref)
            continue
        scope = _fact_scope(rec.title or "", prov, rec.title or "", now)
        if isinstance(rec, AttendeeRecord) and spec.structured == "attendees":
            if not own.search(rec.title or ""):
                discovery_only.append(rec.ref)
                continue
            valid = [a for a in rec.attendees if isinstance(a, str) and _PERSON_NAME.match(a.strip())]
            if len(valid) != len(rec.attendees):
                ambiguous.append((rec.ref, "attendee_name_unparsable", scope))
            for name in dict.fromkeys(a.strip() for a in valid):
                fact(rec.ref, name, "asserts", scope, f"Attendees of {rec.title}: {name}", prov, "structured")
            if not valid and not rec.attendees:
                discovery_only.append(rec.ref)  # an empty list is not evidence that nobody attended
        elif isinstance(rec, SpeakerSegment) and spec.structured == "speaker":
            if looks_like_instruction(rec.text):
                excluded.append((rec.ref, ("instruction_bearing",)))
                continue
            sentence = rec.text.strip()
            named = own.search(sentence) or (own.search(rec.title or "") and not (other_re and other_re.search(sentence)))
            if not _FIRST_PERSON.match(sentence) or not named or not any(c.search(sentence) for c in cue_res):
                discovery_only.append(rec.ref)
                continue
            if _HEDGE.search(sentence) or _NEGATED_VALUE.search(sentence):
                ambiguous.append((rec.ref, "hedged", scope))
            elif not _object_covered(sentence, component, spec):
                discovery_only.append(rec.ref)  # a statement about another object of the same subject
            elif not (isinstance(rec.speaker, str) and _PERSON_NAME.match(rec.speaker.strip())):
                ambiguous.append((rec.ref, "speaker_unresolved", scope))
            else:
                fact(rec.ref, rec.speaker.strip(), "asserts", _fact_scope(sentence, prov, rec.title or "", now), sentence, prov, "speaker")
        else:
            discovery_only.append(rec.ref)
    return AdmissionResult(component.id, tuple(facts), tuple((r, why) for r, why, _ in ambiguous), tuple(excluded), tuple(discovery_only), tuple(s for _, _, s in ambiguous))


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
