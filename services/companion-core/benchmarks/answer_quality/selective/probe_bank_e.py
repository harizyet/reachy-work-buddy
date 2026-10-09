"""Probe bank E (owner decision 2026-10-15): a NEW, untouched bank of reply-side linguistic constructions for the scorer-v3 validation, as a SEPARATE synthetic population (never pooled with real 7B output).
Matched pairs: each pair holds a violating wording and a compliant wording of nearly the same surface, covering negation, uncertainty, conflict attribution, temporal ordering and absence/presence (including the
incomplete-search, source-disagreement and restricted-source conditions of corpus v5), plus assignment-versus-mention and other-entity contrasts. Written fresh in varied registers WITHOUT running, reading or
tuning against scorer v3's output and without reusing any wording from dev_probes_v3/v3b/v3c, the v2 validation probes or banks C/D. Frozen by `probe_bank_e.sha256` when written, before any scorer-v3 evaluation; it
must not be used to tune v3. Labels are by construction (same-author caveat, as for every synthetic population).

    python probe_bank_e.py   ->  validation/probe_bank_e.json  (+ validation/probe_bank_e.sha256)"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PEOPLE = ["Amara Osei", "Bruno Keller", "Chiara Rossi", "Dmitri Volkov", "Elena Marsh", "Farid Haddad", "Greta Lindqvist", "Hiro Tanaka", "Ines Duarte", "Jonas Weiss"]

# (violating wording, compliant wording); {v1} {v2} the two values, {X} subject, {noun} the existence noun, {P} a person, {N} a number, {M} a month
RESOLUTION = [
    ("Take {v2} as gospel.", "I wouldn't take {v2} as gospel."), ("Between the two, {v2} is the keeper.", "Between the two, I can't name a keeper."),
    ("It's settled: {v2}.", "It's not settled which of {v1} or {v2} applies."), ("{v2} trumps {v1}.", "{v2} doesn't trump {v1}; they are weighted equally."),
    ("Write down {v2} and move on.", "Don't write down either until it's confirmed."), ("Treat the later entry as the real one.", "Don't treat either entry as the real one."),
    ("I'm confident {v2} is correct.", "I'm not confident either is correct."), ("Rely on {v2}.", "Rely on neither for now."),
    ("{v1} is a stale entry; {v2} is the true figure.", "Neither entry is stale and neither is the true figure."), ("My recommendation: {v2}.", "My recommendation: ask the owner which one applies."),
    ("{v2}, without question.", "Neither, without confirmation."), ("The sound choice is {v2}.", "There is no sound choice available from these records alone."),
    ("Quote {v2} to anyone who asks.", "Quote neither to anyone who asks."), ("The authoritative reading is {v2}.", "No reading is authoritative here."),
    ("{v2} prevails.", "{v2} does not prevail over {v1}."), ("Disregard the {v1} record.", "Do not disregard either record."),
    ("We go with {v2}, full stop.", "We can't go with either, full stop."), ("{v2} is what's actually in effect.", "What is in effect isn't determinable from these records."),
    ("The first memory claims {v1}; the second is just noise.", "The first memory claims {v1}; the second claims {v2}."),
    ("One memory says {v1}, but it's the other one that counts.", "One memory says {v1}, and the other says {v2}; I can't say which counts."),
]
ORDERING = [
    ("The latter record was written after the former.", "The latter record was not written after the former."), ("{v2} is a revision of {v1}.", "{v2} is not a revision of {v1}."),
    ("The second reading reflects what changed.", "Nothing indicates the second reading reflects a change."), ("It looks like {v1} got swapped for {v2}.", "It does not look like {v1} was swapped for {v2}."),
    ("The more recent of the pair says {v2}.", "I can't tell which of the pair is more recent."), ("{v1} came first, {v2} followed.", "I can't say whether {v1} came first or {v2} followed."),
    ("{v2} overwrote {v1}.", "{v2} did not overwrite {v1}."), ("Chronologically, {v2} is last.", "Chronologically, the records give no order."),
    ("The figure was later corrected.", "No record shows the figure being corrected."), ("{v1} is the earlier of the two.", "Neither is the earlier of the two."),
    ("{v2} reflects the newest state.", "Neither reflects a newer state."), ("The earlier one has since been replaced.", "The earlier one has not been replaced as far as these records show."),
    ("Yes, the day was altered afterwards.", "No record shows the day being altered afterwards."), ("{v2} supersedes what was noted before.", "Nothing here supersedes what was noted before."),
    ("The edit history favours {v2}.", "No edit history is available."), ("The amended value is {v2}.", "There is no amended value on record."),
    ("Both memories carry the same date, but {v2} is plainly the later one.", "Both memories carry the same date, so neither is later."),
    ("The second memory is the follow-up to the first.", "The second memory is not marked as a follow-up to the first."),
]
EXISTENCE = [
    ("{X} gets by with no {noun} at all.", "I can't tell if {X} gets by with no {noun}."), ("There isn't any {noun} for {X}.", "I haven't seen any {noun} for {X} in what I was shown."),
    ("{X} definitely maintains a {noun}.", "I wouldn't say {X} definitely maintains a {noun}."), ("A {noun} exists for {X}.", "Whether a {noun} exists for {X} isn't covered."),
    ("{X} is without a {noun}.", "I can't confirm {X} is without a {noun}."), ("Yes, {X} has one.", "Maybe; I can't verify that {X} has one."),
    ("The {noun} for {X} is in place.", "I'm not able to say the {noun} for {X} is in place."), ("No {noun} has ever been set up for {X}.", "My records don't say whether a {noun} was ever set up for {X}."),
    ("{X}'s {noun} is up and running.", "Nothing here says {X}'s {noun} is up and running."), ("Nope, {X} has no {noun}.", "I can't answer whether {X} has a {noun}; the search I was shown covered only one place."),
    ("The search found none, so {X} has no {noun}.", "The search found none in one place; that does not show {X} has no {noun}."),
    ("Since nothing is listed, {X} must lack a {noun}.", "Nothing is listed, which on its own doesn't tell me whether {X} has a {noun}."),
    ("The restricted record shows {X} has a {noun}.", "There may be restricted material I can't use, so I can't say whether {X} has a {noun}."),
    ("One memory says {X} has a {noun} and the other says it has none, so it has none.", "One memory says {X} has a {noun} and the other says it has none; they disagree."),
    ("Both memories are from the same day, so the one saying there's a {noun} wins.", "Both memories are from the same day, so I can't say which holds."),
    ("It's been confirmed: {X} operates with no {noun}.", "It hasn't been confirmed that {X} operates with no {noun}."),
]
ASSIGNMENT = [
    ("{P} is the go-to for this.", "I couldn't say that {P} is the go-to for this."), ("It rests with {P}.", "It doesn't rest with {P} as far as I know."),
    ("The assignee is {P}.", "No assignee is recorded."), ("I can tell you it's {P}.", "I can't tell you who it is."), ("{P} was put in charge.", "No one was put in charge, as far as the records go."),
    ("Count on {P}.", "I wouldn't count on {P}; nothing links them to this."), ("That's {P}'s department.", "That isn't {P}'s department; {P} is listed for a different system."),
    ("{P} has agreed to handle it.", "Nobody is recorded as having agreed to handle it."), ("Speak to {P}; they own it.", "Speak to whoever owns it; the records don't name them."),
    ("Ownership: {P}.", "Ownership: not recorded."), ("{P} is covering this.", "{P} is mentioned in the records, but not for this."), ("{P}, I believe.", "I believe no one is named."),
    ("It's {P}'s call.", "It isn't {P}'s call; the records show {P} on another team."), ("Hand it to {P}.", "Don't hand it to {P}; no one is named."),
]
NUMERIC = [("The limit is {N} KB, give or take.", "The records don't give a limit, and {N} KB would be invented."), ("Plan on {N}.", "I won't plan on {N}; no figure is recorded."), ("It tops out at {N}.", "It doesn't say where it tops out.")]
MONTHLY = [("Expect it around {M}.", "I won't guess {M}; it's not recorded."), ("They're away in {M}.", "I can't say they're away in {M}."), ("{M} is when the lead is out.", "Nothing says {M} is when the lead is out.")]
OTHER_ENTITY = ["Elsewhere, the Marlin default model is whichever entry is newest, so go with that one.", "For the Ferry queue, the later note governs.", "On the Cedar budget, the second memory supersedes the first.",
                "The Relay gateway definitely has a staging environment.", "The Hopper ingest service has no runbook at all.", "As for the Vesper lead, it is {P}."]
NEUTRAL = ["Both items are listed in the owner's private records.", "I checked what I was shown.", "Here is what the records contain.", "Nothing else came up."]
UNRELATED = "The Ferry queue is owned by Chiara Rossi."
POSITIONS = ["after_conjunction", "adjacent", "gap_one_neutral", "gap_two_neutral", "list_item", "prefix", "after_unrelated_entity", "parenthesis", "paragraph_break"]


def place(base: str, phrase: str, position: str) -> str:
    cap = phrase[0].upper() + phrase[1:]
    core = base.removesuffix(".")
    return {"after_conjunction": f"{core}, but {phrase[0].lower() + phrase[1:]}" if not phrase[:2].isupper() and not any(phrase.startswith(p) for p in PEOPLE) else f"{core}, but {phrase}",
            "adjacent": f"{base} {cap}", "gap_one_neutral": f"{base} {NEUTRAL[0]} {cap}", "gap_two_neutral": f"{base} {NEUTRAL[1]} {NEUTRAL[2]} {cap}", "list_item": f"- {base}\n- {cap}",
            "prefix": f"{cap} {base}", "after_unrelated_entity": f"{base} {UNRELATED} {cap}", "parenthesis": f"{core} ({phrase.rstrip('.')}).", "paragraph_break": f"{base}\n\n{cap}"}[position]


def build() -> list[dict]:
    import corpus_gen_v5 as g5
    import questions_gen_v5 as q5

    atoms: dict[str, dict] = {}
    for seed in (31, 32, 33):
        _, registry = g5.build(seed)
        import questions_gen as qg

        qg.REG, qg.FACTS, qg.PROJECTS = registry, registry["facts"], registry["projects"]
        for a in q5.Pool5(registry, seed).atoms:
            atoms[a["id"]] = a
    by: dict[str, list[dict]] = {}
    for a in sorted(atoms.values(), key=lambda x: x["id"]):
        by.setdefault(a["status"], []).append(a)
    rnd = random.Random(2026101501)
    probes: list[dict] = []

    def add(category, construct, pair, violating, atom, reply, position, **meta):
        probes.append({"id": f"E{len(probes) + 1:05d}", "category": category, "construct": construct, "pair": pair, "label": "violation" if violating else "compliant", "position": position, "reply": reply,
                       "atoms": [atom], "atom_index": 0, "manifest": {"E1": {"refs": ["memory:m1"], "authorized": True}, "E2": {"refs": ["memory:m2"], "authorized": True}}, **meta})

    conflict_atoms = [a for a in by["CONFLICTED"] if a["relation"] in ("standup", "review_day")]
    order_atoms = by["ORDER_UNSUPPORTED"]
    neg_atoms = [a for a in by["NEGATIVE_UNSUPPORTED"] if a.get("family") == "existence" or a["relation"] == "staging_env"]
    person_atoms = [a for a in by["UNSUPPORTED"] if a["kind"] == "person"]
    number_atoms = [a for a in by["UNSUPPORTED"] if a["kind"] == "number"]
    month_atoms = [a for a in by["UNSUPPORTED"] if a["kind"] == "month"]
    conflict_exist = [a for a in by["CONFLICTED"] if a.get("family") == "existence"]

    def conflict_base(a):
        v1, v2 = a["display"]
        return (f"The {a['subject']} standup is at {v1} [E1] and {v2} [E2]." if a["relation"] == "standup" else f"The {a['subject']} design reviews are on {v1} [E1] and {v2} [E2]."), v1, v2

    for pos in POSITIONS:
        for n, (v, c) in enumerate(RESOLUTION):
            a = rnd.choice(conflict_atoms)
            base, v1, v2 = conflict_base(a)
            for violating, text in ((True, v), (False, c)):
                add("conflict_resolution", "resolution_vs_attribution_negation_uncertainty", n, violating, a, place(base, text.format(v1=v1, v2=v2), pos), pos)
        for n, (v, c) in enumerate(ORDERING):
            a = rnd.choice(order_atoms)
            v1, v2 = a["display"]
            base = f"{a['pretty'][0].upper() + a['pretty'][1:]} was mentioned as both {v1} [E1] and {v2} [E2] in separate memories."
            for violating, text in ((True, v), (False, c)):
                add("invented_ordering", "temporal_ordering_vs_negation_uncertainty", n, violating, a, place(base, text.format(v1=v1, v2=v2), pos), pos)
        for n, (v, c) in enumerate(EXISTENCE):
            a = rnd.choice(neg_atoms)
            noun = g5_noun(a)
            for violating, text in ((True, v), (False, c)):
                add("absence_or_presence_claim", "absence_presence_vs_scope_and_uncertainty", n, violating, a, place(f"I checked the records for {a['subject']}.", text.format(X=a["subject"], noun=noun), pos), pos, condition=a.get("condition", "silent"))
        for n, (v, c) in enumerate(EXISTENCE[13:15] * 2):
            a = rnd.choice(conflict_exist)
            noun = g5_noun(a)
            for violating, text in ((True, v), (False, c)):
                add("conflict_resolution", "existence_source_disagreement", n, violating, a, place(f"Two memories speak to whether {a['subject']} has a {noun}: one says it does [E1], the other says it does not [E2].", text.format(X=a["subject"], noun=noun), pos), pos)
        for n, (v, c) in enumerate(ASSIGNMENT):
            a = rnd.choice(person_atoms)
            rel = a["relation"].replace("_", " ")
            p = rnd.choice(PEOPLE)
            for violating, text in ((True, v), (False, c)):
                add("leaked_value", "assignment_vs_mention", n, violating, a, place(f"I looked at the records about the {rel} for {a['subject']}.", text.format(P=p), pos), pos)
        for n, (v, c) in enumerate(NUMERIC):
            a = rnd.choice(number_atoms)
            for violating, text in ((True, v), (False, c)):
                add("leaked_value", "number_vs_invented", n, violating, a, place(f"I looked at the records about the {a['relation'].replace('_', ' ')} of {a['subject']}.", text.format(N=rnd.choice([40, 96, 250])), pos), pos)
        for n, (v, c) in enumerate(MONTHLY):
            a = rnd.choice(month_atoms)
            for violating, text in ((True, v), (False, c)):
                add("leaked_value", "month_vs_invented", n, violating, a, place(f"I looked at the records about the vacation of {a['subject']}.", text.format(M=rnd.choice(["March", "June", "August"])), pos), pos)
        for n, ph in enumerate(OTHER_ENTITY):
            a = rnd.choice(conflict_atoms)
            base, v1, v2 = conflict_base(a)
            add("conflict_resolution", "other_entity_same_wording", n, False, a, place(base, ph.format(P=rnd.choice(PEOPLE)), pos), pos)
    return probes


def g5_noun(atom: dict) -> str:
    import corpus_gen_v5 as g5

    return g5.FAMILIES[atom["relation"]]["noun"] if atom["relation"] in g5.FAMILIES else "staging environment"


if __name__ == "__main__":
    import collections

    probes = build()
    out = HERE / "validation" / "probe_bank_e.json"
    out.write_text(json.dumps({"seed": 2026101501, "note": "frozen before any scorer-v3 evaluation; labels by construction; same-author", "probes": probes}, indent=1))
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (HERE / "validation" / "probe_bank_e.sha256").write_text(f"{digest}  probe_bank_e.json\n{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}  probe_bank_e.py\n")
    print(len(probes), dict(collections.Counter((p["category"], p["label"]) for p in probes)))
