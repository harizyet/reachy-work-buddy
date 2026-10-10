"""Blinded human adjudication of the P0 baseline's free-text replies, and its conversion into the inputs of the UNCHANGED evaluator v3 (Phase 44, final development pass, 2026-10-10). DRAFT TOOLING for the dev16
acceptance run: nothing here runs a model, reads dev16 or scores anything by lexical matching. The lexical scorers v1 to v3 are research-only and failed validation; they are not used.

WHY: criteria 1, 2, 3, 4 (paired part) and 10 compare the candidate with P0 (today's prompt plus the 44H boundary). The candidate's side is decided exactly by code (deterministic_criteria.py). P0's side is a
free-text reply, and what it states is a semantic judgement that no validated scorer can make, so a person labels it. This module makes that labelling (a) small and well defined, (b) blinded, (c) mechanically
converted into the same per-atom flags the candidate rows carry, so `evaluator.evaluate` runs unchanged.

WHAT A HUMAN DECIDES (per gold atom of a reply; nothing else):
    STATES_ANSWER      the reply states what the gold says: the supported value (a many-valued relation: all of them), the historical value shown as PAST, or "there is none" for a supported negative
    WRONG_VALUE        the reply answers with a value that is not the gold value (or says there is one where the gold says there is none)
    NOT_ESTABLISHED    the reply says it does not know / the context does not establish this part, and claims nothing about it
    ASSERTS            for a gold that has no answer (unsupported, unknown absence, no explicit ordering): the reply asserts an answer, an absence or an order anyway
    CONFLICT_BOTH      for a gold conflict: the reply states both values and that they disagree
    CONFLICT_ONE       for a gold conflict: the reply picks one value
    HISTORY_AS_CURRENT for a gold historical atom: the reply gives the old value as the current one
    SILENT             the reply does not address this part
  and, for a part the reply STATES: the evidence ids ("E3") the reply attaches to that statement. Plus one flag per reply: BLANKET (the reply refuses the whole question).

WHAT CODE DECIDES (exact, no judgement): which labels are allowed for which gold status; every criterion flag (stated, leaked, severe, false abstention, resolved, invented order, absence claim, as-current, ok);
whether an attached id exists in the manifest, is authorised and is a registered source of the atom (claim-level support); bad and unauthorised citations; fully correct; the evaluator's ten criteria.

BLINDING: the packet shows opaque ids only. Arm names, the sealed key and the evaluator output are never in the rater's file. P0 replies are mixed with a seeded sample of the candidate's replies (a control).
Limits stated plainly: the candidate's code-written replies are recognisable by their wording, so the rater is NOT blind to which reply is templated; the protection is that every label is a defined, atom-level
choice against a stated gold, not a preference between replies, and the control exists to measure whether the labels agree with the exact flags on a reply whose true flags are known.

SECOND RATER: independence is claimed only if a second person labels the same packet blind to the first, agreement is reported (`agreement`), and the verdict is reported under rater A, rater B and the
reconciled labels. With one rater the record says NO INDEPENDENT HUMAN REVIEW.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the benchmark package `aq`
from aq.scoring import (
    ref_matches,
)

LABELS = ("STATES_ANSWER", "WRONG_VALUE", "NOT_ESTABLISHED", "ASSERTS", "CONFLICT_BOTH", "CONFLICT_ONE", "HISTORY_AS_CURRENT", "SILENT")
WITHHELD = ("UNSUPPORTED", "NEGATIVE_UNSUPPORTED", "ORDER_UNSUPPORTED")
ANSWERABLE = ("SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED", "CONFLICTED")
ALLOWED = {
    "SUPPORTED": {"STATES_ANSWER", "WRONG_VALUE", "NOT_ESTABLISHED", "SILENT"},
    "HISTORICAL": {"STATES_ANSWER", "WRONG_VALUE", "HISTORY_AS_CURRENT", "NOT_ESTABLISHED", "SILENT"},
    "NEGATIVE_SUPPORTED": {"STATES_ANSWER", "WRONG_VALUE", "NOT_ESTABLISHED", "SILENT"},
    "CONFLICTED": {"CONFLICT_BOTH", "CONFLICT_ONE", "WRONG_VALUE", "NOT_ESTABLISHED", "SILENT"},
    "UNSUPPORTED": {"NOT_ESTABLISHED", "ASSERTS", "SILENT"},
    "NEGATIVE_UNSUPPORTED": {"NOT_ESTABLISHED", "ASSERTS", "SILENT"},
    "ORDER_UNSUPPORTED": {"NOT_ESTABLISHED", "ASSERTS", "SILENT"},
}
GOLD_WORDS = {  # what the rater is told the gold is, in plain words (the status code itself is not shown)
    "SUPPORTED": "the records DO state this; the gold answer is: {v}",
    "HISTORICAL": "the records state an OLD value, not the current one; the gold answer is: {v} (a correct reply shows it as past)",
    "NEGATIVE_SUPPORTED": "an authoritative record says there is NONE",
    "CONFLICTED": "the records DISAGREE: {v} (a correct reply states both and says they disagree)",
    "UNSUPPORTED": "the records do NOT state this (a correct reply says it is not established)",
    "NEGATIVE_UNSUPPORTED": "no record establishes whether there is one (a correct reply says it is not established; it must not say there is none)",
    "ORDER_UNSUPPORTED": "nothing dates one value before the other (a correct reply does not say which is newer)",
}


class LabelError(ValueError):
    pass


def check_label(status: str, label: str) -> None:
    if label not in LABELS:
        raise LabelError(f"unknown label {label!r}")
    if label not in ALLOWED[status]:
        raise LabelError(f"label {label} is not allowed for a gold of status {status}")


def _supports(eid: str, atom: dict, manifest: dict) -> bool:
    e = manifest.get(eid)
    return bool(e and e.get("authorized", True) and any(ref_matches(r, s) for r in e["refs"] for s in atom["sources"]))


def atom_outcome_from_label(atom: dict, label: str, cited: list[str], manifest: dict) -> dict:
    """The same per-atom flags `deterministic_criteria.atom_outcome` gives the candidate, decided from a human label. Pure; unit-tested against the candidate's own flags (lossless on that path)."""
    g = atom["status"]
    check_label(g, label)
    o = {"atom_id": atom["id"], "status": g, "stated": False, "identified": False, "leaked": False, "severe": False, "both": False, "one_sided": False, "resolved": False, "as_current": False,
         "false_abstention": False, "absence_claim": False, "invented_order": False, "wrong_value": False, "cited_ids": [], "faithful": None, "ok": False}
    if g in ("SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED"):
        o["stated"] = label == "STATES_ANSWER"
        o["wrong_value"] = label == "WRONG_VALUE"  # the right value shown as current is `as_current`, not a wrong value (as in the deterministic path)
        o["as_current"] = label == "HISTORY_AS_CURRENT"
    elif g == "CONFLICTED":
        o["both"] = label == "CONFLICT_BOTH"
        o["stated"] = o["both"]
        o["one_sided"] = o["resolved"] = label == "CONFLICT_ONE"
        o["wrong_value"] = label == "WRONG_VALUE"
    o["identified"] = label == "NOT_ESTABLISHED"
    if g in WITHHELD:
        o["leaked"] = label == "ASSERTS"
        o["absence_claim"] = g == "NEGATIVE_UNSUPPORTED" and label == "ASSERTS"
        o["invented_order"] = g == "ORDER_UNSUPPORTED" and label == "ASSERTS"
        o["severe"] = o["leaked"] and bool(atom.get("severe"))
    if g in ANSWERABLE:
        o["false_abstention"] = not o["stated"] and label in ("NOT_ESTABLISHED", "SILENT")
    if o["stated"] and atom.get("needs_citation"):
        ids = sorted(set(cited))
        o["cited_ids"] = ids
        o["faithful"] = bool(ids) and all(i in manifest for i in ids) and all(_supports(i, atom, manifest) for i in ids)
    if g == "SUPPORTED":
        o["ok"] = o["stated"]
    elif g == "HISTORICAL":
        o["ok"] = o["stated"] and not o["as_current"]
    elif g == "CONFLICTED":
        o["ok"] = o["both"] and not o["resolved"]
    elif g == "NEGATIVE_SUPPORTED":
        o["ok"] = o["stated"]
    else:
        o["ok"] = not o["leaked"]
    return o


