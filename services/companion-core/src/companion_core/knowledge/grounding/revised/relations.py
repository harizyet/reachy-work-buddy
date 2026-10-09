"""Revised relation lexicon: general synonym families per relation, written from general English usage and NOT from any dev12 example. It now includes the three relations that dev12 held out
(on_call, budget_through, deadline), because after dev12 they are known; the relations of corpus v3's held-out set (release_day, escalation_contact, storage_limit) are deliberately absent, so they
exercise the generic path. Bank B of corpus v3 (the unseen paraphrases) was hashed before this file existed; the author wrote both, so 'unseen' means unseen by this file's design process, not independent."""

from __future__ import annotations

RELATIONS: dict[str, dict] = {
    "owner": {"question": ["owns", "owner", "own", "responsible", "look after", "looks after", "looking after", "accountable", "maintain", "maintains", "maintained", "custodian", "ownership"],
              "assertion": ["owns", "owned by", "owner of", "owner", "responsible for", "accountable", "looks after", "maintains", "will own"], "value": "person"},
    "lead": {"question": ["leads", "lead", "head", "heads", "heads up", "in charge", "manager", "manages", "runs the project", "head up"], "assertion": ["lead", "leads", "led by", "in charge of", "manager", "heads"], "value": "person"},
    "retry_limit": {"question": ["retry", "retries", "retried", "tried again", "try again", "attempts", "attempt", "tries", "re-run"], "assertion": ["retried", "retries", "retry", "attempts", "tried"], "value": "number"},
    "default_model": {"question": ["default model", "by default", "default", "standard model", "standard one", "standard", "usual model", "baseline model"], "assertion": ["default model", "serves", "standard model", "default"], "value": "model"},
    "runs_on": {"question": ["run", "runs", "served", "serves", "host", "hardware", "hosted", "deployed", "machine", "running on", "run on", "hosting"], "assertion": ["serves", "on the", "runs on", "hosted", "deployed"], "value": "host"},
    "rollback_window": {"question": ["rollback", "roll back", "rolled back", "undo", "undoing", "revert", "reverting", "back out"], "assertion": ["roll back within", "rollback window", "rollback within", "roll back", "undo", "revert"], "value": "number"},
    "support_hours": {"question": ["support", "hours", "reach", "open", "reachable", "staffed", "available", "business hours", "opening hours"], "assertion": ["support hours", "hours are", "support is open", "staffed", "opening hours"], "value": "hours"},
    "decision": {"question": ["decided", "decision", "decide", "agree", "agreed", "settled", "chose", "chosen", "resolved"], "assertion": ["decision is", "we decided", "agreed to", "decided to", "settled on", "chose", "keep"], "value": "model"},
    "reviews": {"question": ["review", "reviewing", "reviews", "reviewed", "look over", "looks over", "inspect", "vet", "vets", "check over"], "assertion": ["to review", "reviews", "reviewing", "will review", "look over", "inspect"], "value": "text"},
    "on_call": {"question": ["on call", "on-call", "oncall", "covers", "covering", "paged", "pager", "out of hours", "after hours", "duty"], "assertion": ["on call", "on-call", "covers", "paged", "pager", "duty"], "value": "person"},
    "budget_through": {"question": ["budget", "funded", "funding", "financed", "financing", "money"], "assertion": ["budget", "approved through", "funded", "funding"], "value": "month"},
    "deadline": {"question": ["deadline", "due", "by when", "must send", "have to circulate", "circulate", "hand in", "submit", "owed"], "assertion": ["by", "due", "circulate", "deadline"], "value": "day"},
}
STRUCTURED = {"attends": {"question": ["attended", "attend", "attendees", "took part", "take part", "was in", "were in", "joined", "join", "participants", "participated", "present at"]}}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# question cues that are common in other relations' questions: they count for half, so a specific cue elsewhere in the question wins ("how long does the budget run")
WEAK = {"run", "runs", "open", "due", "available", "reach", "hours", "support", "head", "own", "tries", "duty", "money"}
