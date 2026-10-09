"""The conflict-omission detector (Phase 44E follow-up, development only; not an answer gate and not on any live path).

Given the question, a reply and the evidence items it was shown, find evidence items that disagree about a quantity the question bears on and report whether the reply states
every side. Two versions, so the second can be measured against the first:

  v1  every pair of items that share two content words and give different quantities of one kind (hours range, minutes, times ...) must both be reflected in the reply.
  v2  v1 restricted to what the question is about and what is not explained by time:
      - topical: both items must share at least two content words with the question (a disagreement about something the question did not ask is not an omission);
      - scoped questions ("according to the runbook", "the archived version", "used to") name a source or a version, so they are not flagged;
      - temporal: an item marked archived, old, previous, retired or "raised from X" is an older value; a pair that differs only because of an older item is reported as temporal,
        and the reply need not repeat the older value;
      - identifies the disagreeing items by id.
Quantities and number words are normalised ("thirty minutes", "30-minute", "9 to 5", "9-5", "nine to five")."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from companion_core.knowledge.context import _NUMWORDS, _keywords

_SCOPE = re.compile(
    r"\b(?:according to|in the (?:runbook|doc|docs|document|note|meeting|archived|old|original)|the (?:runbook|doc|docs|document|note|meeting|archive\w*)\b[^.?]{0,12}\b(?:say|says|state|states|list|lists)\b|"
    r"archived|previously|originally|once|in march|at first|earlier version|old version)\b", re.IGNORECASE)
_OLDER = re.compile(r"\b(?:archived|old|older|previous|previously|retired|superseded|deprecated|v1|raised from|used to|formerly|as of march)\b", re.IGNORECASE)
_UNITS = {"minute": "minute", "min": "minute", "hour": "hour", "day": "day", "week": "week", "month": "month", "time": "count", "retry": "count", "retrie": "count",
          "try": "count", "trie": "count", "attempt": "count", "%": "percent"}
_WORDS = {w.replace("-", " "): v for w, v in _NUMWORDS.items()}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(w) for w in _WORDS), key=len, reverse=True)) + r")"
_QTY = re.compile(_NUM + r"[\s-]+(?:(?:failed|more|full|extra)\s+)?(minutes?|mins?|hours?|days?|weeks?|months?|times|retries|tries|attempts)\b|"
                  r"\b(?:limit|cap|maximum|max)\s+(?:is|of|was|to)?\s*" + _NUM + r"\b", re.IGNORECASE)
_RANGE = re.compile(_NUM + r"\s*(?:am|pm)?\s*(?:to|-|until)\s*" + _NUM + r"\s*(?:am|pm)?\b", re.IGNORECASE)
_UNIT_WORDS = {"minute", "minutes", "hour", "hours", "times", "retries", "tries", "attempts", "days", "weeks", "months"}
_DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\[[^\]]*\]|\bE\d+\b|\b\d{1,2}:\d{2}\b|\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)


def _stem(word: str) -> str:
    return word[:4]


def _num(token: str) -> float:
    t = token.lower().replace("-", " ")
    return float(_WORDS.get(t, t))


def _topic(text: str) -> set[str]:
    return {_stem(w) for w in _keywords(text) if w not in _UNIT_WORDS}


def quantities(text: str) -> set[tuple[str, float, float | None]]:
    """(kind, low, high) for each quantity: durations, counts and hour ranges, with number words, hyphens and "limit is five" understood."""
    low = text.replace("\u2013", "-")
    out = set()
    for m in _RANGE.finditer(low):
        a, b = _num(m.group(1)), _num(m.group(2))
        if a <= 24 and b <= 24:
            out.add(("range", a, b))
    cleaned = _RANGE.sub(" ", low)
    for m in _QTY.finditer(cleaned):
        if m.group(1):
            unit = _UNITS.get(m.group(2).lower().rstrip("s"), None) or _UNITS.get(m.group(2).lower()[:-3] + "ie")
            out.add((unit or "count", _num(m.group(1)), None))
        else:
            out.add(("count", _num(m.group(3)), None))
    return out


def _canonical_numbers(text: str) -> set[str]:
    """All numbers in a reply as digit strings, ignoring dates, times and citation ids: digits, number words, hyphenated forms."""
    low = _DATE_LIKE.sub(" ", text).lower().replace("-", " ")
    nums = set(re.findall(r"\b\d+\b", low))
    for word, digits in _WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            nums.add(str(int(digits)))
    if re.search(r"\bhalf an hour\b", low):
        nums.add("30")
        low = re.sub(r"\bhalf an hour\b", " ", low)
    if re.search(r"\ban hour\b|\bone hour\b", low):
        nums.add("60")
    return nums


def _context(text: str, qty_text: str | None = None) -> set[str]:
    """Words around the quantities in an item (within five words), normalised ("roll back" is "rollback"): what the number is a number of."""
    norm = re.sub(r"\broll back\b", "rollback", text.lower())
    tokens = re.findall(r"[a-z0-9-]+", norm)
    marks = [i for i, t in enumerate(tokens) if re.fullmatch(r"\d+(?:\.\d+)?|" + "|".join(re.escape(w.replace(" ", "-")) for w in _WORDS), t)]
    near = set()
    for i in marks:
        near |= {_stem(t) for t in tokens[max(0, i - 5): i + 6] if len(t) >= 4 and t not in _STOPWORDS and t not in _UNIT_WORDS}
    return near


_STOPWORDS = {"this", "that", "with", "from", "have", "been", "were", "will", "not", "but", "you", "your", "into", "than", "then", "they", "them", "their", "there", "which", "when", "what", "where", "who", "after", "before", "while", "about", "over", "under", "also", "each", "other", "such", "only", "same", "more", "most", "some", "any", "can", "could", "would", "should", "may", "might", "records", "record", "owner", "evidence", "provided", "based", "within"}


@dataclass
class Detection:
    flag: bool = False
    pairs: list[tuple[str, str]] = field(default_factory=list)  # items that disagree and whose other side the reply omitted
    temporal: list[tuple[str, str]] = field(default_factory=list)  # disagreements explained by an older item (reported, not flagged)
    scoped: bool = False


def _sides(a_text: str, b_text: str):
    qa, qb = quantities(a_text), quantities(b_text)
    kinds = {q[0] for q in qa} & {q[0] for q in qb}
    out = []
    for kind in kinds:
        va, vb = {q for q in qa if q[0] == kind}, {q for q in qb if q[0] == kind}
        if va != vb:
            out.append((va - vb, vb - va))
    return out


def _values_in(reply: str, values) -> bool:
    low = _canonical_numbers(reply)
    for _, lo, hi in values:
        want = {str(int(lo))} | ({str(int(hi))} if hi else set())
        if want <= low:
            return True
    return False


def detect(question: str, reply: str, items: dict[str, tuple[str, str]], version: str = "v2") -> Detection:
    """`items`: evidence id -> (label, text) where the label is the item's info string (title, date, kind). `v1` reproduces the earlier detector (aq.verify.conflict_check);
    `v3` is v2 with the topical test relaxed (each item need share only one word with the question if the two items share three context words)."""
    if version == "v1":
        from aq.verify import conflict_check

        flags = conflict_check(question, reply, {eid: text for eid, (_, text) in items.items()})
        return Detection(flag=bool(flags))
    det = Detection(scoped=bool(_SCOPE.search(question)))
    if det.scoped or len(items) < 2:
        return det
    qtopic = _topic(question)
    ids = list(items)
    contexts = {eid: _context(text) for eid, (_, text) in items.items()}
    common = {w for w in set().union(*contexts.values()) if sum(w in c for c in contexts.values()) > 0.6 * len(items)} if len(items) >= 4 else set()
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            (la, ta), (lb, tb) = items[a], items[b]
            mutual = (contexts[a] & contexts[b]) - common
            need = 1 if (version == "v3" and len(mutual) >= 3) else 2
            if len(_topic(ta) & qtopic) < need or len(_topic(tb) & qtopic) < need:
                continue  # the question is not about both items
            if not mutual:
                continue  # the two numbers are numbers of different things
            for only_a, only_b in _sides(ta, tb):
                if not only_a or not only_b:
                    continue
                if bool(_OLDER.search(la + " " + ta)) != bool(_OLDER.search(lb + " " + tb)):
                    det.temporal.append((a, b))  # one item is an older value: the difference is explained by time
                    continue
                if not (_values_in(reply, only_a) and _values_in(reply, only_b)):
                    det.pairs.append((a, b))
    det.flag = bool(det.pairs)
    return det
