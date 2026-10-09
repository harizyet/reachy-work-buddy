"""Loading and validating the answer-quality cases and fixing their hashes. The corpus is the 44A synthetic one, read-only."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
KR = HERE.parent / "knowledge_retrieval"
if str(KR) not in sys.path:
    sys.path.insert(0, str(KR))

from kbench.fixtures import (
    load_corpus,
    parse_ref,
    source_meta,
    source_texts,
)

CATEGORIES = (
    "single_source", "cross_source", "relationship", "temporal", "conflict", "negative", "authorization", "authorization_control",
    "sensitive_partial", "scope", "shared_speaker", "cloud_destination", "injection", "attached_meeting", "voice",
    "status_routing", "unsupported_inference", "restricted_wording", "supported_control", "numeric_control",
    "person_responsibility", "attribution", "property_grounding", "supersession",
    "no_evidence", "partial_evidence", "wrong_entity", "negative_claim",
)
FILES = {"dev": "cases_dev.json", "holdout": "cases_holdout.json", "dev2": "cases_dev2.json", "dev3": "cases_dev3.json", "dev4": "cases_dev4.json", "dev5": "cases_dev5.json", "dev6": "cases_dev6.json", "dev7": "cases_dev7.json"}


class CaseError(ValueError):
    pass


def load_cases(split: str) -> list[dict[str, Any]]:
    return json.loads((HERE / FILES[split]).read_text())["cases"]


def case_hashes() -> dict[str, str]:
    hashes = {name: hashlib.sha256((HERE / file).read_bytes()).hexdigest() for name, file in FILES.items()}
    corpus = hashlib.sha256((KR / "corpus.json").read_bytes()).hexdigest()
    combined = hashlib.sha256("".join([hashes["dev"], hashes["holdout"], corpus]).encode()).hexdigest()
    return {**hashes, "corpus": corpus, "combined": combined}


def validate(cases_by_split: dict[str, list[dict[str, Any]]] | None = None) -> list[str]:
    """Every problem found. A case is only valid if the question can be answered from its gold sources: each required fact must be
    met by the gold text, unless the case says the model states it itself (`model_stated`)."""
    cases_by_split = cases_by_split or {s: load_cases(s) for s in FILES}
    corpus = load_corpus()
    texts, meta = source_texts(corpus), source_meta(corpus)
    profiles, meetings = corpus["access_profiles"], {m["id"] for m in corpus["meetings"]}
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_q: dict[str, str] = {}
    for split, cases in cases_by_split.items():
        for c in cases:
            cid = c["id"]
            if cid in seen_ids:
                problems.append(f"{cid}: duplicate id")
            seen_ids.add(cid)
            key = (c["question"] + "|" + c["access"]).lower()
            if key in seen_q and seen_q[key] != split:
                problems.append(f"{cid}: same question and access as a case in {seen_q[key]}")
            seen_q[key] = split
            if c["category"] not in CATEGORIES:
                problems.append(f"{cid}: unknown category {c['category']!r}")
            if c["access"] not in profiles:
                problems.append(f"{cid}: unknown access profile")
            if c["attached_meeting"] and c["attached_meeting"] not in meetings:
                problems.append(f"{cid}: unknown attached meeting")
            for ref in [*c["gold_refs"], *c["distractor_refs"], *c["excluded_refs"]]:
                st, sid, loc = parse_ref(ref)
                if f"{st}:{sid}" not in meta or (loc is not None and ref not in texts):
                    problems.append(f"{cid}: reference {ref} is not in the corpus")
            if c["abstain"] and (c["gold_refs"] or c["required"]):
                problems.append(f"{cid}: an abstention case has no gold sources or required facts")
            if not c["abstain"] and not c["required"]:
                problems.append(f"{cid}: an answerable case needs required facts")
            if not c["abstain"] and not c["gold_refs"]:
                problems.append(f"{cid}: an answerable case needs gold sources")
            gold_text = " ".join(_gold_text(ref, texts) for ref in c["gold_refs"])
            stated = set(c.get("model_stated", []))
            for i, alts in enumerate(c["required"]):
                if i not in stated and not any(re.search(a, gold_text, re.IGNORECASE) for a in alts):
                    problems.append(f"{cid}: required fact {i} {alts} is not in the gold sources")
            for pattern in [*(f for f in c["forbidden"]), *c["canaries"], *c["followed"], *(a for r in c["required"] for a in r)]:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    problems.append(f"{cid}: bad pattern {pattern!r}: {exc}")
            for pattern in c["canaries"]:
                if re.search(pattern, c["question"], re.IGNORECASE):
                    problems.append(f"{cid}: canary {pattern!r} appears in the question, so an answer repeating the question would trip it")
            for pattern in c.get("plants", []):
                if not any(re.search(pattern, t, re.IGNORECASE) for t in texts.values()):
                    problems.append(f"{cid}: planted text {pattern!r} is not in the corpus")
            # profile sanity: an answerable case's gold must be reachable by its profile
            for ref in c["gold_refs"]:
                st, sid, _ = parse_ref(ref)
                m = meta[f"{st}:{sid}"]
                prof = profiles[c["access"]]
                from companion_core.semantic import access as rules

                from shared.models.response import Privacy

                if not rules.within_ceiling(Privacy(m["sensitivity"]), Privacy(prof["ceiling"])) or (
                    prof["scopes"] is not None and m["scope"] is not None and m["scope"] not in prof["scopes"]
                ) or (m["local_only"] and "cloud" in prof["destinations"]):
                    problems.append(f"{cid}: gold {ref} is not reachable under {c['access']}")
    return problems


def _gold_text(ref: str, texts: dict[str, str]) -> str:
    if ref in texts:
        text = texts[ref]
        if ref.startswith("meeting:") and "#" in ref:  # a segment is shown with its speaker's name
            meeting = next(m for m in load_corpus()["meetings"] if m["id"] == ref[8:].split("#")[0])
            seg = meeting["segments"][int(ref.split("#")[1])]
            text = f"{meeting['speaker_names'].get(seg['speaker'], '')}: {text}"
        return text
    prefix = ref + "#"
    return " ".join(t for k, t in texts.items() if k.startswith(prefix))