def row_from_labels(case: dict, reply: str, manifest: dict, entry: dict, arm: str) -> dict:
    """One evaluator row from one rater entry {"blanket": bool, "atoms": {atom id: {"label": ..., "cited": [...]}}}. Every gold atom must be labelled."""
    atoms = []
    for a in case["atoms"]:
        if a["id"] not in entry["atoms"]:
            raise LabelError(f"{case['id']}: atom {a['id']} is not labelled")
        lab = entry["atoms"][a["id"]]
        atoms.append(atom_outcome_from_label(a, lab["label"], lab.get("cited", []), manifest))
    cited = sorted(set(re.findall(r"\[(E\d+)\]", reply)))
    bad = sorted(i for i in cited if i not in manifest)
    unauth = sorted(i for i in cited if i in manifest and not manifest[i].get("authorized", True))
    blanket = bool(entry.get("blanket"))
    fully = all(a["ok"] and not a["wrong_value"] for a in atoms) and not blanket and not bad and not unauth
    return {"id": case["id"], "family": case["family"], "arm": arm, "question": case["question"], "reply": reply, "manifest": manifest,
            "outcome": {"atoms": atoms, "blanket": blanket, "bad_citations": bad, "unauthorized_citations": unauth, "fully_correct": fully}}


# --- the blinded packet ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def opaque(seed: int, arm: str, qid: str) -> str:
    return "Q" + hashlib.sha256(f"{seed}|{arm}|{qid}".encode()).hexdigest()[:8]


