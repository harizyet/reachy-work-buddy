"""Phase 31: the deterministic checks that decide whether a finding is labelled `stated` or `uncertain`, and that keep speaker labels out of finding text.

Everything here reads observable transcript evidence only: the quote, the lines that follow it, and the item's own words. No model, no score. The label is a check, not proof, and a finding
that fails it is kept and shown as a weaker suggestion: the owner decides. The speech-to-text output is not required to contain punctuation (a question mark is one hint, never a need)."""

from __future__ import annotations

import re

from companion_core.meeting_analysis.models import ItemKind, Support
from companion_core.notepad_processing.models import normalise

COVERAGE = 0.6  # share of the item's own content words that the quote also contains
ANSWER_LOOKAHEAD = 2  # transcript lines after the quote that are read for an answer

# Wording that turns a sentence into a suggestion, an idea or a condition instead of an agreement or a promise.
_HEDGE = re.compile(
    r"\b(?:maybe|perhaps|might|could|probably|possibly|i think|i guess|i suppose|i feel|not sure|what if|how about|why don't|suggest(?:ed|ion|ions)?|propos(?:e|ed|al)|idea|"
    r"if (?:we|you|i|they|he|she)|would be (?:good|nice|better|great)|in principle|at some point|sometime|eventually|i can|we should consider|worth (?:trying|considering))\b",
    re.IGNORECASE,
)
# An agreement: someone settles or accepts something. "we will" counts only without a hedge in the same quote.
_AGREEMENT = re.compile(
    r"\b(?:agree[ds]?|decid(?:e|ed|ing)|decision|settled|approved?|confirmed?|go(?:ing)? with|go ahead|that's the plan|sounds good|let's (?:go|do|use|move|stick|proceed)|"
    r"we(?:'ll| will| are going to|'re going to)|so we're (?:doing|going)|final(?:ly)?)\b",
    re.IGNORECASE,
)
# A promise or a request aimed at a person: not a need, an idea or a description.
_COMMITMENT = re.compile(
    r"\b(?:i will|i'll|we will|we'll|i'm going to|we're going to|going to|gonna|let me|can you|could you|would you|please|send me|send (?:it|that|the \w+) to me|give me|get back to|follow up|reach out|"
    r"i(?:'ve| have) asked|i(?:'m| am) asking|action item|by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week|the end of))\b|\bwill\s+(?!be\b)\w+",
    re.IGNORECASE,
)
_INTERROGATIVE = re.compile(
    r"^(?:(?:and|so|but|okay|ok|then|now|well|also)[,\s]+)*(?:(?:who|whom|whose|what|when|where|why|how|which)\b|(?:do|does|did|is|are|was|were|can|could|will|would|should|shall|have|has|had|may|might)\s+\w+)",
    re.IGNORECASE,
)
_UNRESOLVED = re.compile(
    r"\b(?:nobody knows|no one knows|(?:i|we) (?:don't|do not|still don't) know|not sure (?:if|whether|who|what|when|where|why|how)|unclear (?:if|whether|who|what|when|where|why|how)|"
    r"wondering (?:if|whether|who|what|when|where|why|how)|(?:yet )?to be (?:decided|determined|confirmed)|open question|any idea|how about|what about)\b",
    re.IGNORECASE,
)
# The start of a reply. The first lines after a question are read for these.
_ANSWER = re.compile(
    r"^\W*(?:yes|yeah|yep|yup|no|nope|nah|sure|correct|exactly|of course|definitely|absolutely|uh-huh|mm-hmm|not really|that's right|that is right|that's correct|it's not|it is not|"
    r"we (?:do|don't|did|didn't|already|haven't|have not)|i (?:do|don't|did|didn't|think so|believe so)|probably not|probably yes|the answer)\b",
    re.IGNORECASE,
)
_STOP = frozenset(["that", "this", "with", "from", "have", "will", "would", "should", "could", "about", "there", "their", "they", "them", "then", "than", "what", "when", "where", "which", "while", "into", "over", "also", "been", "being", "were", "your", "ours", "just", "like", "some", "more", "most", "only", "very"])

_LABEL_VERBS = (
    r"(?:is to|are to|will|would|should|must|needs to|need to|has to|have to|plans to|plan to|offers to|offered to|wants to|want to|is going to|are going to|agrees to|agreed to|volunteers to|can|could)"
)
_LABEL_SAYS = r"(?:says|said|states|stated|mentions|mentioned|believes|thinks|notes|noted|asks|asked|suggests|suggested|explains|explained|reports|wonders|wondered|expects|feels|points out)"


