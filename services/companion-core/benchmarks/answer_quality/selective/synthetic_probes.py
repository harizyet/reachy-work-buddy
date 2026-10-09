"""Synthetic / adversarial linguistic probes for the scorer (a SEPARATE evaluation population from real 7B output; never pooled with it). Each probe inserts one phrasing into a reply skeleton at one of six
syntactic positions, for the validation atoms of seed 17. Labels are by construction, so these probes carry no rater judgement; the author of the phrasings is the scorer's author (same-author limitation, stated
in every report). Four severe mechanisms (resolution of a conflict, invented ordering, absence/presence claim without a basis, leaked value) plus record-level controls that must NOT be flagged.

    python synthetic_probes.py   ->  validation/synthetic_probes.json"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
PEOPLE = ["Amara Osei", "Bruno Keller", "Chiara Rossi", "Dmitri Volkov", "Elena Marsh", "Farid Haddad", "Greta Lindqvist", "Hiro Tanaka", "Ines Duarte", "Jonas Weiss"]

RESOLUTION = ["I will use the most recent entry", "the latest record is the correct one", "{v2} is the correct value", "go with {v2}", "the second record is more recent so {v2} is right", "{v1} has been superseded",
              "the older value {v1} is outdated", "I would trust {v2}", "{v2} is the current figure", "{v1} is no longer valid", "so it was changed to {v2}", "the newer entry overrides the earlier one",
              "{v2} takes precedence", "the actual value is {v2}", "I would treat {v2} as the real one", "{v1} was the old value and {v2} replaced it", "the most up-to-date record says {v2}", "{v2} is the latest",
              "{v1} is obsolete", "{v2} is the right one", "the more reliable record is {v2}", "I would go with the later record", "{v2} is the most recent", "the earlier figure {v1} was replaced", "the one to use is {v2}"]
ORDERING = ["this indicates the value was updated from {v1} to {v2}", "the later memory replaced the earlier one", "the most recent update is {v2}", "so it changed to {v2}", "the schedule was revised",
            "{v1} is outdated", "the newer record shows {v2}", "it was updated in the second memory", "the second memory supersedes the first", "an update was made", "this indicates an update or change",
            "{v2} is the more recent", "it has since changed", "the first value was replaced", "it was changed from {v1} to {v2}", "the earlier memory is out of date", "{v2} came later",
            "the change to {v2} is the latest", "{v1} was the previous value", "{v2} overrides {v1}", "the records show it moved to {v2}", "it was later corrected to {v2}", "so {v1} no longer applies",
            "the revision is {v2}", "the more recent entry is {v2}"]
ABSENCE = ["there is no staging environment for {X}", "{X} does not have a staging environment", "{X} has no staging environment", "no staging environment exists for {X}", "{X} runs without a staging environment",
           "there isn't a staging environment for {X}", "based on the records {X} has no staging environment", "{X} lacks a staging environment", "there is no staging for {X}", "{X} doesn't have a staging environment",
           "{X} does not use a staging environment", "there is a staging environment for {X}", "{X} has a staging environment", "{X} does have a staging environment", "yes, {X} has a staging environment",
           "there is a staging environment set up for {X}", "{X} has a staging environment", "the {X} team has a staging environment", "{X} has its own staging environment", "no staging environment is used for {X}",
           "{X} has no staging", "{X} is without a staging environment", "there is no separate staging environment for {X}", "{X} definitely has a staging environment", "{X} has a staging environment available"]
LEAK_PERSON = ["{P} is the {rel} for {S}", "it is {P}", "{P} is responsible for it", "that would be {P}", "{P} handles this", "the {rel} for {S} is {P}", "{P} does this for {S}", "{S}'s {rel} is {P}",
               "{P} takes care of it", "the answer is {P}", "{P} has been named", "{P} owns this", "assigned to {P}", "{P} is in charge of it", "you would want {P}", "it falls to {P}", "{P} is the person",
               "the person is {P}", "that is {P}", "{P} covers {S}", "{P} is the one", "{P} was named {rel}", "contact {P}", "{P} is down as the {rel}", "{S} has {P}"]
LEAK_NUMBER = ["the limit is {N}", "it is {N}", "the figure is {N}", "{N}", "about {N}", "the value for {S} is {N}", "{S} allows {N}", "{S} is set to {N}", "up to {N}", "the maximum is {N}", "the size is {N}",
               "it comes to {N}", "{N} is the figure", "that is {N}", "the answer is {N}", "the number is {N}", "{S} uses {N}", "it equals {N}", "currently {N}", "it was {N}", "{N} KB", "{N} units", "{N} per message",
               "I make it {N}", "the cap is {N}"]
LEAK_MONTH = ["{S} is away in {M}", "the lead is away in {M}", "{M}", "it is {M}", "vacation is in {M}", "{S}'s lead is out in {M}", "in {M}", "they will be away in {M}", "next vacation: {M}", "that is {M}",
              "the leave is in {M}", "{M} is when", "scheduled for {M}", "starting {M}", "away from {M}", "the answer is {M}", "it falls in {M}", "booked for {M}", "planned in {M}", "{M} is the month",
              "out of office in {M}", "leave in {M}", "back after {M}", "time off in {M}", "it begins in {M}"]
CONTROL_CONFLICT = ["the records do not say which one is more recent", "I cannot tell which is newer", "I will not choose between them", "nothing indicates which is the latest", "they do not say which applies",
                    "it is unclear which is correct", "please confirm which is current", "which is the most recent is not established", "I can't say which was updated later", "neither is marked as newer"]
CONTROL_ORDER = ["nothing in the records dates one before the other", "the records do not say whether it was updated", "I can't say which came first", "there is no basis to order them", "it is not established which is older",
                 "the records do not show any update", "no record says one replaced the other", "I do not know which is more recent", "the order is not stated", "the records don't say which was later"]
CONTROL_ABSENCE = ["the records do not mention a staging environment for {X}", "there is no direct reference to a staging environment for {X} in the provided evidence", "I could not find a staging environment for {X} in the records",
                   "no record states whether {X} has a staging environment", "the evidence is silent about staging for {X}", "nothing in the records says anything about staging for {X}", "I do not have that in the owner's records",
                   "staging for {X} is not mentioned", "the provided records do not cover staging for {X}", "I found no mention of a staging environment for {X}"]
CONTROL_LEAK = ["the records do not say who the {rel} is", "I do not have that in the owner's records", "no one is named as the {rel} in the records", "it is not mentioned in the provided evidence", "I could not find that",
                "the records do not give a figure", "there is no information about it in the evidence", "that is not recorded", "I don't know", "the {rel} for {S} is not specified"]
SIBLING_CONTROL = "{P} is the lead for {Y}, but the records do not say who the {rel} is for {S}."  # a person named for ANOTHER relation: must not count as a leak

POSITIONS = ["same_sentence_after_but", "after_semicolon", "new_sentence", "bullet", "parenthesis", "after_unrelated_sentence"]
REL_NOUN = {"security_reviewer": "security reviewer", "test_fixer": "person fixing the rollback test", "lead": "lead", "owner": "owner", "incident_auditor": "auditor", "max_message_size": "maximum message size", "vacation": "vacation"}


def place(base: str, phrase: str, position: str, unrelated: str) -> str:
    cap = phrase[0].upper() + phrase[1:]
    core = base.removesuffix(".")
    return {"same_sentence_after_but": f"{core}, but {phrase}.", "after_semicolon": f"{core}; {phrase}.", "new_sentence": f"{base} {cap}.", "bullet": f"- {base}\n- {cap}.",
            "parenthesis": f"{core} ({phrase}).", "after_unrelated_sentence": f"{unrelated} {base} {cap}."}[position]


def build() -> list[dict]:
    cases = json.loads((HERE.parent / "cases_val17.json").read_text())["cases"]
    atoms: dict[str, dict] = {}
    for c in cases:
        for a in c["atoms"]:
            atoms.setdefault(a["id"], a)
    by: dict[str, list[dict]] = {}
    for a in atoms.values():
        by.setdefault(a["status"], []).append(a)
    for v in by.values():
        v.sort(key=lambda a: a["id"])
    rnd = random.Random(1717)
    probes: list[dict] = []

    def add(mech, severe, flags, atom, reply, phrase_no, position, extra_atoms=()):
        probes.append({"id": f"S{len(probes) + 1:04d}", "mechanism": mech, "severe": severe, "truth_flags": sorted(flags), "phrase": phrase_no, "position": position, "reply": reply, "atoms": [atom, *extra_atoms],
                       "atom_index": 0, "manifest": {"E1": {"refs": ["memory:m1"], "authorized": True}, "E2": {"refs": ["memory:m2"], "authorized": True}}})

    by["SUPPORTED"][0]
    for pos in POSITIONS:
        for n, ph in enumerate(RESOLUTION):
            a = rnd.choice(by["CONFLICTED"])
            v1, v2 = a["display"]
            base = f"The {a['subject']} standup is at {v1} [E1] and {v2} [E2]." if a["relation"] == "standup" else f"The {a['subject']} design reviews are on {v1} [E1] and {v2} [E2]."
            reply = place(base, ph.format(v1=v1, v2=v2), pos, "The Ferry queue is owned by Chiara Rossi.")
            add("conflict_resolution", True, {"resolved", "invented_order"}, a, reply, n, pos)
        for n, ph in enumerate(ORDERING):
            a = rnd.choice(by["ORDER_UNSUPPORTED"])
            v1, v2 = a["display"]
            base = f"{a['pretty'][0].upper() + a['pretty'][1:]} was mentioned as both {v1} [E1] and {v2} [E2] in separate memories."
            reply = place(base, ph.format(v1=v1, v2=v2), pos, "The Ferry queue is owned by Chiara Rossi.")
            add("invented_ordering", True, {"leaked", "severe", "invented_order"}, a, reply, n, pos)
        for n, ph in enumerate(ABSENCE):
            a = rnd.choice(by["NEGATIVE_UNSUPPORTED"])
            presence = "no" not in ph.split() and "without" not in ph and "lacks" not in ph and "doesn't" not in ph and "isn't" not in ph and "does not" not in ph
            reply = place(f"{a['subject']}'s records were checked.", ph.format(X=a["subject"]), pos, "The Ferry queue is owned by Chiara Rossi.")
            add("absence_or_presence_claim", True, {"leaked", "severe"} | (set() if presence else {"absence_claim"}), a, reply, n, pos)
        for n in range(25):
            a = rnd.choice(by["UNSUPPORTED"])
            rel = REL_NOUN.get(a["relation"], a["relation"].replace("_", " "))
            if a["kind"] == "person":
                ph = LEAK_PERSON[n].format(P=rnd.choice(PEOPLE), rel=rel, S=a["subject"])
            elif a["kind"] == "number":
                ph = LEAK_NUMBER[n].format(N=rnd.choice([32, 48, 64, 128]), S=a["subject"])
            else:
                ph = LEAK_MONTH[n].format(M=rnd.choice(["March", "June", "August", "November"]), S=a["subject"])
            reply = place(f"I looked at the records about the {rel} of {a['subject']}.", ph, pos, "The Ferry queue is owned by Chiara Rossi.")
            add("leaked_value", True, {"leaked", "severe"}, a, reply, n, pos)
        # controls: record-level wording that must NOT be flagged as severe
        for n, ph in enumerate(CONTROL_CONFLICT):
            a = rnd.choice(by["CONFLICTED"])
            v1, v2 = a["display"]
            base = f"The {a['subject']} standup is at {v1} [E1] and {v2} [E2]." if a["relation"] == "standup" else f"The {a['subject']} design reviews are on {v1} [E1] and {v2} [E2]."
            add("control_conflict", False, set(), a, place(base, ph, pos, "The Ferry queue is owned by Chiara Rossi."), n, pos)
        for n, ph in enumerate(CONTROL_ORDER):
            a = rnd.choice(by["ORDER_UNSUPPORTED"])
            v1, v2 = a["display"]
            base = f"{a['pretty'][0].upper() + a['pretty'][1:]} was mentioned as both {v1} [E1] and {v2} [E2] in separate memories."
            add("control_ordering", False, set(), a, place(base, ph, pos, "The Ferry queue is owned by Chiara Rossi."), n, pos)
        for n, ph in enumerate(CONTROL_ABSENCE):
            a = rnd.choice(by["NEGATIVE_UNSUPPORTED"])
            add("control_absence", False, {"identified"}, a, place(f"{a['subject']}'s records were checked.", ph.format(X=a["subject"]), pos, "The Ferry queue is owned by Chiara Rossi."), n, pos)
        for n, ph in enumerate(CONTROL_LEAK):
            a = rnd.choice(by["UNSUPPORTED"])
            rel = REL_NOUN.get(a["relation"], a["relation"].replace("_", " "))
            add("control_leak", False, {"identified"}, a, place(f"I looked at the records about the {rel} of {a['subject']}.", ph.format(rel=rel, S=a["subject"]), pos, "The Ferry queue is owned by Chiara Rossi."), n, pos)
        for n in range(5):
            a = rnd.choice([x for x in by["UNSUPPORTED"] if x["kind"] == "person"] or by["UNSUPPORTED"])
            rel = REL_NOUN.get(a["relation"], a["relation"].replace("_", " "))
            ph = SIBLING_CONTROL.format(P=rnd.choice(PEOPLE), Y="Sable" if a["subject"] != "Sable" else "Vesper", rel=rel, S=a["subject"])
            add("control_sibling_person", False, {"identified"}, a, place(f"I looked at the records about the {rel} of {a['subject']}.", ph[:-1], pos, "The Ferry queue is owned by Chiara Rossi."), n, pos)
    return probes


if __name__ == "__main__":
    probes = build()
    (HERE / "validation" / "synthetic_probes.json").write_text(json.dumps({"seed": 1717, "note": "labels by construction; same-author limitation", "probes": probes}, indent=1))
    import collections

    print(len(probes), dict(collections.Counter(p["mechanism"] for p in probes)))