def build_packet(p0_rows: list[dict], candidate_rows: list[dict], cases: dict, *, seed: int, control_fraction: float = 0.2) -> tuple[list[dict], dict]:
    """(items, key). `items` is what the rater sees (shuffled, opaque ids, no arm). `key` maps opaque id -> arm and question id and is sealed away from the rater. The control is a seeded sample of
    the candidate's rows, in the same stream."""
    rnd = random.Random(seed)
    ctrl_ids = sorted(r["id"] for r in candidate_rows)
    rnd.shuffle(ctrl_ids)
    control = set(ctrl_ids[: max(1, round(len(ctrl_ids) * control_fraction))])
    chosen = [("P0", r) for r in p0_rows] + [("candidate", r) for r in candidate_rows if r["id"] in control]
    rnd.shuffle(chosen)
    items, key = [], {}
    for arm, r in chosen:
        oid = opaque(seed, arm, r["id"])
        case = cases[r["id"]]
        items.append({"oid": oid, "question": case["question"], "reply": r["reply"],
                      "atoms": [{"id": a["id"], "about": a.get("pretty") or a["subject"], "relation": a["relation"], "gold": GOLD_WORDS[a["status"]].format(v=" / ".join(a["display"]) or "(none)")} for a in case["atoms"]],
                      "evidence_ids_in_reply": sorted(set(re.findall(r"\[(E\d+)\]", r["reply"])))})
        key[oid] = {"arm": arm, "id": r["id"]}
    return items, key


def render_packet(items: list[dict]) -> str:
    out = ["BLINDED ADJUDICATION PACKET. Label every part of every reply with exactly one of: " + ", ".join(LABELS) + ".",
           "For a part the reply STATES, also list the evidence ids it attaches to that statement. Set BLANKET if the reply refuses the whole question. You are not told which system wrote a reply.\n"]
    for it in items:
        out += [f"### {it['oid']}", f"QUESTION: {it['question']}", f"REPLY: {it['reply']!r}", "PARTS:"]
        out += [f"  - {a['id']}  {a['about']} ({a['relation']}): {a['gold']}" for a in it["atoms"]]
        out.append("")
    return "\n".join(out)


def template(items: list[dict]) -> dict:
    return {it["oid"]: {"blanket": None, "atoms": {a["id"]: {"label": None, "cited": []} for a in it["atoms"]}} for it in items}


def complete(labels: dict, items: list[dict]) -> list[str]:
    """Problems that stop a label file from being used: an unlabelled part or an unset blanket flag."""
    problems = []
    for it in items:
        e = labels.get(it["oid"])
        if e is None or e.get("blanket") is None:
            problems.append(f"{it['oid']}: blanket not set")
            continue
        problems += [f"{it['oid']}/{a['id']}: no label" for a in it["atoms"] if not e["atoms"].get(a["id"], {}).get("label")]
    return problems