def coverage(text: str, quote: str) -> float:
    words = {w[:5] for w in normalise(text).split() if len(w) >= 4 and w not in _STOP}
    if not words:
        return 1.0
    have = {w[:5] for w in normalise(quote).split()}
    return len(words & have) / len(words)


def _sentences(quote: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", quote) if s.strip()]


def is_question(quote: str) -> bool:
    """A real question is a sentence of at least four words that is built as one (interrogative word, inverted auxiliary, or an explicit "nobody knows who"), with or without a question mark.
    Two-word fragments and tags ("right?", "what about you?") are not."""
    if _UNRESOLVED.search(quote) and len(quote.split()) >= 4:
        return True
    return any(len(s.split()) >= 4 and (_INTERROGATIVE.match(s) is not None or s.endswith("?")) for s in _sentences(quote))


def is_answered(quote: str, following: list[str]) -> bool:
    """Observable answers: a reply inside the quote right after its question, or a reply wording at the start of the next lines."""
    sentences = _sentences(quote)
    for i, s in enumerate(sentences[:-1]):
        if (s.endswith("?") or _INTERROGATIVE.match(s)) and _ANSWER.match(sentences[i + 1]):
            return True
    return any(_ANSWER.match(line) for line in following[:ANSWER_LOOKAHEAD])


def assess(kind: ItemKind, text: str, quoted: str, ambiguity: list[str], following: list[str]) -> Support:
    """STATED needs wording of the right kind in the quote, no hedge on a decision or a promise, an unanswered question, and the item's own words mostly in the quote. Reasons go to `ambiguity`."""
    ok = True
    if kind is ItemKind.DECISION:
        if not _AGREEMENT.search(quoted):
            ambiguity.append("the quote shows no clear agreement: this may be discussion, a fact or a suggestion rather than a decision")
            ok = False
        elif _HEDGE.search(quoted):
            ambiguity.append("the quote is hedged or reads as a proposal (maybe, could, I think, what if): it may not have been agreed")
            ok = False
    elif kind is ItemKind.ACTION:
        if not _COMMITMENT.search(quoted):
            ambiguity.append("the quote has no clear promise or request: it may be a need, an idea or a description rather than an agreed action")
            ok = False
        elif _HEDGE.search(quoted):
            ambiguity.append("the quote is hedged or conditional (maybe, could, if you, I can): it may be an offer or an idea rather than a commitment")
            ok = False
    elif kind is ItemKind.OPEN_QUESTION:
        if not is_question(quoted):
            ambiguity.append("the quote does not read as a real question (too short, or not built as one): check that it was asked")
            ok = False
        elif is_answered(quoted, following):
            ambiguity.append("the next lines appear to answer it: check whether it is still open")
            ok = False
    if coverage(text, quoted) < COVERAGE:
        ambiguity.append("the wording goes beyond what the quote says: read the quote, not just the summary")
        ok = False
    return Support.STATED if ok else Support.UNCERTAIN


def scrub_labels(text: str, quoted: str, labels: set[str]) -> tuple[str, bool]:
    """Take speaker labels ("Speaker 2", an owner-given speaker name) out of a finding's wording unless the quote itself contains them: "Speaker 1 will send the report" becomes "Send the
    report", "Speaker 2 asks whether X" becomes "Whether X", and any other mention becomes "a participant". Returns the new text and whether it changed."""
    names = sorted({re.escape(label) for label in labels if label} | {r"Speaker\s+\d+"}, key=len, reverse=True)
    label = "(?:" + "|".join(names) + ")"
    original = text

    def foreign(match: re.Match) -> bool:
        return re.search(rf"(?<!\w){re.escape(match.group(0))}(?!\w)", quoted, re.IGNORECASE) is None

    lead = re.match(rf"^({label})\s+(?:{_LABEL_VERBS}\s+(?P<act>.+)|{_LABEL_SAYS}\s+(?:that\s+|whether\s+|if\s+)?(?P<said>.+))$", text, re.IGNORECASE)
    if lead and re.search(rf"(?<!\w){re.escape(lead.group(1))}(?!\w)", quoted, re.IGNORECASE) is None:
        rest = (lead.group("act") or lead.group("said")).strip()
        text = rest[0].upper() + rest[1:]
    text = re.sub(rf"(?<!\w){label}(?!\w)", lambda m: "a participant" if foreign(m) else m.group(0), text, flags=re.IGNORECASE)
    text = text[0].upper() + text[1:] if text else text
    return text, text != original
