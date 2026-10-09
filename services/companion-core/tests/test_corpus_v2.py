"""Corpus v2 and its question pool (groundedness milestone, stage 0): deterministic, internally consistent, and the design/acceptance split is real (dev12 holds only held-out relations, held-out projects or unseen paraphrases)."""

import json
import os
import sys
from pathlib import Path

AQ = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality"
sys.path.insert(0, str(AQ / "corpus_v2"))
sys.path.insert(0, str(AQ))
import gen


def test_the_generator_is_deterministic_and_matches_the_files_on_disk():
    corpus, registry = gen.build()
    assert json.loads((AQ / "corpus_v2" / "corpus_v2.json").read_text()) == corpus
    assert json.loads((AQ / "corpus_v2" / "facts_v2.json").read_text()) == registry


def test_every_registry_reference_exists_in_the_corpus():
    corpus, registry = gen.build()
    have = {f"memory:{m['id']}" for m in corpus["memories"]} | {f"document:{d['id']}" for d in corpus["documents"]} | {f"note:{n['id']}" for n in corpus["notes"]} | {f"meeting:{m['id']}" for m in corpus["meetings"]}
    for f in registry["facts"]:
        for ref in f["refs"]:
            assert ref.split("#")[0] in have, (f["id"], ref)


def test_sensitive_facts_are_only_in_sensitive_records_and_marked_unauthorized():
    corpus, registry = gen.build()
    sensitive = {f"document:{d['id']}" for d in corpus["documents"] if d["sensitivity"] == "sensitive"}
    flagged = [f for f in registry["facts"] if f["sensitive"]]
    assert flagged and all(f["state"] == "unauthorized" and set(f["refs"]) <= sensitive for f in flagged)


def test_dev11_and_dev12_are_disjoint_and_dev12_is_all_held_out():
    d11 = json.loads((AQ / "cases_dev11.json").read_text())["cases"]
    d12 = json.loads((AQ / "cases_dev12.json").read_text())["cases"]
    assert not ({c["question"] for c in d11} & {c["question"] for c in d12})
    assert all(c["held_out"] for c in d12) and not any(c["held_out"] for c in d11)
    assert sum(not c["abstain"] for c in d12) >= 50 and len(d12) >= 80  # the milestone's minimum for the acceptance set


def test_the_v2_splits_validate_against_corpus_v2_only():
    os.environ["KBENCH_CORPUS"] = str(AQ / "corpus_v2" / "corpus_v2.json")
    try:
        from aq import cases as caselib

        assert caselib.validate() == []
    finally:
        os.environ.pop("KBENCH_CORPUS", None)
