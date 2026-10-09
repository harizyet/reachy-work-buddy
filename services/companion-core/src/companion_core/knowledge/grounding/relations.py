"""The relation lexicon: a small, written, reviewable table. A relation has the question cues that select it, the assertion cues that mark a sentence as stating it, and the kind of value an
assertion must carry. It is designed from the DESIGN relations only; the held-out relations (on_call, budget_through, deadline) are deliberately absent, so questions about them take the generic path
and the acceptance set measures how far the matcher generalises. Stems are compared by the same crude stemmer the coverage code used (first five letters, y/ie/ied folded)."""

from __future__ import annotations

# value kinds: person | number | model | host | hours | text (any capitalised or numeric token)
RELATIONS: dict[str, dict] = {
    "owner": {"question": ["owns", "owner", "responsible", "looks after", "ownership"], "assertion": ["owns", "owned by", "owner of", "owner", "responsible for"], "value": "person"},
    "lead": {"question": ["leads", "lead", "head", "heads"], "assertion": ["lead", "leads", "led by"], "value": "person"},
    "retry_limit": {"question": ["retry", "retries", "retried", "tried again", "try again"], "assertion": ["retried", "retries", "retry"], "value": "number"},
    "default_model": {"question": ["default model", "by default", "default"], "assertion": ["default model", "serves", "model"], "value": "model"},
    "runs_on": {"question": ["run", "runs", "served", "serves", "host", "hardware", "hosted"], "assertion": ["serves", "on the", "runs on", "hosted"], "value": "host"},
    "rollback_window": {"question": ["rollback", "roll back", "rolled back", "undo"], "assertion": ["roll back within", "rollback window", "rollback within", "roll back"], "value": "number"},
    "support_hours": {"question": ["support", "hours", "reach", "open", "reachable"], "assertion": ["support hours", "hours are", "support is open"], "value": "hours"},
    "decision": {"question": ["decided", "decision", "agree", "agreed"], "assertion": ["decision is", "we decided", "agreed to", "decided to"], "value": "model"},
    "reviews": {"question": ["review", "reviewing", "reviews"], "assertion": ["to review", "reviews", "reviewing", "will review"], "value": "text"},
}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60}

# relations answered from an authoritative store (C3) rather than from text: C1 and C2 do not judge them
STRUCTURED = {"attends": {"question": ["attended", "attend", "attendees", "took part", "was in", "were in"]}}
HISTORICAL_TEXT = ["as of march", "as of january", "as of february", "as of april", "as of may", "as of june", "as of july", "as of august", "as of september", "formerly", "previously", "used to", "has been retired", "was retired"]
HISTORICAL_TITLE = ["archived", " v1", "(old)"]
HISTORY_QUESTION = ["in march", "in january", "in february", "in april", "in may", "in june", "in july", "in august", "in september", "before october", "before it switched", "previously", "used to", "earlier", "formerly", "originally"]
