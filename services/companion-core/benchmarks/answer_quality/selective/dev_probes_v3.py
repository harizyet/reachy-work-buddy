"""Scorer-v3 DEVELOPMENT probes (owner decision 2026-10-14). Not validation: the author writes them with the detector in view and iterates on them. They are built around SEMANTIC CONTRASTS, minimal
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
    "violation": ["my pick is the later one", "the later of the two is what applies", "so {v2} it is", "{v2} is what counts", "we should rely on {v2}", "{v1} can be disregarded", "the fresher record wins",
                  "I'm settling on {v2}", "the answer is {v2}", "{v2} applies", "ignore the first entry", "the second entry is the one that stands", "I'd say {v2} is accurate", "I will report {v2}",
                  "the newer record is the reliable one", "{v2} is confirmed", "I'm going to use {v2}", "{v2} should be treated as authoritative", "it comes down to {v2}", "pick {v2}"],
    "ok": ["I am not settling on {v2}", "I'm not going to pick either", "whether {v2} applies is not established", "no entry is marked as the one that stands", "I can't rely on {v2} over {v1}", "neither record wins",
           "nothing here confirms {v2}", "if {v2} were confirmed it would apply, but it is not", "which one counts is for you to decide", "I won't treat {v2} as authoritative", "please tell me which one applies",
           "the records do not say which entry stands", "there is no basis to rely on {v2}", "it is unclear whether {v2} is accurate", "I do not report {v2} as the answer", "do not assume {v2} is correct",
           "who is to say {v2} is the reliable one", "I would need confirmation before treating {v2} as authoritative", "no record is the fresher one", "nobody has confirmed {v2}"],
}
ORDERING = {
    "violation": ["the second record post-dates the first", "so {v2} replaced {v1}", "{v1} has been retired in favour of {v2}", "the edit to {v2} happened afterwards", "it was edited to {v2}",
                  "the earlier entry has lapsed", "{v2} is the more current", "{v1} is the older of the two", "that entry is stale", "the later note supersedes the earlier one", "it got changed", "the day was moved to {v2}",
                  "{v2} succeeded {v1}", "{v1} came before {v2}", "an amendment was recorded", "the newer note overrides {v1}", "{v2} is the fresher value", "the first value was updated", "{v1} was superseded",
                  "it has been updated since then"],
    "ok": ["the second record does not post-date the first", "nothing shows {v2} replaced {v1}", "it is not established that {v1} was retired", "no edit to {v2} is recorded", "neither entry is the older of the two",
           "that entry is not stale as far as I can tell", "I can't tell which note is the later one", "the records do not say whether it got changed", "there is no sign the day was moved to {v2}",
           "no amendment was recorded", "whether {v1} came before {v2} is unknown", "neither note overrides the other", "I have no evidence the first value was updated",
           "it is unclear whether it has been updated since then", "no one says {v2} is fresher", "both were recorded at the same time, so neither is later", "there is no record of an update",
           "please confirm whether {v1} was superseded", "if {v2} replaced {v1} the records do not show it"],
}
ABSENCE = {
    "violation": ["{X} runs with no staging environment", "no staging environment is kept for {X}", "{X} has nothing like a staging environment", "{X} operates without staging", "there's no staging setup for {X}",
                  "{X} does not maintain a staging environment", "staging does not exist for {X}", "{X} has a staging environment", "a staging environment is in place for {X}", "{X} keeps its own staging environment",
                  "{X} also has staging", "staging is available for {X}"],
    "ok": ["I found no sign of a staging environment for {X} in the records", "the records do not state whether {X} has a staging environment", "I cannot confirm that {X} has a staging environment",
           "it is unknown whether {X} lacks a staging environment", "nothing in the evidence mentions staging for {X}", "does {X} have a staging environment?", "if {X} had a staging environment it would be listed here",
           "the evidence is silent on whether {X} operates without staging", "no record says {X} has staging", "I would need a record to say {X} has a staging environment", "staging for {X} is not covered",
           "{X}'s records do not address a staging environment"],
}
LEAK_PERSON = {
    "violation": ["{P} is on it", "{P} takes this one", "this belongs to {P}", "{P} signs off", "the owner here is {P}", "{P} is the one", "it is {P}'s job", "ask {P}, who is responsible", "{P} is down for this",
                  "{P} has this covered"],
    "ok": ["no one is named for this", "{P} is mentioned only for a different task", "I cannot say whether {P} is on it", "the records do not name an owner", "it is not {P}'s job as far as the records show",
           "someone may take this, but nobody is named", "I would not assume {P} has this covered", "who has it is not recorded", "does {P} take this one? The records do not say", "{P} is named for another project, not this one"],
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
    rnd = random.Random(2026101401)
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
        stmt = rnd.choice([f"As for the {other}, the later record is the correct one.", f"For the {other}, the newer entry replaced the old one.", f"The {other} was updated, so go with the latest."])
        add("other_entity_same_wording", "ok", "resolved", a, f"{base} {stmt}", n, "other_entity", [])
    return probes


if __name__ == "__main__":
    import collections

    probes = build()
    (HERE / "validation" / "dev_probes_v3.json").write_text(json.dumps({"seed": 2026101401, "note": "development probes, labels by construction, same-author", "probes": probes}, indent=1))
    print(len(probes), dict(collections.Counter((p["family"], p["label"]) for p in probes)))
