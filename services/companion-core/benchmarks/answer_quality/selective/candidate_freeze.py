"""Freeze (and check) the deterministic candidate before acceptance (Phase 44, final development pass, 2026-10-10): the entity and relation registry, the question decomposer, the transition reader, the
admission / state / contract code, the relation definitions as DATA, the evaluator and the deterministic criteria definitions, the P0 adjudication tooling, and the labelled development sets with their own
freezes. It is a manifest of SHA-256 hashes plus `relation_definitions_frozen.json` (every relation: subjects, value kind, record cues, question cues, label, templates, flags).

What this does NOT do: it does not freeze dev16 or bank D (neither is listed, opened or hashed here), it does not run anything, and it does not approve acceptance. A later change to any listed file makes
`--check` fail until a NEW freeze is written and named in the record; the earlier manifest is kept.

    python candidate_freeze.py --write     -> CANDIDATE_FREEZE_2026-10-10.sha256, relation_definitions_frozen.json
    python candidate_freeze.py --check     -> exit 1 and the changed files if anything differs
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[2] / "src" / "companion_core" / "knowledge" / "answerability_b1"
sys.path.insert(0, str(HERE.parents[2] / "src"))
MANIFEST = HERE / "CANDIDATE_FREEZE_2026-10-10.sha256"
RELATIONS_JSON = HERE / "relation_definitions_frozen.json"

SOURCE = ["__init__.py", "admission.py", "contract.py", "questions.py", "registry.py", "states.py", "transitions.py", "types.py"]
BENCH = ["candidate_freeze.py", "deterministic_criteria.py", "evaluator.py", "i2b_eval.py", "p0_adjudication.py", "decomp_eval.py", "decomposition_set.py", "decomposition_dev_set.json", "DECOMPOSITION_SET.sha256",
         "decomposition_heldout_set.py", "decomposition_heldout_set.json", "HELDOUT_SET.sha256", "review_sample.py", "review_sample_frozen.json", "REVIEW_SAMPLE_FREEZE.sha256", "review_sample_b.py",
         "review_sample_b_frozen.json", "REVIEW_SAMPLE_B_FREEZE.sha256", "transition_probes.py", "TRANSITION_PROBES.sha256", "corpus_v4.json", "relation_definitions_frozen.json"]
CASES = ["cases_dev15.json"]  # the development population. dev16 / bank D are intentionally absent.


def relation_definitions() -> dict:
    from companion_core.knowledge.answerability_b1.registry import RELATIONS

    out = []
    for r in RELATIONS:
        out.append({"name": r.name, "subject_types": sorted(t.value for t in r.subject_types), "kind": r.kind, "cues": list(r.cues), "qcues": list(r.qcues), "label": r.label, "answer_kinds": sorted(r.answer_kinds),
                    "value_types": sorted(t.value for t in r.value_types), "co_types": sorted(t.value for t in r.co_types), "many": r.many, "negation": r.negation, "presence": r.presence, "text_pattern": r.text_pattern,
                    "object_words": list(r.object_words), "structured": r.structured, "unit": r.unit, "prefix": r.prefix, "holder_role": r.holder_role, "allows_next": r.allows_next, "plural": r.plural,
                    "sentence": r.sentence, "sentence_past": r.sentence_past, "speaker_ok": r.speaker_ok})
    return {"count": len(out), "defined_in_final_development_pass": ["release_day", "escalation_contact", "approver"], "relations": out}


def files() -> list[tuple[str, Path]]:
    return [(f"src/{n}", SRC / n) for n in SOURCE] + [(f"selective/{n}", HERE / n) for n in BENCH] + [(f"answer_quality/{n}", HERE.parent / n) for n in CASES]


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write() -> None:
    RELATIONS_JSON.write_text(json.dumps(relation_definitions(), indent=1, sort_keys=True) + "\n")
    lines = [f"# Freeze of the deterministic candidate before acceptance, {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%S+00:00')}. dev16 and bank D are NOT listed, opened or hashed. A change to any file here",
             "# needs a new freeze file named in the record. Relations defined in this pass: release_day, escalation_contact, approver."]
    lines += [f"{digest(p)}  {name}" for name, p in files()]
    MANIFEST.write_text("\n".join(lines) + "\n")
    print(f"froze {len(lines) - 2} files; {relation_definitions()['count']} relations")


def check() -> list[str]:
    changed = []
    if json.dumps(relation_definitions(), indent=1, sort_keys=True) + "\n" != RELATIONS_JSON.read_text():
        changed.append("relation definitions in registry.py differ from relation_definitions_frozen.json")
    listed = {}
    for line in MANIFEST.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        h, name = line.split(None, 1)
        listed[name.strip()] = h
    for name, p in files():
        if name not in listed:
            changed.append(f"{name}: not in the manifest")
        elif digest(p) != listed[name]:
            changed.append(f"{name}: changed")
    return changed


if __name__ == "__main__":
    if "--write" in sys.argv:
        write()
    else:
        bad = check()
        print("\n".join(bad) if bad else "candidate freeze intact")
        sys.exit(1 if bad else 0)
