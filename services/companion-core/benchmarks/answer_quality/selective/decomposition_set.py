"""Labelled development set of question STRUCTURES for the question-side decomposer (Phase 44, I-2 follow-up, 2026-10-10). Authored BEFORE the decomposer and the typed registry existed, then frozen by hash
(`DECOMPOSITION_SET.sha256`) before the decomposer was first run; the first-contact result and the result after one documented tuning pass are both reported in the follow-up record.

Independence: nothing here is generated from, or copied out of, the dev15 / dev16 gold atoms or the question banks. dev16 and bank D were not opened. About 60% of the entity names are NOT in the invented
corpus (unseen projects, systems, models, vendors and people), because "unseen names within known types" is one of the things being measured. Phrasings are the author's own, so the set shares the
author's blind spots; that is disclosed, not corrected. About a third of the items are DELIBERATELY hard or out of scope, with the correct behaviour stated: the decomposer must withhold, not guess.

Each item: `q` (question text), `cat` (structure category), `parts` (the sub-claims a careful reader would extract, in order) and `unc` (the number of clauses a careful reader would say cannot be typed from
the question alone, so the correct behaviour is to withhold that clause). A part is (subject, relation, ask, scope, period): `ask` is value | existence | ordering; `scope` is any | current | past; `period` is
None or [kind, month] for a stated month. `obj` (the kind of answer requested) is derived from the relation in the labels below. Items marked `hard` are expected misses of a conservative decomposer and are
reported separately, not removed.

    python decomposition_set.py     -> decomposition_dev_set.json
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

OBJ = {  # the kind of answer each relation asks for (author's definition)
    "owner": "person", "lead": "person", "retry_limit": "number", "default_model": "model", "decision": "text", "runs_on": "host", "rollback_window": "number", "support_hours": "hours", "reviews": "text",
    "on_call": "person", "budget_through": "month", "deadline": "day", "staging_env": "existence", "test_fixer": "person", "security_reviewer": "person", "max_message_size": "number", "vacation": "month",
    "incident_auditor": "person", "standup": "time", "review_day": "day", "attends": "person"}


def P(subject, relation, ask="value", scope="any", period=None):
    return {"subject": subject, "relation": relation, "ask": ask, "scope": scope, "period": period, "obj": "existence" if ask == "existence" else "order" if ask == "ordering" else OBJ[relation]}


ITEMS: list[dict] = []


def add(cat, q, parts=(), unc=0, hard=False):
    ITEMS.append({"id": f"L{len(ITEMS) + 1:03d}", "cat": cat, "q": q, "parts": list(parts), "unc": unc, "hard": hard})


# --- single relation, plain wording -------------------------------------------------------------------------------------------------------------------------------------------------------------
add("single", "Who owns the Relay gateway?", [P("Relay gateway", "owner")])
add("single", "Who is responsible for the Beacon queue?", [P("Beacon queue", "owner")])
add("single", "Who looks after the Kiln scheduler?", [P("Kiln scheduler", "owner")])
add("single", "Who maintains the Pylon gateway?", [P("Pylon gateway", "owner")])
add("single", "Who leads Harbor?", [P("Harbor", "lead")])
add("single", "Who is the Lantern lead?", [P("Lantern", "lead")])
add("single", "Who heads Meadow?", [P("Meadow", "lead")])
add("single", "Who manages Zenith?", [P("Zenith", "lead")])
add("single", "What is the retry limit of the Shale store?", [P("Shale store", "retry_limit")])
add("single", "How many attempts does the Vault auth service allow?", [P("Vault auth service", "retry_limit")])
add("single", "How many times does the Loom stream retry a failed job?", [P("Loom stream", "retry_limit")])
add("single", "What is Harbor's default model?", [P("Harbor", "default_model")])
add("single", "Which model does Aspen use by default?", [P("Aspen", "default_model")])
add("single", "What model does Briar default to?", [P("Briar", "default_model")])
add("single", "Which model did Lantern decide to keep?", [P("Lantern", "decision")])
add("single", "What was decided for Zenith?", [P("Zenith", "decision")])
add("single", "Where does Falcon-4B run?", [P("Falcon-4B", "runs_on")])
add("single", "Which host serves Wren-3B?", [P("Wren-3B", "runs_on")])
add("single", "On which machine does Raven-13B run?", [P("Raven-13B", "runs_on")])
add("single", "What hardware does Lynx-7B run on?", [P("Lynx-7B", "runs_on")])
add("single", "How long do I have to roll back a failed Harbor deploy?", [P("Harbor", "rollback_window")])
add("single", "What is the rollback window for Lantern?", [P("Lantern", "rollback_window")])
add("single", "Within how many minutes must Meadow be rolled back?", [P("Meadow", "rollback_window")])
add("single", "What are Acme Freight's support hours?", [P("Acme Freight", "support_hours")])
add("single", "When is Zephyr Telecom support open on weekdays?", [P("Zephyr Telecom", "support_hours")])
add("single", "What hours is Borealis Cloud staffed?", [P("Borealis Cloud", "support_hours")])
add("single", "What does Nadia Orlov review?", [P("Nadia Orlov", "reviews")])
add("single", "Which settings is Marco Bianchi reviewing?", [P("Marco Bianchi", "reviews")])
add("single", "Who is on call for Harbor?", [P("Harbor", "on_call")])
add("single", "Who has the pager for Lantern?", [P("Lantern", "on_call")])
add("single", "Who covers on-call duty for Cedar?", [P("Cedar", "on_call")])
add("single", "Until which month is Harbor funded?", [P("Harbor", "budget_through")])
add("single", "Through when is Lantern's budget approved?", [P("Lantern", "budget_through")])
add("single", "What is Priya Nair's deadline for the written summary?", [P("Priya Nair", "deadline")])
add("single", "By when does Kofi Mensah have to circulate the summary?", [P("Kofi Mensah", "deadline")])
add("single", "Who will fix the Harbor rollback test?", [P("Harbor", "test_fixer")])
add("single", "Who is working on the Lantern rollback test?", [P("Lantern", "test_fixer")])
add("single", "Who is the security reviewer for Harbor?", [P("Harbor", "security_reviewer")])
add("single", "Who signs off Lantern security?", [P("Lantern", "security_reviewer")])
add("single", "Who reviews security for Cedar?", [P("Cedar", "security_reviewer")])
add("single", "How large can a Mosaic search index message be?", [P("Mosaic search index", "max_message_size")])
add("single", "What is the maximum message size of the Beacon queue?", [P("Beacon queue", "max_message_size")])
add("single", "How big can a Cinder cache message be?", [P("Cinder cache", "max_message_size")])
add("single", "When will the Osprey lead be away next?", [P("Osprey", "vacation")])
add("single", "When is the Harbor lead's next vacation?", [P("Harbor", "vacation")])
add("single", "When is the Cedar lead on holiday?", [P("Cedar", "vacation")])
add("single", "Who audits the Cedar build logs?", [P("Cedar", "incident_auditor")])
add("single", "What time is the Harbor standup?", [P("Harbor", "standup")])
add("single", "When does the Quartz stand-up start?", [P("Quartz", "standup")])
add("single", "Which day is the Harbor design review?", [P("Harbor", "review_day")])
add("single", "On which day are Lantern design reviews held?", [P("Lantern", "review_day")])
add("single", "Who was in the Harbor planning meeting?", [P("Harbor", "attends")])
add("single", "Who attended the Garnet planning meeting?", [P("Garnet", "attends")])
add("single", "Who took part in the Lantern meeting?", [P("Lantern", "attends")])
add("single", "Who is in charge of the Ferry queue?", [P("Ferry queue", "owner")])

# --- existence ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
add("existence", "Does Harbor have a staging environment?", [P("Harbor", "staging_env", "existence")])
add("existence", "Is there a staging environment for Garnet?", [P("Garnet", "staging_env", "existence")])
add("existence", "Do Lantern and Cedar have a staging environment?", [P("Lantern", "staging_env", "existence"), P("Cedar", "staging_env", "existence")], hard=True)
add("existence", "Has Meadow got a staging environment?", [P("Meadow", "staging_env", "existence")], hard=True)

# --- phrasing variants (prefixes, no question mark, lowercase) ---------------------------------------------------------------------------------------------------------------------------------
add("phrasing", "Could you tell me who owns the Ember API?", [P("Ember API", "owner")])
add("phrasing", "Can you tell me Harbor's default model?", [P("Harbor", "default_model")])
add("phrasing", "I'd like to know who leads Lantern.", [P("Lantern", "lead")])
add("phrasing", "Tell me who is on call for Harbor.", [P("Harbor", "on_call")])
add("phrasing", "Please say what the retry limit of the Glint dashboard is", [P("Glint dashboard", "retry_limit")])
add("phrasing", "Do you know who owns the Atlas search index?", [P("Atlas search index", "owner")])
add("phrasing", "who owns the relay gateway", [P("Relay gateway", "owner")], hard=True)
add("phrasing", "what is harbor's default model?", [P("Harbor", "default_model")], hard=True)
add("phrasing", "Whose is the Prism dashboard?", [P("Prism dashboard", "owner")], hard=True)
add("phrasing", "What's the biggest message the Sluice cache accepts?", [P("Sluice cache", "max_message_size")], hard=True)
add("phrasing", "Which engineer is on the pager for Quartz?", [P("Quartz", "on_call")])
add("phrasing", "Which of our people leads Aspen?", [P("Aspen", "lead")], hard=True)

# --- temporal qualification ---------------------------------------------------------------------------------------------------------------------------------------------------------------
add("temporal", "Who used to own the Ferry queue?", [P("Ferry queue", "owner", scope="past")])
add("temporal", "What was Harbor's previous default model?", [P("Harbor", "default_model", scope="past")])
add("temporal", "Which model did Aspen use by default in February?", [P("Aspen", "default_model", scope="past", period=["in", "february"])])
add("temporal", "What was Willow's default model before November?", [P("Willow", "default_model", scope="past", period=["before", "november"])])
add("temporal", "How many retries did the archived Kiln scheduler architecture allow?", [P("Kiln scheduler", "retry_limit", scope="past")])
add("temporal", "What was the old retry limit of the Lattice store?", [P("Lattice store", "retry_limit", scope="past")])
add("temporal", "Which model was Lantern formerly using by default?", [P("Lantern", "default_model", scope="past")])
add("temporal", "What is Harbor's current default model?", [P("Harbor", "default_model", scope="current")])
add("temporal", "Who is on call for Cedar right now?", [P("Cedar", "on_call", scope="current")])
add("temporal", "Who currently leads Meadow?", [P("Meadow", "lead", scope="current")])
add("temporal", "What is the retry limit of the Conduit stream today?", [P("Conduit stream", "retry_limit", scope="current")])
add("temporal", "What was the Harbor default model in 2025?", unc=1)
add("temporal", "Who was on call for Cedar last week?", unc=1)
add("temporal", "Who is on call for Lantern this month?", unc=1)
add("temporal", "What did Aspen use by default after March?", unc=1)
add("temporal", "What was the Zenith default model as of June?", [P("Zenith", "default_model", scope="past", period=["as of", "june"])])
add("temporal", "Before November, which model did Sable use by default?", [P("Sable", "default_model", scope="past", period=["before", "november"])], hard=True)
add("temporal", "What is the old and current retry limit of the Shale store?", unc=1)

# --- ordering -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
add("ordering", "Was the Harbor design review day updated after the other memory gave a different answer?", [P("Harbor", "review_day", "ordering")])
add("ordering", "Has the Harbor standup time changed?", [P("Harbor", "standup", "ordering")])
add("ordering", "Did the Quartz design review day get replaced by a newer record?", [P("Quartz", "review_day", "ordering")])
add("ordering", "Which Cedar standup time is more recent?", [P("Cedar", "standup", "ordering")])
add("ordering", "Which is newer, the Lantern standup time in one memory or in the other?", [P("Lantern", "standup", "ordering")], hard=True)
add("ordering", "What is the latest Harbor standup time?", unc=1)

# --- coordination ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
add("coordination", "Who owns the Ferry queue, and who leads Marlin?", [P("Ferry queue", "owner"), P("Marlin", "lead")])
add("coordination", "Where does Swift-6B run and who is on call for Sable?", [P("Swift-6B", "runs_on"), P("Sable", "on_call")])
add("coordination", "Who leads Harbor; who is on call for Lantern?", [P("Harbor", "lead"), P("Lantern", "on_call")])
add("coordination", "Who leads Harbor? Who is on call for Lantern?", [P("Harbor", "lead"), P("Lantern", "on_call")])
add("coordination", "Who owns the Beacon queue, who leads Meadow, and what is Zenith's default model?", [P("Beacon queue", "owner"), P("Meadow", "lead"), P("Zenith", "default_model")])
add("coordination", "Who leads Harbor and Lantern?", [P("Harbor", "lead"), P("Lantern", "lead")], hard=True)
add("coordination", "Who owns the Ember API and the Kiln scheduler?", [P("Ember API", "owner"), P("Kiln scheduler", "owner")], hard=True)
add("coordination", "What are Harbor's default model and rollback window?", [P("Harbor", "default_model"), P("Harbor", "rollback_window")], hard=True)
add("coordination", "Who leads and who is on call for Cedar?", [P("Cedar", "lead"), P("Cedar", "on_call")], hard=True)
add("coordination", "What is the retry limit and the maximum message size of the Beacon queue?", [P("Beacon queue", "retry_limit"), P("Beacon queue", "max_message_size")], hard=True)
add("coordination", "Who is on call for Harbor and who fixes the Harbor rollback test?", [P("Harbor", "on_call"), P("Harbor", "test_fixer")])
add("coordination", "Is there a staging environment for Cedar, and what is Harbor's default model?", [P("Cedar", "staging_env", "existence"), P("Harbor", "default_model")])
add("coordination", "Who owns the Ferry queue, and what time is the Cedar standup, and who audits the Lantern build logs?", [P("Ferry queue", "owner"), P("Cedar", "standup"), P("Lantern", "incident_auditor")])
add("coordination", "Who was in the Harbor planning meeting, and who has the on-call duty for Harbor, and who will fix the Lantern rollback test?",
    [P("Harbor", "attends"), P("Harbor", "on_call"), P("Lantern", "test_fixer")])
add("coordination", "What was Sable's default model before November, and what is the retry limit of the Relay gateway?",
    [P("Sable", "default_model", scope="past", period=["before", "november"]), P("Relay gateway", "retry_limit")])
add("coordination", "Which model did Vesper use by default in February, and which model does Willow use by default?",
    [P("Vesper", "default_model", scope="past", period=["in", "february"]), P("Willow", "default_model")])
add("coordination", "Who owns the Ferry queue, and also what are Quarry Data's support hours?", [P("Ferry queue", "owner"), P("Quarry Data", "support_hours")])
add("coordination", "Who leads Harbor as well as who owns the Ferry queue?", [P("Harbor", "lead"), P("Ferry queue", "owner")])
add("coordination", "Who is the Wren lead, and who covers Wren's on-call?", [P("Wren", "lead"), P("Wren", "on_call")])
add("coordination", "How many times does the Cobalt auth service retry a failed job, and who owns the Cobalt auth service?", [P("Cobalt auth service", "retry_limit"), P("Cobalt auth service", "owner")])
add("coordination", "Who owns the Ferry queue, or who leads Marlin?", [P("Ferry queue", "owner"), P("Marlin", "lead")])
add("coordination", "When will the Cedar lead be on vacation, and who leads Marlin?", [P("Cedar", "vacation"), P("Marlin", "lead")])
add("coordination", "Who leads Harbor, who owns the Beacon queue, who is on call for Lantern, and what time is the Meadow standup?",
    [P("Harbor", "lead"), P("Beacon queue", "owner"), P("Lantern", "on_call"), P("Meadow", "standup")])

# --- partly typeable: the typeable clause is answered, the rest withheld ---------------------------------------------------------------------------------------------------------------
add("partial", "Does Harbor have a staging environment, and who is on call for it?", [P("Harbor", "staging_env", "existence")], unc=1)
add("partial", "Who owns the Ferry queue, and what is its retry limit?", [P("Ferry queue", "owner")], unc=1)
add("partial", "Who leads Harbor and what do they review?", [P("Harbor", "lead")], unc=1)
add("partial", "Who is the Cedar lead and when are they away?", [P("Cedar", "lead")], unc=1)
add("partial", "Who owns the Ferry queue, and why?", [P("Ferry queue", "owner")], unc=1)
add("partial", "Who leads Harbor, and how many employees does Lantern have?", [P("Harbor", "lead")], unc=1)
add("partial", "What is Cedar's favourite colour, and who leads Marlin?", [P("Marlin", "lead")], unc=1)

# --- must be withheld (the correct behaviour is "I cannot work out what is being asked") ---------------------------------------------------------------------------------------
add("uncertain", "Who owns it?", unc=1)
add("uncertain", "What is its retry limit?", unc=1)
add("uncertain", "And who leads that project?", unc=1)
add("uncertain", "What about their standup?", unc=1)
add("uncertain", "What is Cedar's favourite colour?", unc=1)
add("uncertain", "How many employees does Harbor have?", unc=1)
add("uncertain", "Why did Cedar switch models?", unc=1)
add("uncertain", "Summarise the Harbor project.", unc=1)
add("uncertain", "Is Pablo Reyes the Cedar lead?", unc=1)
add("uncertain", "Is Cedar's default model Kestrel-3B?", unc=1)
add("uncertain", "Does the Ferry queue retry 5 times?", unc=1)
add("uncertain", "Is the Harbor standup on Monday?", unc=1)
add("uncertain", "Who owns the Ferry queue at Cedar?", unc=1)
add("uncertain", "Who is on call?", unc=1)
add("uncertain", "What is the retry limit?", unc=1)
add("uncertain", "Where is the Harbor lead?", unc=1)
add("uncertain", "Who is the rollback window for Cedar?", unc=1)
add("uncertain", "Tell me about Cedar.", unc=1)
add("uncertain", "Who runs Cedar?", unc=1)
add("uncertain", "Who is in charge of Cedar?", unc=1)
add("uncertain", "Does Cedar have a lead?", unc=1)
add("uncertain", "Which staging environment does Harbor use?", unc=1)
add("uncertain", "Does the Ferry queue have a staging environment?", unc=1)
add("uncertain", "Who owns Pablo Reyes?", unc=1)
add("uncertain", "Who leads Swift-6B?", unc=1)
add("uncertain", "Which host serves Harbor?", unc=1)
add("uncertain", "Who is on call for Harbor and Lantern together?", unc=1)

# --- unseen names within known types ------------------------------------------------------------------------------------------------------------------------------------------------------
add("unseen", "Who owns the Zeta stream?", [P("Zeta stream", "owner")])
add("unseen", "Which host serves Orca-30B?", [P("Orca-30B", "runs_on")])
add("unseen", "Which host serves Pika-1.5B?", [P("Pika-1.5B", "runs_on")])
add("unseen", "What are Northwind Traders' support hours?", [P("Northwind Traders", "support_hours")])
add("unseen", "What does Anna-Marie Oduya review?", [P("Anna-Marie Oduya", "reviews")])
add("unseen", "What does Liam O'Connor review?", [P("Liam O'Connor", "reviews")])
add("unseen", "Who leads Tidewater?", [P("Tidewater", "lead")])
add("unseen", "What is the retry limit of the Orbit worker?", [P("Orbit worker", "retry_limit")])
add("unseen", "Who owns the Krait message broker?", [P("Krait message broker", "owner")])
add("unseen", "Who owns the Mica database?", [P("Mica database", "owner")])
add("unseen", "What is Ibex's default model?", [P("Ibex", "default_model")])
add("unseen", "Who is on call for Nightjar?", [P("Nightjar", "on_call")])


def build() -> dict:
    return {"version": 1, "purpose": "labelled question structures for the deterministic question-side decomposer (development set, not an acceptance set)", "items": ITEMS}


if __name__ == "__main__":
    import collections

    out = HERE / "decomposition_dev_set.json"
    out.write_text(json.dumps(build(), indent=1) + "\n")
    print(len(ITEMS), dict(collections.Counter(i["cat"] for i in ITEMS)), "hard", sum(i["hard"] for i in ITEMS), "parts", sum(len(i["parts"]) for i in ITEMS), "unc", sum(i["unc"] for i in ITEMS))