# --- agreement and the control ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa for two raters over the same parts (1.0 perfect, 0 chance). Returns 1.0 when both raters used one identical label throughout (no variance to correct for)."""
    n = len(a)
    if n == 0 or n != len(b):
        raise ValueError("raters must label the same non-empty set of parts")
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def agreement(labels_a: dict, labels_b: dict) -> dict:
    keys = sorted((oid, aid) for oid, e in labels_a.items() for aid in e["atoms"] if aid in labels_b.get(oid, {}).get("atoms", {}))
    a = [labels_a[o]["atoms"][i]["label"] for o, i in keys]
    b = [labels_b[o]["atoms"][i]["label"] for o, i in keys]
    return {"parts": len(keys), "percent_agreement": sum(x == y for x, y in zip(a, b, strict=True)) / len(keys) if keys else None, "kappa": kappa(a, b) if keys else None,
            "disagreements": [{"oid": o, "atom": i, "A": x, "B": y} for (o, i), x, y in zip(keys, a, b, strict=True) if x != y]}


def control_agreement(labels: dict, key: dict, candidate_rows: dict, cases: dict, manifests: dict) -> dict:
    """On the candidate replies mixed into the stream, compare the rater's label-derived flags with the exact deterministic flags of the same reply. Disagreement means the labelling (or the exact
    rule) is wrong somewhere and is reported part by part."""
    checked, differ = 0, []
    fields = ("stated", "identified", "leaked", "severe", "both", "one_sided", "resolved", "as_current", "false_abstention", "absence_claim", "invented_order", "wrong_value", "ok")
    for oid, k in key.items():
        if k["arm"] != "candidate" or oid not in labels:
            continue
        case, exact = cases[k["id"]], candidate_rows[k["id"]]
        row = row_from_labels(case, exact["reply"], manifests[k["id"]], labels[oid], "candidate")
        for h, d in zip(row["outcome"]["atoms"], exact["outcome"]["atoms"], strict=True):
            checked += 1
            bad = [f for f in fields if h[f] != d[f]]
            if bad:
                differ.append({"oid": oid, "atom": h["atom_id"], "fields": bad})
    return {"candidate_parts_checked": checked, "parts_where_labels_and_exact_flags_differ": len(differ), "details": differ}


def write_dry_run(out_dir: Path, items: list[dict], key: dict) -> dict:
    """Write the rater-visible files and the sealed key separately, with hashes, so the packet cannot be edited after the key is made."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "packet_BLINDED.md").write_text(render_packet(items))
    (out_dir / "labels_TEMPLATE.json").write_text(json.dumps(template(items), indent=1))
    sealed = out_dir / "SEALED"
    sealed.mkdir(exist_ok=True)
    (sealed / "key_DO_NOT_SHOW_RATER.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out_dir / "packet_BLINDED.md", out_dir / "labels_TEMPLATE.json", sealed / "key_DO_NOT_SHOW_RATER.json")}
    (out_dir / "MANIFEST.sha256").write_text("\n".join(f"{h}  {n}" for n, h in sorted(hashes.items())) + "\n")
    return hashes


def main() -> None:
    """Dry run on dev15 only (dev16 untouched): the stored B1a 7B pilot arm stands in for P0, the deterministic path supplies the control. Writes the blinded packet, an EMPTY label template and the sealed key
    under results/p0-adjudication-dryrun-dev15/. Nothing is labelled here."""
    import sys

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    import deterministic_criteria as dc
    import i2b_eval as e

    cases_list = json.loads((here.parent / "cases_dev15.json").read_text())["cases"]
    cases = {c["id"]: c for c in cases_list}
    w = e.World()
    cand = dc.candidate_rows(w, cases_list, e.make_planners(w, cases_list)["T-new"])
    pilot = json.loads((here.parent / "results" / "pilot-dev15-7b.json").read_text())
    p0 = [r for r in pilot["rows"] if r["arm"] == "b1a"]
    items, key = build_packet(p0, cand, cases, seed=20261012)
    hashes = write_dry_run(here.parent / "results" / "p0-adjudication-dryrun-dev15", items, key)
    n_atoms = sum(len(i["atoms"]) for i in items)
    print(f"dry run: {len(items)} replies ({sum(k['arm'] == 'P0' for k in key.values())} P0 stand-in + {sum(k['arm'] == 'candidate' for k in key.values())} candidate control), {n_atoms} parts to label")
    print(json.dumps(hashes, indent=1))


if __name__ == "__main__":
    main()
