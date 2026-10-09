"""C5: independent validation of atomic claims against the evidence the turn actually had. A model-generated citation or quote is NOT proof; every claim must pass four checks computed by code:
  1 source identity   the cited id exists in this turn's evidence manifest and resolves to a logical source reference
  2 authorization     that item is authorised for this turn (recomputed from the manifest, never from model text)
  3 exact evidence    the quote is a non-trivial, verbatim span of that exact item's text; offsets are computed here
  4 supported relation the claim's names, numbers and models appear in the quote or in the item's own title/speaker context, and a relation cue in the claim appears in the quote
An empty or trivial quote never supports a claim. A claim that fails any check is dropped (never repaired, never regenerated)."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from companion_core.knowledge.grounding.claims import QUOTE_MIN_CHARS
from companion_core.knowledge.grounding.relations import RELATIONS
from companion_core.knowledge.sufficiency import _STOP, _WORD, _stem

_TOKEN = re.compile(r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*|\b\d+\b")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Evidence:
    """One item as the turn presented it. `text` is the stored text; `context` its title, section and speaker; `authorized` the code-side result of the access rules for this turn."""

    refs: tuple[str, ...]
    text: str
    context: str
    authorized: bool


@dataclass
class Verdict:
    accepted: list[dict] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (claim index, reason)
    spans: dict[int, tuple[str, int, int]] = field(default_factory=dict)  # claim index -> (item id, start, end) computed here


def _norm(s: str) -> str:
    return _WS.sub(" ", html.unescape(s)).strip().lower()


def _cues(claim: str) -> set[str]:
    """Relation cue stems the claim itself uses (from the written lexicon), so a claim that says 'owns' needs 'owns' or an equivalent in the quote."""
    low = claim.lower()
    found: set[str] = set()
    for spec in RELATIONS.values():
        for cue in spec["assertion"]:
            if " " not in cue and _stem(cue) in {_stem(w) for w in _WORD.findall(low)}:
                found.add(_stem(cue))
    return found


def validate(claims: list[dict], evidence: Mapping[str, Evidence]) -> Verdict:
    v = Verdict()
    for i, c in enumerate(claims):
        eid, claim, quote = str(c.get("evidence", "")), str(c.get("claim", "")), str(c.get("quote", ""))
        item = evidence.get(eid)
        if item is None or not item.refs:
            v.rejected.append((i, "unknown_source"))
            continue
        if not item.authorized:
            v.rejected.append((i, "unauthorized_source"))
            continue
        q = _norm(quote)
        if len(q) < QUOTE_MIN_CHARS or len(q.split()) < 3:
            v.rejected.append((i, "trivial_quote"))
            continue
        hay = _norm(item.text)
        pos = hay.find(q)
        if pos < 0:
            v.rejected.append((i, "quote_not_in_item"))
            continue
        support = f"{q} {_norm(item.context)}"
        first = claim.strip().split(" ")[0] if claim.strip() else ""
        toks = [m.group(0) for m in _TOKEN.finditer(claim) if not (m.start() == claim.find(first) and m.group(0) == first.strip(".,;:") and m.group(0)[0].isupper() and not m.group(0)[0].isdigit() and "-" not in m.group(0))]
        missing = [t for t in toks if t.lower() not in support and t.lower() not in _STOP and t.lower() not in {"i", "the", "a", "an"}]
        if missing:
            v.rejected.append((i, "claim_value_not_in_span"))
            continue
        cues = _cues(claim)
        if cues and not (cues & {_stem(w) for w in _WORD.findall(q)}):
            v.rejected.append((i, "relation_not_in_span"))
            continue
        v.accepted.append(c)
        v.spans[i] = (eid, pos, pos + len(q))
    return v
