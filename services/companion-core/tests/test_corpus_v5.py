"""Corpus v5 (existence families), bank E, probe bank E, the manifest and the cluster-aware analysis: structure, provenance and authorisation semantics, frozen hashes. No model, no scorer evaluation."""

import collections
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"
AQ = SEL.parent
for p in (str(SEL), str(AQ)):
    if p not in sys.path:
        sys.path.insert(0, p)


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SEL / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


g5 = load("sel_corpus_gen_v5", "corpus_gen_v5.py")
banks_e = load("sel_banks_e", "banks_e.py")
banks = load("sel_banks_c", "banks.py")
q5 = load("sel_questions_gen_v5", "questions_gen_v5.py")
cluster = load("sel_cluster", "cluster_analysis.py")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def world(seed=31):
    corpus, registry = g5.build(seed)
    return corpus, registry


def test_every_design_project_gets_each_family_once_with_balanced_conditions():
    _, reg = world()
    facts = [f for f in reg["facts"] if f["relation"] in g5.FAMILIES]
    assert len(facts) == len(g5.design_projects()) * 4 == 32
    assert len({(f["subject"], f["relation"]) for f in facts}) == 32 and not g5.check_unique(reg)
    counts = collections.Counter(f["state"] for f in facts)
    assert set(counts) == set(g5.CONDITIONS) and min(counts.values()) >= 5
    assert all(not f["held_out"] and f["subject"].lower() not in g5.gen.HELD_OUT_PROJECTS for f in facts)


def test_each_condition_has_its_evidence_provenance_and_authorisation():
    corpus, reg = world()
    mem = {f"memory:{m['id']}": m for m in corpus["memories"]}
    notes = {f"note:{n['id']}": n for n in corpus["notes"]}
    docs = {f"document:{d['id']}": d for d in corpus["documents"]}
    for f in (f for f in reg["facts"] if f["relation"] in g5.FAMILIES):
        c = f["state"]
        if c == "explicit_absence":
            (r,) = f["refs"]
            assert " no " in mem[r]["text"] and mem[r]["author_class"] == "owner" and mem[r]["sensitivity"] == "work-private"
        elif c == "incomplete_scope":
            (r,) = f["refs"]
            body = notes[r]["body"]
            assert "only" in body and "not " in body and "found none" in body  # the trap sentence and the scope limit are both present
        elif c == "source_disagreement":
            a, b = (mem[r] for r in f["refs"])
            assert a["created"] == b["created"] and ("has no" in a["text"]) != ("has no" in b["text"])  # same day, opposite statements: no ordering basis
        elif c == "other_authorized_source":
            (r,) = f["refs"]
            assert r in docs and docs[r]["sensitivity"] == "work-private" and docs[r]["author_class"] == "third_party"
        elif c == "unauthorized_only":
            (r,) = f["refs"]
            assert docs[r]["sensitivity"] == "sensitive" and f["sensitive"]  # above the owner_private ceiling
        else:
            assert c == "silent" and f["refs"] == []


def test_gold_statuses_follow_the_conditions_and_unauthorised_or_incomplete_evidence_is_never_a_source():
    _, reg = world()
    cases = q5.build_cases(reg, 31)
    ex = {a["id"]: a for c in cases for a in c["atoms"] if a.get("family") == "existence"}
    assert len(ex) == 32
    for a in ex.values():
        assert a["status"] == g5.STATUS_OF[a["condition"]] and a["world"] == 31
        if a["status"] == "NEGATIVE_UNSUPPORTED":
            assert a["sources"] == []
        if a["status"] == "CONFLICTED":
            assert len(a["values"]) == 2 and len(a["sources"]) == 2


def test_questions_use_only_bank_e_and_bank_e_shares_no_phrasing_with_banks_c_and_d():
    old = {p.lower() for v in banks.BANKS.values() for p in v}
    new = {p.lower() for v in banks_e.BANK_E.values() for p in v}
    assert not (old & new)
    assert (set(banks.BANKS) - banks.HELD_OUT) | set(g5.FAMILIES) <= set(banks_e.BANK_E)  # held-out relations stay out of the validation worlds
    _, reg = world()
    cases = q5.build_cases(reg, 31)
    assert all(c["bank"] == "E" for c in cases)
    sample = [c for c in cases if c["family"] == "existence"][:5]
    assert all(any(e.split("{")[0].strip().lower()[:12] in c["question"].lower() for v in banks_e.BANK_E.values() for e in v) for c in sample)


def test_the_v4_world_and_the_first_manifest_are_untouched_by_the_v5_generator():
    manifest_old = json.loads((SEL / "validation" / "fresh_corpus_manifest.json").read_text())
    manifest_new = json.loads((SEL / "validation" / "fresh_v5_manifest.json").read_text())
    assert set(manifest_old["seeds"]).isdisjoint(set(manifest_new["worlds"])) and len(manifest_new["worlds"]) == 18 and manifest_new["version"] == 5
    gen = g5.gen
    saved = gen.SEED
    _corpus, _ = gen.build.__wrapped__(14) if hasattr(gen.build, "__wrapped__") else (None, None)
    gen.SEED = 14
    corpus4, _ = gen.build()
    gen.SEED = saved
    assert json.loads((SEL / "corpus_v4.json").read_text()) == json.loads(json.dumps(corpus4))


def test_bank_e_and_probe_bank_e_are_frozen_by_hash():
    assert (SEL / "bank_e.sha256").read_text().split()[0] == sha(SEL / "banks_e.py")
    lines = (SEL / "validation" / "probe_bank_e.sha256").read_text().splitlines()
    assert lines[0].split()[0] == sha(SEL / "validation" / "probe_bank_e.json") and lines[1].split()[0] == sha(SEL / "probe_bank_e.py")
    manifest = json.loads((SEL / "validation" / "fresh_v5_manifest.json").read_text())
    assert manifest["bank_e_sha256"] == sha(SEL / "banks_e.py")


def test_two_worlds_regenerate_to_their_manifest_hashes():
    fm = load("sel_fresh_v5_manifest", "fresh_v5_manifest.py")
    manifest = json.loads((SEL / "validation" / "fresh_v5_manifest.json").read_text())["worlds"]
    for seed in (31, 48):
        corpus, registry, cases = fm.world(seed)
        w = manifest[str(seed)]
        assert (fm.digest(corpus), fm.digest(registry), fm.digest(cases)) == (w["corpus_sha256"], w["facts_sha256"], w["cases_sha256"])


def test_cluster_aware_analysis_is_more_conservative_than_the_primary_bound_when_worlds_differ():
    even = {w: (5, 5) for w in range(10)}
    r = cluster.analyse(even)
    assert r["primary_exact_one_sided_95_lower"] >= 0.94 and r["conservative_lower_bound"] >= 0.94
    uneven = {w: ((3, 5) if w % 3 == 0 else (5, 5)) for w in range(12)}
    r = cluster.analyse(uneven)
    assert r["conservative_lower_bound"] <= r["primary_exact_one_sided_95_lower"] and r["design_effect"]["icc"] > 0
    assert cluster.analyse({1: (0, 0)})["conservative_lower_bound"] is None
