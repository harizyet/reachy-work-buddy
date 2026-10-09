"""I-2: offline evaluation of the deterministic typed-template path (Stage B-1 pipeline + composer) against dev15. NO MODEL. Development data only: dev16 is not used and not touched.

What is measured and how (owner direction 2026-10-10):
  MECHANICAL (decided by code against gold or against the turn's own manifest): exact state vs the registry gold, value correctness against the gold display, template purity of every withheld/conflict/
  negative/ordering sentence, citation integrity (evidence id exists, record authorised, the cited record's own text contains the value or the scope), authorisation (no admitted or cited record is
  unauthorised; no value that exists only in unauthorised records appears in any reply), false abstention, unsupported claims, partial answers.
  NOT ESTABLISHED BY ANY OF THIS (needs a human reader; a closed-vocabulary pass is not semantic correctness): whether a reply reads clearly, whether the stated uncertainty is the right amount for a lay
  owner, whether a composed multi-part reply is understandable, whether a value that equals the gold display was read from a sentence that actually answers the question (rather than a coincidence of
  wording), and whether a quoted scope is faithful. The report lists these separately and samples replies for a single-reader pass (labelled NO INDEPENDENT HUMAN REVIEW).
Circularity (disclosed): the relation specs, subject patterns and component asks come from the gold atoms (cue_re, subject_re, status), written by the same author as the pipeline. The decomposition run
(question text -> components) is reported separately and uses only the record-side cues, so it is a floor, not a tuned result. Authorisation follows the owner_private profile (sensitive not authorised).

    python i2_eval.py            -> results/i2-dev15-report.json, results/i2-dev15-replies.jsonl, results/i2-existence-sweep.json
"""
from __future__ import annotations

import collections
import json
import re
import statistics
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.argv = [sys.argv[0], "--harness-fixes", "--structured", "--context", "--text"]  # the final B-1 configuration, as in the extension record
sys.path.insert(0, str(HERE))
import b1_dev15_check as h
from companion_core.knowledge.answerability_b1 import (
    Ask,
    AuthDecision,
    Component,
    RelationSpec,
    Scope,
    admit,
    build_plan,
    decompose,
)

OUT = HERE.parent / "results"
NOW = h.NOW
ANSWERED = {"SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED"}
WITHHELD_GOLD = {"UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED"}
CAVEAT = r"(?: Another record on this could not be read reliably, so it is not used\.)?"


def _purity_regexes(label: str) -> dict[str, re.Pattern]:
    L = re.escape(label)
    cite = r"(?: ?\[[A-Z]\d+\])+"
    return {
        "UNSUPPORTED": re.compile(rf"^(?:The records do not say the {L}\.{CAVEAT}|The records on the {L} are unclear, so I will not pick an answer\.|I could not check the {L}\.)$"),
        "NEGATIVE_UNSUPPORTED": re.compile(rf"^(?:The records I searched do not mention an? {L}\.{CAVEAT}|The records on the {L} are unclear, so I will not pick an answer\.|I could not check the {L}\.|"
                                           rf"(?:A search of .+? found no {L}{cite}(?:; not searched: .+?|; the record does not say where else was checked)\. ?)+That does not show there is none\.{CAVEAT}|"
                                           rf"A record by .+? says there is no {L}{cite}, but that is not an authoritative source, so the records do not establish it\.(?: A search of .+)?)$"),
        "ORDER_UNSUPPORTED": re.compile(rf"^(?:Nothing in the records establishes an order for the {L}\.{CAVEAT}|The records give .+? for the {L}, but nothing in them dates one before the other\.{CAVEAT}|"
                                        rf"The records on the {L} are unclear, so I will not pick an answer\.|I could not check the {L}\.)$"),
        "CONFLICTED": re.compile(rf"^The records disagree on (?:whether there is an? {L}|the {L}): .+? They do not say which applies\.{CAVEAT}$"),
    }


