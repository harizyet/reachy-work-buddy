"""Key-terms candidate generation for transcript corrections (Phase 41, ADR 0030).

Deterministic half of the resolver: find short spans of the transcript that
look like a mis-hearing of a term the owner supplied, and rank the terms for
each span. A model then only chooses among those candidates, instead of
inventing a correction from its own knowledge (the 7B model cannot do that:
it never connects "germanite" to "Gemini")."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
MAX_SPAN_WORDS = 3
MIN_LETTERS = 4

# Applied in order to the letters-only lowercase form. A light phonetic key, not full Metaphone: enough that
# "germanite" and "Gemini" both reduce to a soft-j, nasal consonants.
_PHONETIC_RULES = [
    (r"^(kn|gn|pn)", "n"), (r"^wr", "r"), (r"ph", "f"), (r"ck", "k"), (r"qu", "kw"), (r"x", "ks"),
    (r"dg", "j"), (r"c(?=[eiy])", "s"), (r"c", "k"), (r"g(?=[eiy])", "j"), (r"z", "s"), (r"gh", "g"),
    (r"tch", "ch"), (r"sch", "sk"), (r"wh", "w"),
]


def letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def phonetic_key(text: str) -> str:
    word = letters(text)
    for pattern, replacement in _PHONETIC_RULES:
        word = re.sub(pattern, replacement, word)
    if not word:
        return ""
    # Vowels carry most of the ASR noise: keep only the first letter's sound and the consonant skeleton.
    skeleton = word[0] + re.sub(r"[aeiouyhw]", "", word[1:])
    return re.sub(r"(.)\1+", r"\1", skeleton)


def similarity(span: str, term: str) -> float:
    a, b = letters(span), letters(term)
    if not a or not b:
        return 0.0
    lexical = SequenceMatcher(None, a, b).ratio()
    pa, pb = phonetic_key(span), phonetic_key(term)
    phonetic = SequenceMatcher(None, pa, pb).ratio() if pa and pb else 0.0
    # The phonetic key is lossy, so it can raise a score but only partway.
    return max(lexical, 0.9 * phonetic)


@dataclass(frozen=True)
class Candidate:
    segment: int
    span: str
    start: int
    end: int
    terms: tuple[tuple[str, float], ...]  # best terms for this span, highest score first

    @property
    def best_score(self) -> float:
        return self.terms[0][1]

    @property
    def spelling_variant(self) -> bool:
        """Same letters as a term, written differently ("anti-gravity", "click house"): no model needed."""
        return letters(self.span) == letters(self.terms[0][0])


def spans(text: str) -> list[tuple[int, int, int]]:
    """(start, end, word_count) of every run of 1 to 3 adjacent words."""
    tokens = list(TOKEN.finditer(text))
    out: list[tuple[int, int, int]] = []
    for i in range(len(tokens)):
        for n in range(1, MAX_SPAN_WORDS + 1):
            if i + n <= len(tokens):
                out.append((tokens[i].start(), tokens[i + n - 1].end(), n))
    return out


def find_candidates(
    segments: list[tuple[int, str]], terms: list[str], *, threshold: float = 0.62, per_span: int = 3,
    multi_word_threshold: float = 0.74,
) -> list[Candidate]:
    clean = list(dict.fromkeys(t.strip() for t in terms if len(letters(t)) >= MIN_LETTERS))
    lowered_terms = [t.lower() for t in clean]
    out: list[Candidate] = []
    for index, text in segments:
        found: list[Candidate] = []
        for start, end, words in spans(text):
            span = text[start:end]
            lowered = span.lower()
            if len(letters(span)) < MIN_LETTERS:
                continue
            # A run that already contains a whole known term is the term (or next to it), not a mis-hearing of it.
            if any(re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", lowered) for term in lowered_terms):
                continue
            scored = []
            for term in clean:
                # Multi-word runs need a closer match: sound-alikes across word breaks are mostly noise.
                score = similarity(span, term)
                if score >= (threshold if words == 1 else multi_word_threshold) and lowered != term.lower():
                    scored.append((term, round(score, 3)))
            if scored:
                scored.sort(key=lambda pair: -pair[1])
                found.append(Candidate(index, span, start, end, tuple(scored[:per_span])))
        # Overlapping runs in one sentence: keep the strongest, then the shortest.
        found.sort(key=lambda c: (-c.best_score, c.end - c.start))
        kept: list[Candidate] = []
        for cand in found:
            if all(cand.end <= k.start or cand.start >= k.end for k in kept):
                kept.append(cand)
        out += sorted(kept, key=lambda c: c.start)
    return out
