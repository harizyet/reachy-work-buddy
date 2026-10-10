"""I-2 follow-up (2026-10-10): the deterministic typed-template path on dev15, re-run with the typed entity registry, the gold-independent relation registry and the question-side decomposer. NO MODEL. dev16 untouched.

Two separate evaluations on the SAME dev15 questions, plus the before/after arms and a renamed-world check:

  GOLD-SPEC (what is isolated: evidence admission and rendering). The sub-claim structure (subject, relation, ask, time scope) is taken from the dev15 gold annotation, as in the first I-2 run.
    G-old       gold structure, gold-derived relation specs, the first run's known-subject list       (reproduces the recorded 267/307)
    G-typed     the same, with only the model-name collision fixed by typed competing subjects       (isolates the typing fix)
    G-registry  gold structure, but relation specs / labels / competing subjects from the gold-independent registry (isolates the spec source)
  QUESTION-TEXT-ONLY (the real end-to-end deterministic path: question text -> decomposer -> registry specs -> pipeline). Nothing from the gold is read except to SCORE.
    T-old       the first run's decomposer with gold-derived specs                                    (the recorded 124-of-173 fallback)
    T-grammar   the new decomposer, registry specs, entities typed by grammar alone
    T-new       the new decomposer, registry specs, grammar plus entities learned from the record pool (also recognises lower-case spellings)
  T-renamed     T-grammar on a world in which every project, system, model, vendor and person name is replaced by a name never seen before (same structure, same sentences)

Scoring is deterministic against the registry gold; for a text arm each gold sub-claim is ALIGNED to the component with the same subject and relation (a gold sub-claim with none is NOT_TYPED, a component with
no gold sub-claim is SPURIOUS: an invented structure). The frozen review sample and the decomposition set are verified before the run.

    python i2b_eval.py   -> results/i2b-dev15-report.json, results/i2b-dev15-replies-<arm>.jsonl
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import statistics
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG_ARGV = list(sys.argv)  # i2_eval replaces sys.argv with the B-1 configuration flags at import
import i2_eval as i2

h = i2.h
from companion_core.knowledge.answerability_b1 import (
    AuthDecision,
    Component,
    build_plan,
    decompose,
)
from companion_core.knowledge.answerability_b1.questions import (
    plan_question,
)
from companion_core.knowledge.answerability_b1.registry import Registry
from companion_core.knowledge.answerability_b1.types import Ask, Scope

OUT = HERE.parent / "results"
NOW = h.NOW
ANSWERED, WITHHELD_GOLD = i2.ANSWERED, i2.WITHHELD_GOLD
CANON = {"default_model_history": "default_model", "retry_limit_history": "retry_limit"}


def verify_frozen() -> None:
    for manifest in ("REVIEW_SAMPLE_FREEZE.sha256", "DECOMPOSITION_SET.sha256"):
        for line in (HERE / manifest).read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            digest, name = line.split()
            if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
                raise SystemExit(f"FROZEN FILE CHANGED: {name}")


def canon_relation(atom: dict) -> str:
    return atom.get("base_relation") if atom["relation"] == "order_figure" else CANON.get(atom["relation"], atom["relation"])


def gold_ask(atom: dict) -> Ask:
    return Ask.EXISTENCE if atom["kind"] == "bool" else Ask.ORDERING if atom["status"] == "ORDER_UNSUPPORTED" else Ask.VALUE


def gold_scope(atom: dict) -> Scope:
    return Scope.PAST if atom["status"] == "HISTORICAL" else Scope.ANY


class World:
    """One evaluation world: the discovery pool, authorisations, evidence ids and the corpus-derived inventories."""

    def __init__(self, corpus_path: Path | None = None):
        if corpus_path is not None:
            h.CORPUS = corpus_path
        self.c4, self.items, self.auths, self.eids, self.structured, self.texts, self.level = i2.build_world()
        self.ref_of = {v: k for k, v in self.eids.items()}
        self.unauth = {r for r, d in self.auths.items() if not d.authorized}
        self.registry = Registry()
        corpus_texts = [*(i.text for i in self.items), *(getattr(s, "title", "") for s in self.structured)]
        self.pool = self.registry.entities.harvest(corpus_texts)
        self.learned = Registry(entities=self.registry.entities.with_entries(self.pool))


def purity_regexes(label: str) -> dict[str, re.Pattern]:
    """The fixed code-written forms a withheld or conflicted claim may take after the final development pass (the first-run patterns of `i2_eval._purity_regexes` are kept untouched for the preserved first-run
    report). A withheld claim still contains no asserted value: the only value-bearing addition is the pending-decision sentence, allowed in exactly one form (a DECIDED or PLANNED value reported as such,
    with the statement that the records do not say it is in place)."""
    L = re.escape(label)
    cite = r"(?: ?\[[A-Z]\d+\])+"
    caveat = i2.CAVEAT
    pending = rf"(?: A record says [^.\[\]]+? (?:was decided on|is planned) for the {L}, but the records do not say it is in place{cite}\.)*"
    unclear = (rf"One record about the {L} is worded in a way I cannot read safely, so I have not answered it\.|One record says a value of the {L} is in use and another says it is retired, so I have not picked an answer\.|"
               rf"The records word the time of the {L} differently, so I have not picked an answer\.|I could not check the {L}\.")
    return {
        "UNSUPPORTED": re.compile(rf"^(?:The records do not say the {L}\.{caveat}{pending}|{unclear})$"),
        "NEGATIVE_UNSUPPORTED": re.compile(rf"^(?:The records I searched do not mention an? {L}\.{caveat}|{unclear}|"
                                           rf"(?:A search of .+? found no {L}{cite}(?:; not searched: .+?|; the record does not say where else was checked)\. ?)+That does not show there is none\.{caveat}|"
                                           rf"A record by .+? says there is no {L}{cite}, but that is not an authoritative source, so the records do not establish it\.(?: A search of .+)?)$"),
        "ORDER_UNSUPPORTED": re.compile(rf"^(?:Nothing in the records establishes an order for the {L}\.{caveat}|On the {L}, the records give .+?, but nothing in them dates one before the other\.{caveat}|{unclear})$"),
        "CONFLICTED": re.compile(rf"^The records disagree on (?:whether there is an? {L}|the {L}): .+? They do not say which applies\.{caveat}$"),
    }


def old_known(cases):
    from validate_scorer import PEOPLE

    people = {p.lower() for p in PEOPLE} | {p.split()[0].lower() for p in PEOPLE}
    known = sorted({re.sub(r"\\b", "", a["subject_re"]) for q in cases for a in q["atoms"] if a["subject_re"]} - people - {p.replace(" ", "\\ ") for p in people})
    known_raw = [k for k in known if k.replace("\\", "") not in people]
    return [k.replace("\\", "") for k in known_raw]


# --- planners: each returns (plan, components, meta) for one dev15 question; `auths` may be overridden (the revocation test) ---------------------------------------------------------------------

def make_planners(w: World, cases: list[dict]):
    known = old_known(cases)
    subjects_gold, allspecs_gold = {}, {}
    for q in cases:
        for a in q["atoms"]:
            allspecs_gold.setdefault(a["relation"], i2.spec_for(a))
            subjects_gold.setdefault(a["subject"], (re.sub(r"\\b", "", a["subject_re"]).replace("\\", ""),))

    def g_old(q, auths=None, typed=False):
        specs: dict = {}
        comps, canon = [], []
        for n, a in enumerate(q["atoms"], 1):
            subject = re.sub(r"\\b", "", a["subject_re"]).replace("\\", "")
            specs.setdefault(a["relation"], i2.spec_for(a))
            comps.append(Component(f"c{n}", a["subject"], (subject,), a["relation"], gold_ask(a), gold_scope(a), i2.LABELS[a["relation"]].format(s=a["subject"])))
            canon.append(canon_relation(a))
        by_id = {c.id: r for c, r in zip(comps, canon, strict=True)}
        if typed:
            def ks(c):
                return w.registry.competitors(by_id[c.id], c.aliases, w.pool)
        else:
            ks = known
        plan = build_plan(comps, w.items, auths or w.auths, now=NOW, specs=specs, eids=w.eids, known_subjects=ks, policy=h.POLICY, structured=w.structured)
        return plan, comps, {}

    def g_registry(q, auths=None):
        reg = w.registry
        comps = []
        for n, a in enumerate(q["atoms"], 1):
            men = [m for m in reg.entities.mentions(a["subject"]) if m.subject.casefold() == a["subject"].casefold()] or reg.entities.mentions(a["subject"])
            rel = canon_relation(a)
            comps.append(Component(f"c{n}", a["subject"], (men[0].alias,), rel, gold_ask(a), gold_scope(a), reg.label(rel, men[0])))

        def ks(c):
            return reg.competitors(c.relation, c.aliases, w.pool)

        plan = build_plan(comps, w.items, auths or w.auths, now=NOW, specs=reg.specs(), eids=w.eids, known_subjects=ks, policy=h.POLICY, structured=w.structured)
        return plan, comps, {}

    def t_old(q, auths=None):
        comps, fallback = decompose(q["question"], allspecs_gold, subjects_gold)
        plan = build_plan(comps, w.items, auths or w.auths, now=NOW, specs=allspecs_gold, eids=w.eids, known_subjects=known, policy=h.POLICY, fallback=fallback, structured=w.structured)
        return plan, list(comps), {"reasons": []}

    def t_new(registry):
        def run(q, auths=None):
            plan, dec = plan_question(q["question"], registry, w.items, auths or w.auths, now=NOW, eids=w.eids, policy=h.POLICY, structured=w.structured, pool_mentions=w.pool)
            return plan, list(dec.components), {"reasons": [c.reason for c in dec.uncertain], "clauses": [(c.text, c.reason) for c in dec.clauses]}
        return run

    return {"G-old": g_old, "G-typed": lambda q, auths=None: g_old(q, auths, typed=True), "G-registry": g_registry, "T-old": t_old, "T-grammar": t_new(w.registry), "T-new": t_new(w.learned)}


# --- scoring --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def score_arm(w: World, cases: list[dict], planner, *, canon: bool, with_revocation: bool = False) -> tuple[dict, list[dict], dict]:
    m = collections.Counter()
    by_gold = collections.defaultdict(collections.Counter)
    problems: dict[str, list] = collections.defaultdict(list)
    replies, words, cites_n = [], [], []
    partial = collections.Counter()
    reasons = collections.Counter()
    for q in cases:
        plan, comps, meta = planner(q)
        for r in meta.get("reasons", []):
            reasons[r] += 1
        key = (lambda a: (a["subject"].casefold(), canon_relation(a))) if canon else (lambda a: (a["subject"].casefold(), a["relation"]))
        used: set[int] = set()
        pairs = []
        for a in q["atoms"]:
            idx = next((i for i, c in enumerate(comps) if i not in used and c.relation is not None and (c.subject.casefold(), c.relation) == key(a)), None)
            if idx is not None:
                used.add(idx)
            pairs.append((a, idx))
        untyped = [i for i, c in enumerate(comps) if c.relation is None]
        spurious = [i for i in range(len(comps)) if i not in used and comps[i].relation is not None]
        qgood = not untyped and not spurious
        sup_ok, withheld_ok = [], []
        m["questions"] += 1
        m["questions_with_untyped_clause"] += bool(untyped)
        m["untyped_clauses"] += len(untyped)
        m["questions_all_clauses_untyped"] += len(untyped) == len(comps) and bool(comps)
        m["spurious_components"] += len(spurious)
        m["questions_with_spurious"] += bool(spurious)
        for i in spurious:
            c = plan.claims[i]
            if c.state.value in ANSWERED | {"CONFLICTED"}:
                m["spurious_answered"] += 1
                problems["spurious_answered"].append((q["id"], comps[i].subject, comps[i].relation, c.text))
            problems["spurious"].append((q["id"], comps[i].subject, comps[i].relation, comps[i].ask.value, comps[i].scope.value, q["question"]))
        for a, idx in pairs:
            gold = a["status"]
            m["atoms"] += 1
            if idx is None:
                got, ticket, claim, comp = "NOT_TYPED", None, None, None
                m["not_typed"] += 1
                if gold in ("SUPPORTED", "HISTORICAL"):
                    m["false_abstention"] += 1
                    m["false_abstention_cause:not_typed"] += 1
                    problems["false_abstention"].append((q["id"], a["id"], a["relation"], gold, got, ["not_typed"]))
                    sup_ok.append(False)
                if gold not in ("SUPPORTED", "HISTORICAL"):
                    withheld_ok.append(False)
                by_gold[gold][got] += 1
                qgood = False
                continue
            comp, ticket, claim = comps[idx], plan.tickets[idx], plan.claims[idx]
            got = claim.state.value
            m["typed"] += 1
            by_gold[gold][got] += 1
            ok = gold == got
            m["exact"] += ok
            qgood &= ok
            if comp.ask is not gold_ask(a) or (comp.scope is Scope.PAST) != (gold_scope(a) is Scope.PAST):
                m["ask_or_scope_mismatch"] += 1
                qgood = False
                problems["ask_or_scope_mismatch"].append((q["id"], a["id"], a["relation"], comp.ask.value, comp.scope.value, got))
            display = {i2.norm(d) for d in a["display"]}
            if gold in WITHHELD_GOLD and got in ANSWERED | {"CONFLICTED"}:
                m["unsupported_claim"] += 1
                problems["unsupported_claim"].append((q["id"], a["id"], gold, got, claim.text))
            if gold == "CONFLICTED" and got in ANSWERED:
                m["conflict_resolved"] += 1
            if gold == "HISTORICAL" and got == "SUPPORTED":
                m["history_as_current"] += 1
            if got in ("SUPPORTED", "HISTORICAL") and comp.ask is Ask.VALUE:
                shown = {i2.norm(v) for v, _ in ticket.values}
                many = comp.relation == "attends"
                good = shown == display if many else shown <= display
                m["answered_values"] += 1
                if not good:
                    m["wrong_value"] += 1
                    problems["wrong_value"].append((q["id"], a["id"], ticket.values, a["display"]))
            if gold in ("SUPPORTED", "HISTORICAL") and got in WITHHELD_GOLD | {"UNSUPPORTED"}:
                m["false_abstention"] += 1
                m["false_abstention_cause:evidence"] += 1
                reasons_t = list(ticket.reasons)
                for r_ in reasons_t:
                    m[f"false_abstention_reason:{r_}"] += 1
                problems["false_abstention"].append((q["id"], a["id"], a["relation"], gold, got, reasons_t))
            if gold in ("SUPPORTED", "HISTORICAL"):
                m["gold_answerable"] += 1
                sup_ok.append(got == gold)
            else:
                withheld_ok.append(ok)
        # --- every claim in the reply (aligned, spurious and untyped alike): purity, citations, authorisation
        for i, claim in enumerate(plan.claims):
            got = claim.state.value
            if got in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED", "CONFLICTED") and comps[i].relation is not None:
                pat = purity_regexes(claim.label).get(got)
                m["purity_checked"] += 1
                if pat is None or not pat.match(claim.text) or (got == "UNSUPPORTED" and claim.assertable):
                    m["purity_fail"] += 1
                    problems["purity"].append((q["id"], comps[i].id, got, claim.text))
            if comps[i].relation is None:
                m["not_understood_checked"] += 1
                if claim.text != "I could not work out one part of the question, so I have not answered it." or claim.assertable:
                    m["not_understood_impure"] += 1
            for value, ids in claim.assertable:
                m["cited_values"] += 1
                if not ids:
                    m["citation_missing"] += 1
                for e in ids:
                    ref = w.ref_of.get(e)
                    if ref is None:
                        m["citation_error"] += 1
                        problems["citation"].append((q["id"], comps[i].id, "unknown evidence id", e))
                        continue
                    if ref in w.unauth:
                        m["authorization_failure"] += 1
                        problems["authorization"].append((q["id"], comps[i].id, "cited unauthorised record", ref))
                    if value in ("present", "absent", "absent (attributed)"):
                        continue
                    hay = i2.norm(w.texts.get(ref, ""))
                    if i2.norm(value) not in hay and not set(i2.norm(value).split()) <= set(hay.split()):
                        m["citation_error"] += 1
                        problems["citation"].append((q["id"], comps[i].id, "cited record does not contain the value", value, ref))
                if not all(f"[{e}]" in claim.text for e in ids):
                    m["citation_not_in_text"] += 1
            for r_ in (r for _, refs in plan.tickets[i].values for r in refs):
                if r_ in w.unauth:
                    m["authorization_failure"] += 1
                    problems["authorization"].append((q["id"], comps[i].id, "admitted from unauthorised record", r_))
            if claim.state.value in ANSWERED and not claim.assertable:
                m["answered_without_citation"] += 1
        if len(q["atoms"]) >= 2 and any(sup_ok) and withheld_ok:
            partial["mixed_questions"] += 1
            partial["supported_part_answered"] += all(sup_ok)
            partial["withheld_parts_correct"] += all(withheld_ok)
            partial["both"] += all(sup_ok) and all(withheld_ok)
        m["questions_fully_correct"] += qgood
        m["questions_atoms_all_exact"] += all(idx is not None and plan.claims[idx].state.value == a["status"] for a, idx in pairs)
        words.append(len(plan.answer.split()))
        cites_n.append(len(re.findall(r"\[E\d+\]", plan.answer)))
        replies.append({"id": q["id"], "family": q["family"], "question": q["question"], "gold": [(a["relation"], a["subject"], a["status"], a["display"]) for a in q["atoms"]],
                        "components": [(c.subject, c.relation, c.ask.value, c.scope.value, list(c.period) if c.period else None) for c in comps], "states": [c.state.value for c in plan.claims],
                        "reasons": meta.get("reasons", []), "answer": plan.answer})
    ws = sorted(words)
    out = {"counts": {**{k: 0 for k in ("unsupported_claim", "conflict_resolved", "wrong_value", "history_as_current", "purity_fail", "citation_error", "citation_missing", "authorization_failure", "answered_without_citation",
                                        "spurious_answered", "not_understood_impure", "ask_or_scope_mismatch")}, **dict(m)},
           "exact_by_gold": {g: dict(c) for g, c in by_gold.items()}, "partial_answers": dict(partial), "untyped_reasons": dict(reasons),
           "reply_length_words": {"median": statistics.median(ws), "p90": ws[int(0.9 * len(ws))], "max": ws[-1]}, "citations_per_reply_median": statistics.median(cites_n)}
    if with_revocation:
        out["revocation"] = revocation(w, cases, planner)
    return out, replies, problems


def revocation(w: World, cases: list[dict], planner) -> dict:
    """For every question with an answered claim: revoke (or make stale) exactly the records its answered claims cite and rebuild the whole plan. No claim may still cite a revoked record; a claim that is now
    withheld must be a plain template without a value."""
    r = collections.Counter()
    for q in cases:
        plan, _comps, _ = planner(q)
        answered = [i for i, c in enumerate(plan.claims) if c.state.value in ANSWERED and plan.tickets[i].values]
        if not answered:
            continue
        cited = {ref for i in answered for _, refs in plan.tickets[i].values for ref in refs}
        for mode in ("revoked", "stale"):
            bad = {ref: (AuthDecision(False, d.checked_at, d.policy_version, d.acl_revision) if mode == "revoked" else AuthDecision(True, NOW - timedelta(hours=2), d.policy_version, d.acl_revision)) if ref in cited else d for ref, d in w.auths.items()}
            p2, _c2, _ = planner(q, bad)
            for i in answered:
                r[f"{mode}_claims_tested"] += 1
                new = p2.claims[i]
                still = {ref for _, refs in p2.tickets[i].values for ref in refs} & cited
                if still:
                    r[f"{mode}_STILL_CITES_REVOKED"] += 1
                elif new.state.value in ANSWERED:
                    r[f"{mode}_resupported_by_other_authorised_record"] += 1
                else:
                    r[f"{mode}_withheld"] += 1
                    pat = purity_regexes(new.label).get(new.state.value)
                    if (pat is not None and not pat.match(new.text)) or new.assertable:
                        r[f"{mode}_withheld_text_impure"] += 1
    return dict(r)


def renamed_world(tmp: Path) -> tuple[Path, dict[str, str]]:
    """Corpus v4 with every project, system head word, model, vendor and person replaced by a name that is not in the invented corpus, consistently in every record. Structure and sentences are unchanged."""
    from validate_scorer import PEOPLE

    c4 = json.loads(h.CORPUS.read_text())
    projects = ["Cedar", "Marlin", "Juniper", "Osprey", "Tamarind", "Vesper", "Pinnacle", "Quartz", "Sable", "Thistle", "Umbra", "Willow"]
    new_projects = ["Harbor", "Lantern", "Meadow", "Zenith", "Aspen", "Briar", "Garnet", "Nightjar", "Ibex", "Tidewater", "Falconry", "Orchid"]
    heads = ["Ferry", "Gantry", "Relay", "Hopper", "Sluice", "Turret", "Conduit", "Lattice", "Prism", "Anvil", "Cobalt", "Mosaic"]
    new_heads = ["Beacon", "Kiln", "Pylon", "Quill", "Cinder", "Ember", "Loom", "Shale", "Glint", "Forge", "Vault", "Atlas"]
    models = ["Kestrel-3B", "Kestrel-9B", "Merlin-2B", "Merlin-7B", "Heron-4B", "Heron-12B", "Swift-6B", "Swift-20B"]
    new_models = ["Wren-3B", "Wren-9B", "Raven-2B", "Raven-7B", "Lynx-4B", "Lynx-12B", "Orca-6B", "Orca-20B"]
    vendors = ["Nimbus Metrics", "Quarry Data", "Falconer Logs", "Tidewater Pay", "Brightwell Mail", "Ironside Backup"]
    new_vendors = ["Acme Freight", "Zephyr Telecom", "Borealis Cloud", "Northwind Traders", "Pelican Print", "Granite Audit"]
    first = ["Nadia", "Marco", "Priya", "Kofi", "Anya", "Tomas", "Leila", "Ravi", "Sofia", "Emeka", "Hana", "Dario", "Iris", "Jamal", "Keiko", "Lucas", "Maya", "Nico", "Oksana", "Pavel", "Quentin", "Rosa", "Soren", "Thea"]
    last = ["Orlov", "Bianchi", "Nair", "Mensah", "Petrenko", "Varga", "Haddad", "Iyer", "Costa", "Okoro", "Sato", "Moretti", "Lund", "Kamara", "Ito", "Silva", "Cohen", "Baptiste", "Ivanova", "Novak", "Reyes", "Alvarez", "Berg", "Quist"]
    mapping: dict[str, str] = {}
    for a, b in zip(PEOPLE, [f"{f} {ls}" for f, ls in zip(first, last, strict=True)], strict=True):
        mapping[a] = b
        mapping[a.split()[0]] = b.split()[0]
    for src, dst in ((projects, new_projects), (heads, new_heads), (models, new_models), (vendors, new_vendors)):
        mapping.update(dict(zip(src, dst, strict=True)))
    rx = re.compile("|".join(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])" for k in sorted(mapping, key=len, reverse=True)))

    def ren(s):
        return rx.sub(lambda mo: mapping[mo.group(0)], s) if isinstance(s, str) else s

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return ren(o)

    # ids and refs embed project slugs; a consistent lower-case mapping keeps every ref resolvable
    slug_map = {k.lower().replace(" ", "-"): v.lower().replace(" ", "-") for k, v in mapping.items()}
    rx2 = re.compile("|".join(r"(?<![\w])" + re.escape(k) + r"(?![\w])" for k in sorted(slug_map, key=len, reverse=True)))
    text = json.dumps(walk(c4))
    text = rx2.sub(lambda mo: slug_map[mo.group(0)], text)
    out = tmp / "corpus_v4_renamed.json"
    out.write_text(text)
    return out, mapping


def main() -> None:
    verify_frozen()
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    w = World()
    planners = make_planners(w, cases)
    report: dict = {"scope": "dev15 only; no model; dev16 untouched; the recorded first-run report (i2-dev15-report.json) is not modified", "arms": {}}
    problems_all, replies_all = {}, {}
    for arm, canon in (("G-old", False), ("G-typed", False), ("G-registry", True), ("T-old", False), ("T-grammar", True), ("T-new", True)):
        res, replies, problems = score_arm(w, cases, planners[arm], canon=canon, with_revocation=arm in ("G-registry", "T-new"))
        report["arms"][arm] = res
        problems_all[arm] = {k: v for k, v in problems.items()}
        replies_all[arm] = replies
        (OUT / f"i2b-dev15-replies-{arm}.jsonl").write_text("\n".join(json.dumps(r) for r in replies))
        c = res["counts"]
        print(f"{arm:11s} atoms {c['atoms']}: exact {c.get('exact', 0)}, not typed {c.get('not_typed', 0)}, false abstention {c.get('false_abstention', 0)}, unsupported {c['unsupported_claim']}, wrong values {c['wrong_value']}, "
              f"spurious {c.get('spurious_components', 0)} (answered {c['spurious_answered']}), citation errors {c['citation_error']}, authorization {c['authorization_failure']}; questions fully correct {c.get('questions_fully_correct', 0)}/{c['questions']}; "
              f"questions with an untyped clause {c.get('questions_with_untyped_clause', 0)}")
    # renamed world
    tmp = Path(ORIG_ARGV[1]) if len(ORIG_ARGV) > 1 else Path("/tmp")
    renamed_path, mapping = renamed_world(tmp)
    wr = World(renamed_path)
    rn_cases = json.loads(re.sub(r"(?<![\w-])(" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")(?![\w-])", lambda mo: mapping[mo.group(0)], json.dumps(cases)))
    res_r, replies_r, problems_r = score_arm(wr, rn_cases, make_planners(wr, rn_cases)["T-grammar"], canon=True)
    report["arms"]["T-renamed"] = res_r
    problems_all["T-renamed"] = {k: v for k, v in problems_r.items()}
    (OUT / "i2b-dev15-replies-T-renamed.jsonl").write_text("\n".join(json.dumps(r) for r in replies_r))
    # name-for-name comparison of the two worlds' replies after mapping the original replies through the same renaming
    mapped = {r["id"]: re.sub(r"(?<![\w-])(" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")(?![\w-])", lambda mo: mapping[mo.group(0)], r["answer"]) for r in replies_all["T-grammar"]}
    same = sum(mapped[r["id"]] == r["answer"] for r in replies_r)
    states_same = sum(next(x for x in replies_all["T-grammar"] if x["id"] == r["id"])["states"] == r["states"] for r in replies_r)
    report["renamed_world"] = {"names_replaced": len(mapping), "questions": len(replies_r), "replies_identical_after_mapping": same, "states_identical": states_same}
    c = res_r["counts"]
    print(f"T-renamed   atoms {c['atoms']}: exact {c.get('exact', 0)}, not typed {c.get('not_typed', 0)}, false abstention {c.get('false_abstention', 0)}, unsupported {c['unsupported_claim']}; replies identical to T-grammar after mapping {same}/{len(replies_r)}, states identical {states_same}/{len(replies_r)}")
    report["problems"] = problems_all
    (OUT / "i2b-dev15-report.json").write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