LABELS = {  # reply wording per relation (presentation only; the registry would own this later)
    "owner": "owner of the {s}", "reviews": "review assigned to {s}", "decision": "planning decision for {s}", "runs_on": "host running {s}", "attends": "attendees of the {s} planning meeting",
    "support_hours": "weekday support hours of {s}", "budget_through": "last funded month for {s}", "lead": "lead of {s}", "deadline": "deadline for {s}'s written summary", "default_model": "default model of {s}",
    "rollback_window": "rollback window for {s}", "security_reviewer": "security reviewer for {s}", "max_message_size": "maximum message size of the {s}", "vacation": "next days off for the {s} lead",
    "test_fixer": "person fixing the {s} rollback test", "incident_auditor": "person who audits the {s} build logs", "on_call": "person on call for {s}", "retry_limit": "retry limit of the {s}",
    "staging_env": "staging environment for {s}", "default_model_history": "default model of {s}", "retry_limit_history": "retry limit of the {s}", "standup": "standup time for {s}",
    "review_day": "design review day for {s}", "order_figure": "{s} records"}
UNITS = {"rollback_window": "minutes", "retry_limit": "retries", "retry_limit_history": "retries"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^(?:the|a|an)\s+", "", s.strip().casefold()))


def build_world():
    items = h.pool()
    c4 = json.loads(h.CORPUS.read_text())
    level = {}
    texts = {}
    for key, store in (("memories", "memory"), ("notes", "note"), ("documents", "document"), ("meetings", "meeting")):
        for r in c4[key]:
            level[f"{store}:{r['id']}"] = r.get("sensitivity", "public")
    auths = {i.ref: AuthDecision(level.get(i.ref.split("#")[0], "public") != "sensitive", NOW - timedelta(seconds=3), "p1", 1) for i in items}
    eids = {i.ref: f"E{n}" for n, i in enumerate(items, 1)}
    structured = h.structured_records(c4)
    for rec in structured:
        auths[rec.ref] = AuthDecision(level.get(rec.ref.split("#")[0], "public") != "sensitive", NOW - timedelta(seconds=3), "p1", 1)
        if rec.ref not in eids:  # one evidence id per distinct record (the earlier harness overwrote ids, giving every meeting segment the same one; this evaluation's citation check caught it)
            eids[rec.ref] = f"E{len(eids) + 1}"
    for i in items:
        texts[i.ref] = i.text
    for rec in structured:
        texts[rec.ref] = " ".join(rec.attendees) if hasattr(rec, "attendees") else f"{texts.get(rec.ref, '')} {rec.text} {rec.speaker or ''}"  # the resolved speaker is authoritative metadata of the cited segment
    return c4, items, auths, eids, structured, texts, level


def spec_for(a, kind=None):
    kind = h.KINDS.get(a["kind"], "person")
    text_pattern = None
    if a["relation"] in h.TEXT_PATTERNS:
        kind, text_pattern = "text", h.TEXT_PATTERNS[a["relation"]]
    structured = "attendees" if a["relation"] == "attends" else "speaker" if kind == "person" else None
    return RelationSpec(a["relation"], kind, (a["cue_re"],), unit=UNITS.get(a["relation"], ""), prefix="the " if a["relation"] == "runs_on" else "", many=a["relation"] == "attends", co_subjects_ok=a["relation"] in ("runs_on", "default_model"), negation=r"\b(?:has no|does not have|there is no|no)\b",
                        presence=r"\b(?:has a|has an|there is a)\b", text_pattern=text_pattern, structured=structured, object_words=tuple(re.findall(r"[A-Za-z0-9]+", a["cue_re"])))


def main():
    _, items, auths, eids, structured, texts, _ = build_world()
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    from validate_scorer import PEOPLE

    people = {p.lower() for p in PEOPLE} | {p.split()[0].lower() for p in PEOPLE}
    known = sorted({re.sub(r"\\b", "", a["subject_re"]) for q in cases for a in q["atoms"] if a["subject_re"]} - people - {p.replace(" ", "\\ ") for p in people})
    known_raw = [k for k in known if k.replace("\\", "") not in people]  # as the earlier harness built it (backslashes kept: an escaped hyphen never matched)
    known = [k.replace("\\", "") for k in known_raw]
    ref_of = {v: k for k, v in eids.items()}
    unauth = {r for r, d in auths.items() if not d.authorized}
    sensitive_text = " ".join(texts[r] for r in unauth if r in texts)
    authorised_text = " ".join(t for r, t in texts.items() if r not in unauth).casefold()
    sens_only = sorted({m for m in re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", sensitive_text) if m.casefold() not in authorised_text})

    m = collections.Counter()
    exact_by_gold = collections.defaultdict(collections.Counter)
    problems: dict[str, list] = collections.defaultdict(list)
    replies = []
    word_counts, cite_counts = [], []
    partial = collections.Counter()
    sens_leaks = []
    for q in cases:
        comps, specs = [], {}
        for n, a in enumerate(q["atoms"], 1):
            subject = re.sub(r"\\b", "", a["subject_re"]).replace("\\", "")
            specs.setdefault(a["relation"], spec_for(a))
            ask = Ask.EXISTENCE if a["kind"] == "bool" else Ask.ORDERING if a["status"] == "ORDER_UNSUPPORTED" else Ask.VALUE
            comps.append(Component(f"c{n}", a["subject"], (subject,), a["relation"], ask, Scope.PAST if a["status"] == "HISTORICAL" else Scope.ANY, LABELS[a["relation"]].format(s=a["subject"])))
        plan = build_plan(comps, items, auths, now=NOW, specs=specs, eids=eids, known_subjects=known, policy=h.POLICY, structured=structured)
        qgood = True
        sup_atoms_ok, withheld_ok = [], []
        for a, comp, ticket, claim in zip(q["atoms"], comps, plan.tickets, plan.claims, strict=True):
            gold, got = a["status"], claim.state.value
            m["atoms"] += 1
            exact_by_gold[gold][got] += 1
            ok = gold == got
            m["exact"] += ok
            qgood &= ok
            display = {norm(d) for d in a["display"]}
            # --- unsupported-claim errors (mechanical)
            if gold in WITHHELD_GOLD and got in ANSWERED | {"CONFLICTED"}:
                m["unsupported_claim"] += 1
                problems["unsupported_claim"].append((q["id"], a["id"], gold, got, claim.text))
            if gold == "CONFLICTED" and got in ANSWERED:
                m["conflict_resolved"] += 1
                problems["conflict_resolved"].append((q["id"], a["id"], claim.text))
            if gold == "HISTORICAL" and got == "SUPPORTED":
                m["history_as_current"] += 1
            if got in ("SUPPORTED", "HISTORICAL") and comp.ask is Ask.VALUE:
                shown = {norm(v) for v, _ in ticket.values}
                good = shown == display if specs[a["relation"]].many else shown <= display
                m["answered_values"] += 1
                if not good:
                    m["wrong_value"] += 1
                    problems["wrong_value"].append((q["id"], a["id"], ticket.values, a["display"]))
            # --- false abstention
            if gold in ("SUPPORTED", "HISTORICAL") and got in WITHHELD_GOLD | {"UNSUPPORTED"}:
                m["false_abstention"] += 1
                adm = admit(comp, items, auths, now=NOW, spec=specs[a["relation"]], known_subjects=known, policy=h.POLICY, structured=structured)
                why = sorted({reason for _, reason in adm.ambiguous}) or ["no_sentence_read_for_this_subject_and_relation"]
                for w in why:
                    m[f"false_abstention_cause:{w}"] += 1
                problems["false_abstention"].append((q["id"], a["id"], a["relation"], gold, got, why))
            if gold in ("SUPPORTED", "HISTORICAL"):
                m["gold_answerable"] += 1
                sup_atoms_ok.append(got == gold)
            else:
                withheld_ok.append(ok)
            # --- template purity (code-written sentences contain only fixed words, the label and cited ids)
            if got in ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED", "CONFLICTED"):
                pat = _purity_regexes(claim.label).get(got)
                m["purity_checked"] += 1
                if pat is None or not pat.match(claim.text):
                    m["purity_fail"] += 1
                    problems["purity"].append((q["id"], a["id"], got, claim.text))
                if got in ("UNSUPPORTED",) and claim.assertable:
                    m["purity_fail"] += 1
                    problems["purity"].append((q["id"], a["id"], got, "assertable on a withheld claim"))
            # --- citation integrity (evidence ids, authorisation, record text contains the cited value/scope)
            for value, ids in claim.assertable:
                m["cited_values"] += 1
                if not ids:
                    m["citation_missing"] += 1
                    problems["citation"].append((q["id"], a["id"], "no evidence id", value))
                for e in ids:
                    ref = ref_of.get(e)
                    if ref is None:
                        m["citation_error"] += 1
                        problems["citation"].append((q["id"], a["id"], "unknown evidence id", e))
                        continue
                    if ref in unauth:
                        m["authorization_failure"] += 1
                        problems["authorization"].append((q["id"], a["id"], "cited unauthorised record", ref))
                    if value in ("present", "absent", "absent (attributed)"):
                        continue
                    hay = norm(texts.get(ref, ""))
                    if norm(value) not in hay and not (a["kind"] == "person" and set(norm(value).split()) <= set(hay.split())):
                        m["citation_error"] += 1
                        problems["citation"].append((q["id"], a["id"], "cited record does not contain the value", value, ref))
                    gold_src = set(a.get("sources", []))
                    if gold_src and ref.split("#")[0] not in gold_src:
                        m["cites_non_gold_record"] += 1  # informational: the record contains the value but is not the registered source
                if not all(f"[{e}]" in claim.text for e in ids):
                    m["citation_not_in_text"] += 1
            for r_ in (r for _, refs in ticket.values for r in refs):
                if r_ in unauth:
                    m["authorization_failure"] += 1
                    problems["authorization"].append((q["id"], a["id"], "admitted from unauthorised record", r_))
            if claim.state.value in ANSWERED and not claim.assertable:
                m["answered_without_citation"] += 1
        answer = plan.answer
        for name in sens_only:
            if name.casefold() in answer.casefold():
                m["sensitive_value_in_reply"] += 1
                sens_leaks.append((q["id"], name))
        if len(q["atoms"]) >= 2 and any(sup_atoms_ok) and withheld_ok:
            partial["mixed_questions"] += 1
            partial["supported_part_answered"] += all(sup_atoms_ok)
            partial["withheld_parts_correct"] += all(withheld_ok)
            partial["both"] += all(sup_atoms_ok) and all(withheld_ok)
        m["questions"] += 1
        m["questions_all_exact"] += qgood
        word_counts.append(len(answer.split()))
        cite_counts.append(len(re.findall(r"\[E\d+\]", answer)))
        replies.append({"id": q["id"], "family": q["family"], "question": q["question"], "gold": [(a["relation"], a["subject"], a["status"], a["display"]) for a in q["atoms"]],
                        "states": [c.state.value for c in plan.claims], "answer": answer})

    # authorisation diagnostic: with sensitive records wrongly authorised, would the pipeline have answered from them? (shows the check bites)
    open_auths = {r: AuthDecision(True, d.checked_at, d.policy_version, d.acl_revision) for r, d in auths.items()}
    bites = 0
    for q in cases:
        for a in q["atoms"]:
            if a["status"] == "UNSUPPORTED" and a["relation"] == "incident_auditor":
                subject = re.sub(r"\\b", "", a["subject_re"]).replace("\\", "")
                comp = Component("c1", a["subject"], (subject,), a["relation"], Ask.VALUE, Scope.ANY)
                p2 = build_plan([comp], items, open_auths, now=NOW, specs={a["relation"]: spec_for(a)}, eids=eids, known_subjects=[k for k in known if k != subject], policy=h.POLICY, structured=structured)
                bites += p2.claims[0].state.value in ANSWERED

    # --- DIAGNOSTIC ONLY (not the evaluated path): the false abstentions trace to model names being in the known-subject list. A model name is a SUBJECT for "where does Swift-6B run" and a VALUE for "default model" /
    # "decision"; a sentence that names it is then treated as naming a competing subject (title/context binding is refused, or the value is skipped). Quantify the caller-side fix (known subjects without model names for
    # every relation except runs_on, plus co_subjects_ok on the two model-valued relations that lacked it), WITHOUT changing the source.
    def diagnostic():
        known_nm = [k for k in known if not re.fullmatch(r"[a-z]+-\d+b", k)]
        conf, unsupported, wrong = collections.Counter(), 0, 0
        for q in cases:
            for a in q["atoms"]:
                subject = re.sub(r"\\b", "", a["subject_re"]).replace("\\", "")
                sp = spec_for(a)
                if a["relation"] in ("default_model_history", "decision"):
                    sp = RelationSpec(**{**sp.__dict__, "co_subjects_ok": True})
                ask = Ask.EXISTENCE if a["kind"] == "bool" else Ask.ORDERING if a["status"] == "ORDER_UNSUPPORTED" else Ask.VALUE
                comp = Component("c1", a["subject"], (subject,), a["relation"], ask, Scope.PAST if a["status"] == "HISTORICAL" else Scope.ANY)
                pl = build_plan([comp], items, auths, now=NOW, specs={a["relation"]: sp}, eids=eids, known_subjects=known if a["relation"] == "runs_on" else known_nm, policy=h.POLICY, structured=structured)
                got = pl.claims[0].state.value
                conf[(a["status"], got)] += 1
                unsupported += a["status"] in WITHHELD_GOLD and got in ANSWERED | {"CONFLICTED"}
                if got in ("SUPPORTED", "HISTORICAL") and ask is Ask.VALUE:
                    shown = {norm(v) for v, _ in pl.tickets[0].values}
                    wrong += not (shown == {norm(d) for d in a["display"]} if sp.many else shown <= {norm(d) for d in a["display"]})
        return {"exact": sum(v for (g, x), v in conf.items() if g == x), "atoms": sum(conf.values()), "false_abstention": sum(v for (g, x), v in conf.items() if g in ("SUPPORTED", "HISTORICAL") and x not in ANSWERED),
                "unsupported_claims": unsupported, "wrong_values": wrong}

    diagnostic_variant = diagnostic()

    # --- comparability with the earlier extension record (282/307): same isolated-atom harness, escaped known list, VALUE ask for non-negative atoms; then the same with a faithful (unescaped) known list
    replica = {}
    for mode, klist in (("earlier_harness_escaped_known", known_raw), ("isolated_atoms_faithful_known", known)):
        conf = collections.Counter()
        for q in cases:
            for a in q["atoms"]:
                subject = re.sub(r"\\b", "", a["subject_re"]).replace("\\", "")
                ask = Ask.EXISTENCE if a["status"].startswith("NEGATIVE") else Ask.ORDERING if a["status"] == "ORDER_UNSUPPORTED" else Ask.VALUE
                comp = Component("c1", a["subject"], (subject,), a["relation"], ask, Scope.PAST if a["status"] == "HISTORICAL" else Scope.ANY)
                p3 = build_plan([comp], items, auths, now=NOW, specs={a["relation"]: spec_for(a)}, eids=eids, known_subjects=[k for k in klist if k != subject and k.replace("\\", "") != subject], policy=h.POLICY, structured=structured)
                conf[(a["status"], p3.claims[0].state.value)] += 1
        replica[mode] = {"exact": sum(v for (g, x), v in conf.items() if g == x), "atoms": sum(conf.values()), "withheld_supported_or_historical": sum(v for (g, x), v in conf.items() if g in ("SUPPORTED", "HISTORICAL") and x in ("UNSUPPORTED",))}

    # --- authorisation revocation test: for every answered claim, revoke (or stale) exactly the records it cites and rebuild. The claim must disappear or be re-supported by OTHER authorised records; it must never still cite
    # a revoked record, and a withheld result must be the plain template with no value (this is the real authorisation control: dev15's four sensitive documents are not readable by the pipeline either way)
    revoke = collections.Counter()
    for q in cases:
        for a in q["atoms"]:
            subject = re.sub(r"\\b", "", a["subject_re"]).replace("\\", "")
            ask = Ask.EXISTENCE if a["kind"] == "bool" else Ask.ORDERING if a["status"] == "ORDER_UNSUPPORTED" else Ask.VALUE
            comp = Component("c1", a["subject"], (subject,), a["relation"], ask, Scope.PAST if a["status"] == "HISTORICAL" else Scope.ANY, LABELS[a["relation"]].format(s=a["subject"]))
            base = build_plan([comp], items, auths, now=NOW, specs={a["relation"]: spec_for(a)}, eids=eids, known_subjects=known, policy=h.POLICY, structured=structured)
            if base.claims[0].state.value not in ANSWERED or not base.tickets[0].values:
                continue
            cited = {r for _, refs in base.tickets[0].values for r in refs}
            for mode in ("revoked", "stale"):
                bad = {r: (AuthDecision(False, d.checked_at, d.policy_version, d.acl_revision) if mode == "revoked" else AuthDecision(True, NOW - timedelta(hours=2), d.policy_version, d.acl_revision)) if r in cited else d for r, d in auths.items()}
                p2 = build_plan([comp], items, bad, now=NOW, specs={a["relation"]: spec_for(a)}, eids=eids, known_subjects=known, policy=h.POLICY, structured=structured)
                c2, t2 = p2.claims[0], p2.tickets[0]
                revoke[f"{mode}_tested"] += 1
                still = {r for _, refs in t2.values for r in refs} & cited
                if still:
                    revoke[f"{mode}_STILL_CITES_REVOKED"] += 1
                elif c2.state.value in ANSWERED:
                    revoke[f"{mode}_resupported_by_other_authorised_record"] += 1
                else:
                    pat = _purity_regexes(c2.label).get(c2.state.value)
                    revoke[f"{mode}_withheld"] += 1
                    if (pat is not None and not pat.match(c2.text)) or c2.assertable:
                        revoke[f"{mode}_withheld_text_impure"] += 1

    # --- decomposition from question text (record-side cues only; a floor, not tuned)
    allspecs, subjects = {}, {}
    for q in cases:
        for a in q["atoms"]:
            allspecs.setdefault(a["relation"], spec_for(a))
            subjects.setdefault(a["subject"], (re.sub(r"\\b", "", a["subject_re"]).replace("\\", ""),))
    dec = collections.Counter()
    for q in cases:
        comps, fallback = decompose(q["question"], allspecs, subjects)
        want = collections.Counter((a["subject"], a["relation"]) for a in q["atoms"])
        got = collections.Counter((c.subject, c.relation) for c in comps)
        dec["questions"] += 1
        dec["fallback"] += fallback
        dec["exact_decomposition"] += (want == got) and not fallback
        dec["atoms_recovered"] += sum((want & got).values())
        dec["atoms"] += sum(want.values())

    words = sorted(word_counts)
    report = {
        "scope": "dev15 only, no model, specs/asks from gold atoms (circular, disclosed); dev16 untouched",
        "counts": {**{k: 0 for k in ("unsupported_claim", "conflict_resolved", "wrong_value", "history_as_current", "purity_fail", "citation_error", "citation_missing", "citation_not_in_text", "authorization_failure", "answered_without_citation", "sensitive_value_in_reply")}, **dict(m)},
        "exact_answerability_by_gold": {g: dict(c) for g, c in exact_by_gold.items()},
        "partial_answers": dict(partial),
        "reply_length_words": {"median": statistics.median(words), "p90": words[int(0.9 * len(words))], "max": words[-1]},
        "citations_per_reply_median": statistics.median(cite_counts),
        "sensitive_only_values_scanned": len(sens_only),
        "authorisation_note": "the four sensitive dev15 documents are not readable by the pipeline even if authorised (qualified-object rule), so the scan of sensitive-only values is vacuous; the revocation test below is the real control",
        "authorisation_revocation_test": dict(revoke),
        "decomposition_from_question_text": dict(dec),
        "comparability_with_extension_record": replica,
        "DIAGNOSTIC_model_names_as_values_variant_not_evaluated_path": diagnostic_variant,
        "problems": {k: v for k, v in problems.items()},
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "i2-dev15-report.json").write_text(json.dumps(report, indent=1, default=str))
    (OUT / "i2-dev15-replies.jsonl").write_text("\n".join(json.dumps(r) for r in replies))
    print(json.dumps({k: v for k, v in report.items() if k != "problems"}, indent=1, default=str))
    print({k: len(v) for k, v in problems.items()})


if __name__ == "__main__":
    main()
