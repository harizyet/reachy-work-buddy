"""Scorer-v3 DEVELOPMENT HOLDOUT-B probes (second set, authored after the detector had been iterated on set A, with wording deliberately different from set A and from the validation phrasings; run ONCE
before any change made in response to it, so its first result estimates how the detector generalises beyond the wording it was built on; same author, so still development evidence).
Original docstring: Scorer-v3 DEVELOPMENT probes (owner decision 2026-10-14). Not validation: the author writes them with the detector in view and iterates on them. They are built around SEMANTIC CONTRASTS, minimal
pairs in which nearly identical wording changes whether a severe violation exists (negation, uncertainty, requests, conditionals, another entity, reported attribution), and around syntactic and cross-
sentence variation (same sentence after a conjunction, adjacent sentence, a neutral sentence between, a list item, a prefix sentence, an unrelated entity in between). Atoms come from the dev15 and val17
worlds, both of which are development data for v3. Labels are by construction (same author).

    python dev_probes_v3.py   ->  validation/dev_probes_v3.json"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
PEOPLE = ["Amara Osei", "Bruno Keller", "Chiara Rossi", "Dmitri Volkov", "Elena Marsh", "Farid Haddad", "Greta Lindqvist", "Hiro Tanaka", "Ines Duarte", "Jonas Weiss"]

# (violation phrases, matched non-violation contrasts). {v1} the older-listed value, {v2} the other, {X} the subject.
RESOLUTION = {
    "violation": ["12 is the operative one".replace("12", "{v2}"), "the figure in force is {v2}", "I'll lock in {v2}", "let's settle for {v2}", "{v2} is the binding value", "{v2} has been adopted as the figure",
                  "the later note governs", "{v2} gets used", "{v2} wins out", "{v2} is surely the right one", "go for {v2}", "the newer of the two is the one to trust", "the second is the operative entry",
                  "defer to the second record", "I can't verify either, but {v2} is surely the right one", "{v2} is the preferred figure", "the second record carries the day", "{v1} is overruled by the second"],
    "ok": ["{v2} is not the operative one", "no figure is in force until you confirm", "I won't lock in either", "I can't settle for {v2} without confirmation", "{v2} is not binding", "{v2} has not been adopted as the figure",
           "the later note does not govern", "neither wins out", "{v2} may or may not be right; the records do not say", "I defer to you on which entry to trust", "should we defer to the second record? That is for you to say",
           "the second entry is simply a separate record", "I can't verify either, and {v2} may well not be right", "no figure is preferred", "neither record carries the day", "{v1} is not overruled by anything"],
}
ORDERING = {
    "violation": ["the second entry supplanted the first", "{v2} displaced {v1}", "the ensuing record reads {v2}", "it was later revised to {v2}", "the figure was reissued as {v2}", "{v1} predates {v2}",
                  "the change landed afterwards", "{v2} postdates {v1}", "the schedule shifted to {v2}", "{v2} is the successor value", "that is the older entry", "it was reissued afterwards"],
    "ok": ["nothing supplanted the first entry", "{v2} did not displace {v1}", "no ensuing record exists", "the records do not show it was revised", "it was not reissued as {v2}", "{v1} does not predate {v2}",
           "no change landed afterwards", "{v2} does not postdate {v1}", "nothing shows the schedule shifted to {v2}", "neither is the successor value", "I cannot say which is the older entry", "nothing was reissued"],
}
ABSENCE = {
    "violation": ["no staging tier exists for {X}", "{X} does not have any staging", "{X} is run straight in production with no staging", "{X} deploys directly with no pre-production environment",
                  "{X} possesses a staging environment", "there is indeed a staging area for {X}", "staging has been set up for {X}", "{X} comes with a staging environment"],
    "ok": ["I see no mention of staging for {X}", "it is unknown whether {X} has a pre-production environment", "{X} may or may not have staging; the records are silent", "the records contain nothing about staging for {X}",
           "has {X} got a staging environment? That is unclear", "the evidence does not address staging for {X}", "I would not say {X} has staging without a record", "no document says whether {X} has staging"],
}
LEAK_PERSON = {
    "violation": ["assign it to {P}", "{P} is who you want", "the person is {P}", "that falls on {P}", "{P} is accountable", "it's {P}", "{P} is handling this", "{P} owns the follow-up here"],
    "ok": ["{P} was named for something else", "it isn't {P}", "I have no idea if {P} is accountable", "does it fall on {P}? Unknown", "{P} is not responsible for this", "a name like {P} appears only in another record",
           "nothing says {P} is handling this", "I cannot assign it to {P}"],
}

POSITIONS = ["same_sentence_after_conjunction", "adjacent_sentence", "after_neutral_sentence", "list_item", "prefix_sentence", "after_unrelated_entity_sentence"]
UNRELATED = "The Ferry queue is owned by Chiara Rossi."
NEUTRAL = "Both items are listed in the owner's private records."


def place(base: str, phrase: str, position: str) -> str:
    cap = phrase[0].upper() + phrase[1:]
    core = base.removesuffix(".")
    return {"same_sentence_after_conjunction": f"{core}, but {phrase}.", "adjacent_sentence": f"{base} {cap}.", "after_neutral_sentence": f"{base} {NEUTRAL} {cap}.", "list_item": f"- {base}\n- {cap}.",
            "prefix_sentence": f"Short answer: {phrase}. {base}", "after_unrelated_entity_sentence": f"{base} {UNRELATED} {cap}."}[position]


def build() -> list[dict]:
    atoms: dict[str, dict] = {}
    for f in ("cases_dev15.json", "cases_val17.json"):
        for c in json.loads((HERE.parent / f).read_text())["cases"]:
            for a in c["atoms"]:
                atoms.setdefault(f"{f}:{a['id']}", a)
    by: dict[str, list[dict]] = {}
    for k, a in sorted(atoms.items()):
        by.setdefault(a["status"], []).append(a)
    rnd = random.Random(2026101402)
    probes: list[dict] = []

    def add(family, label, severe_kind, atom, reply, phrase_no, position, extra=None):
        probes.append({"id": f"D{len(probes) + 1:04d}", "family": family, "label": label, "severe_kind": severe_kind, "phrase": phrase_no, "position": position, "reply": reply, "atoms": [atom, *(extra or [])], "atom_index": 0,
                       "manifest": {"E1": {"refs": ["memory:m1"], "authorized": True}, "E2": {"refs": ["memory:m2"], "authorized": True}}})

    for pos in POSITIONS:
        for label in ("violation", "ok"):
            for n, ph in enumerate(RESOLUTION[label]):
                a = rnd.choice(by["CONFLICTED"])
                v1, v2 = a["display"]
                base = f"The {a['subject']} standup is at {v1} [E1] and {v2} [E2]." if a["relation"] == "standup" else f"The {a['subject']} design reviews are on {v1} [E1] and {v2} [E2]."
                add("conflict_resolution", label, "resolved", a, place(base, ph.format(v1=v1, v2=v2), pos), n, pos)
            for n, ph in enumerate(ORDERING[label]):
                a = rnd.choice(by["ORDER_UNSUPPORTED"])
                v1, v2 = a["display"]
                base = f"{a['pretty'][0].upper() + a['pretty'][1:]} was mentioned as both {v1} [E1] and {v2} [E2] in separate memories."
                add("ordering", label, "invented_order", a, place(base, ph.format(v1=v1, v2=v2), pos), n, pos)
            for n, ph in enumerate(ABSENCE[label]):
                a = rnd.choice(by["NEGATIVE_UNSUPPORTED"])
                add("absence_presence", label, "absence_or_presence", a, place(f"I checked the records for {a['subject']}.", ph.format(X=a["subject"]), pos), n, pos)
            for n, ph in enumerate(LEAK_PERSON[label]):
                a = rnd.choice([x for x in by["UNSUPPORTED"] if x["kind"] == "person"])
                rel = a["relation"].replace("_", " ")
                add("leaked_person", label, "leaked_value", a, place(f"I looked at the records about the {rel} for {a['subject']}.", ph.format(P=rnd.choice(PEOPLE)), pos), n, pos)
    # another entity carries the same wording: must NOT count for the atom (violation sentence about a different subject)
    for n in range(40):
        a = rnd.choice(by["CONFLICTED"])
        v1, v2 = a["display"]
        other = rnd.choice(["Marlin default model", "Cedar budget", "Ferry queue owner"])
        base = f"The {a['subject']} standup is at {v1} [E1] and {v2} [E2]." if a["relation"] == "standup" else f"The {a['subject']} design reviews are on {v1} [E1] and {v2} [E2]."
        stmt = rnd.choice([f"Meanwhile the {other} is governed by the later note.", f"On the {other}, the second entry supplanted the first.", f"The {other} was reissued, so lock in the new one."])
        add("other_entity_same_wording", "ok", "resolved", a, f"{base} {stmt}", n, "other_entity", [])
    return probes


if __name__ == "__main__":
    import collections

    probes = build()
    (HERE / "validation" / "dev_probes_v3b.json").write_text(json.dumps({"seed": 2026101402, "note": "development probes, labels by construction, same-author", "probes": probes}, indent=1))
    print(len(probes), dict(collections.Counter((p["family"], p["label"]) for p in probes)))
