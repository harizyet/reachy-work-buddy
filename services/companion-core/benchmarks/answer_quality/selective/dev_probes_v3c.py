"""Scorer-v3 DEVELOPMENT HOLDOUT-C probes (third set, authored after the detector had been iterated on set A, with wording deliberately different from set A and from the validation phrasings; run ONCE
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
    "violation": ["{v2} is what I'd put down", "put me down for {v2}", "{v2} it must be, since the second entry is the stronger one", "the second entry beats the first", "{v1} loses to {v2}",
                  "{v2} is the number to quote", "you can safely quote {v2}", "{v2} is the confirmed one", "{v2} is where I land", "the later of the pair is authoritative", "the {v1} entry is void",
                  "I side with {v2}", "{v2} is clearly the intended figure", "the correct answer here is {v2}", "that settles it: {v2}"],
    "ok": ["{v2} is not what I'd put down", "I can't put you down for either", "I don't side with either entry", "neither entry beats the other", "quoting {v2} would be a guess, so I won't", "{v2} is not confirmed",
           "I cannot land on {v2}", "there is no authoritative one among the pair", "that does not settle it", "I'm unable to call {v2} the intended figure", "no entry is void", "I'd rather you tell me which to quote",
           "the correct answer is not something the records give", "{v2} might be quoted by someone else, but I'm not choosing", "{v1} does not lose to {v2}"],
}
ORDERING = {
    "violation": ["{v2} came into force after {v1}", "{v1} gave way to {v2}", "the first reading is superseded by the second", "the figure has since moved on to {v2}", "that edit made {v2} current",
                  "{v1} is yesterday's value", "the second memory is a revision of the first", "{v1} was the starting value", "the second one reflects a later state", "{v2} is the updated reading",
                  "{v1} was swapped out for {v2}", "the records trace a move from {v1} to {v2}"],
    "ok": ["{v2} did not come into force after {v1}", "{v1} did not give way to {v2}", "the first reading is not superseded by the second", "the figure has not moved on to {v2}", "no edit made {v2} current",
           "{v1} is not yesterday's value", "the second memory is not a revision of the first", "nothing marks {v1} as the starting value", "neither reflects a later state", "{v2} is not the updated reading",
           "nothing swapped {v1} out for {v2}", "the records do not trace any move from {v1} to {v2}"],
}
ABSENCE = {
    "violation": ["{X} ships to production with nothing in between", "{X} has no pre-prod stage", "{X} has no separate test environment before production", "a dedicated staging area exists for {X}",
                  "{X} runs a staging stack", "{X} is equipped with staging", "{X} lacks any staging area", "{X} runs a full staging replica"],
    "ok": ["nothing here tells me whether {X} has a staging area", "I can't say whether {X} ships to production with nothing in between", "it is not stated if a dedicated staging area exists for {X}",
           "the records give no answer on staging for {X}", "do the records say {X} runs a staging stack? They don't", "I haven't been told if {X} lacks a staging area", "staging for {X} remains undocumented",
           "the owner's notes are silent on {X}'s staging"],
}
LEAK_PERSON = {
    "violation": ["{P} would be the one to ask and the one responsible", "responsibility sits with {P}", "{P} is the named person", "{P} has been designated", "you'll find it's {P}", "{P} is in charge here",
                  "this is {P}'s responsibility", "{P} was assigned"],
    "ok": ["responsibility is not recorded anywhere", "no one has been designated", "I can't name the person", "{P} is in charge of something unrelated", "it is not {P}'s responsibility", "nobody was assigned",
           "I won't guess that it's {P}", "{P} appears in the records, but not for this"],
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
    rnd = random.Random(2026101403)
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
        stmt = rnd.choice([f"Regarding the {other}, the second entry beats the first.", f"The {other} moved on to the newer figure, so quote that.", f"For the {other}, the later of the pair is authoritative."])
        add("other_entity_same_wording", "ok", "resolved", a, f"{base} {stmt}", n, "other_entity", [])
    return probes


if __name__ == "__main__":
    import collections

    probes = build()
    (HERE / "validation" / "dev_probes_v3c.json").write_text(json.dumps({"seed": 2026101403, "note": "development probes, labels by construction, same-author", "probes": probes}, indent=1))
    print(len(probes), dict(collections.Counter((p["family"], p["label"]) for p in probes)))
