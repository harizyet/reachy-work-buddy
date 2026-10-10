"""Labelled development set of question STRUCTURES for the three relations that were held out of the registry until now: release_day, escalation_contact and approver (Phase 44, final development pass,
2026-10-10). Authored BEFORE those relations were defined in `registry.py`, and frozen by hash (`HELDOUT_SET.sha256`) before the decomposer was run on it. The relation definitions are written from what the
words mean (a release day is the weekday releases go out; an escalation contact is the person incidents are escalated to; an approver is the person who approves a release), not from any dev16 case or bank D phrasing.

Independence and its limits, stated plainly:
  * dev16 (`cases_dev16.json`) and bank D were NOT opened for this set or for the definitions.
  * The invented corpus (`corpus_v4.json`) is shared with dev16. Before this set was written, the author had incidentally seen three RECORD sentence forms of these relations in a search output
    ("Escalate serious <Project> incidents to <Person>.", "<Person> approved the <Project> release.", and the budget sentences "approved through <Month>"). No release-day record sentence was seen. So the
    definitions are not blind to the record surface of two of the three relations; they are blind to dev16's questions, cases and phrasings.
  * All project / system names below are NOT in the corpus. Phrasings are the author's own, so the set shares the author's blind spots.
  * About a third of the items are near misses or out of scope on purpose: the correct behaviour is to withhold, never to guess a neighbouring relation.

Each item has the same shape as `decomposition_dev_set.json`: `parts` are (subject, relation, ask, scope, period) and `unc` is the number of clauses that cannot be typed from the question alone.

    python decomposition_heldout_set.py     -> decomposition_heldout_set.json
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

OBJ = {"release_day": "day", "escalation_contact": "person", "approver": "person", "owner": "person", "lead": "person", "on_call": "person", "budget_through": "month", "default_model": "model"}


def P(subject, relation, ask="value", scope="any", period=None):
    return {"subject": subject, "relation": relation, "ask": ask, "scope": scope, "period": period, "obj": "existence" if ask == "existence" else "order" if ask == "ordering" else OBJ[relation]}


ITEMS: list[dict] = []


def add(cat, q, parts=(), unc=0, hard=False):
    ITEMS.append({"id": f"H{len(ITEMS) + 1:03d}", "cat": cat, "q": q, "parts": list(parts), "unc": unc, "hard": hard})


# --- release_day --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
add("release_day", "Which day does Cobalt release?", [P("Cobalt", "release_day")])
add("release_day", "What is Drift's release day?", [P("Drift", "release_day")])
add("release_day", "On which day do Fennel releases go out?", [P("Fennel", "release_day")])
add("release_day", "When does Grove ship?", [P("Grove", "release_day")])
add("release_day", "What day of the week is the Mistral release?", [P("Mistral", "release_day")], hard=True)
add("release_day", "Which weekday does Nimbus usually release on?", [P("Nimbus", "release_day")])
add("release_day", "What day are Onyx releases cut?", [P("Onyx", "release_day")])
add("release_day", "Could you tell me Paprika's release day?", [P("Paprika", "release_day")])
add("release_day", "What is Cobalt's release day, and who owns the Ember API?", [P("Cobalt", "release_day"), P("Ember API", "owner")])
add("release_day", "Who is the Cobalt lead and which day does Cobalt release?", [P("Cobalt", "lead"), P("Cobalt", "release_day")])
add("release_day", "Which day was the Drift release approved?", unc=1, hard=True)  # an approval day is not a release day; no relation for it exists
add("release_day", "Is the Fennel release on a Friday?", unc=1)
add("release_day", "Which day will Grove release next month?", unc=1)
add("release_day", "When was the last Nimbus release?", unc=1, hard=True)  # a one-off event date, not the recurring day
add("release_day", "What is the release schedule for Onyx?", unc=1, hard=True)
add("release_day", "How many releases did Drift ship?", unc=1)

# --- escalation_contact -------------------------------------------------------------------------------------------------------------------------------------------------------------------------
add("escalation", "Who is the escalation contact for Cobalt?", [P("Cobalt", "escalation_contact")])
add("escalation", "Who should I escalate Drift incidents to?", [P("Drift", "escalation_contact")])
add("escalation", "Who do I escalate to for Fennel outages?", [P("Fennel", "escalation_contact")])
add("escalation", "Who handles escalations for Grove?", [P("Grove", "escalation_contact")])
add("escalation", "Who is the escalation point for the Ember API?", [P("Ember API", "escalation_contact")])
add("escalation", "Which person do we escalate Mistral problems to?", [P("Mistral", "escalation_contact")])
add("escalation", "Who is the Onyx escalation contact?", [P("Onyx", "escalation_contact")])
add("escalation", "Who is on call for Paprika, and who is the escalation contact for Paprika?", [P("Paprika", "on_call"), P("Paprika", "escalation_contact")])
add("escalation", "Who should I escalate to?", unc=1)
add("escalation", "Who do they escalate to?", unc=1)
add("escalation", "Who is the escalation contact for Cobalt this week?", unc=1)
add("escalation", "Is Olga Petrova the escalation contact for Drift?", unc=1)
add("escalation", "Who owns the Kiln scheduler and who is its escalation contact?", [P("Kiln scheduler", "owner")], unc=1)
add("escalation", "Who is the escalation contact?", unc=1)
add("escalation", "Why was the Cobalt incident escalated?", unc=1)

# --- approver -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
add("approver", "Who approved the Cobalt release?", [P("Cobalt", "approver")])
add("approver", "Who is the release approver for Drift?", [P("Drift", "approver")])
add("approver", "Who approves Fennel releases?", [P("Fennel", "approver")])
add("approver", "Who signed off the Grove release?", [P("Grove", "approver")], hard=True)
add("approver", "Who has to approve the Mistral release?", [P("Mistral", "approver")])
add("approver", "Who is the approver for Nimbus?", [P("Nimbus", "approver")])
add("approver", "Who approves releases for Onyx?", [P("Onyx", "approver")])
add("approver", "Which person approved the Paprika release?", [P("Paprika", "approver")])
add("approver", "Who approved the Cobalt release and who owns the Ember API?", [P("Cobalt", "approver"), P("Ember API", "owner")])
add("approver", "Who approved the Drift release, and which day does Drift release?", [P("Drift", "approver"), P("Drift", "release_day")])
add("approver", "Who approved the budget for Fennel?", unc=1)  # a budget approver is not a release approver
add("approver", "Who is the budget approver for Grove?", unc=1)
add("approver", "Who approved it?", unc=1)
add("approver", "Has Pablo Reyes approved the Cobalt release?", unc=1)
add("approver", "Who approved the Cobalt release last month?", unc=1)
add("approver", "Who approved the Cobalt release in March?", [P("Cobalt", "approver", "value", "past", ["in", "march"])])
add("approver", "Who can approve a release?", unc=1)
add("approver", "Through when is Nimbus's budget approved?", [P("Nimbus", "budget_through")])  # the existing budget relation must not be taken by the approver
add("approver", "Until which month is the Onyx budget approved?", [P("Onyx", "budget_through")])

# --- mixed with defined relations -----------------------------------------------------------------------------------------------------------------------------------------------------------------
add("mixed", "Who leads Cobalt, who is the Cobalt escalation contact and which day does it release?", [P("Cobalt", "lead"), P("Cobalt", "escalation_contact")], unc=1)
add("mixed", "What is Drift's default model, who approved the Drift release, and who is on call for Drift?", [P("Drift", "default_model"), P("Drift", "approver"), P("Drift", "on_call")])


def main() -> None:
    out = {"version": "heldout-relations-1", "purpose": "question-structure labels for release_day, escalation_contact and approver; authored before the relations were defined", "items": ITEMS}
    (HERE / "decomposition_heldout_set.json").write_text(json.dumps(out, indent=1))
    print(len(ITEMS), "items;", sum(len(i["parts"]) for i in ITEMS), "parts;", sum(i["unc"] for i in ITEMS), "must-withhold clauses;", sum(i["hard"] for i in ITEMS), "marked hard")


if __name__ == "__main__":
    main()
