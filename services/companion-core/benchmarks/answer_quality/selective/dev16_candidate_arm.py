"""The deterministic candidate arm as the acceptance runner executes it (Phase 44, acceptance infrastructure, 2026-10-10). It composes FROZEN code only (the candidate sources, `i2b_eval.World`,
`make_planners(...)["T-new"]`, `deterministic_criteria.question_row`) and changes none of it. What this module adds is harness-side and deterministic:

  * PER-CASE AUTHORISATION. The frozen World carries one global authorisation (record sensitivity), which equals the `owner_private` profile of the invented corpus and is all dev15 used. Other access
    profiles exist (`shared_speaker`, `harbor_only`, ...). The runner therefore derives each case's authorisation decisions from the authoritative corpus facts of that case's profile
    (`kbench.security.violations`) and passes them to the frozen planner (`planner(q, auths=...)`) and to the row builder (as a per-case world view). For `owner_private` the result is identical to the
    default (verified on the consumed dev15 data in the tests).
  * THE DECLARED CONFIGURATION. `DECLARED` is the predeclared configuration; `effective()` computes the same facts from the imported modules; the runner refuses to run if they differ.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parents[1] / "knowledge_retrieval")]
CONFIG_PATH = HERE / "dev16_candidate_config.json"

DECLARED = {
    "arm": "candidate",
    "path": "deterministic selective answering (Stage B-1), no model",
    "planner": "i2b_eval.make_planners(world, cases)['T-new']  (question text only; entity registry = grammar + entries harvested from the record pool)",
    "decomposer_and_registry": "companion_core.knowledge.answerability_b1.questions / registry (frozen by CANDIDATE_FREEZE_2026-10-10.sha256)",
    "relation_definitions_sha256": "set by write_declared()",
    "evaluation_clock_now": "set by write_declared()",
    "admission_policy": "set by write_declared()",
    "authorisation_model": "per case: kbench.security.violations(record, the case's access profile) empty -> authorised; checked_at = now - 3 s; policy 'p1'; acl revision 1",
    "evidence_ids": "one id per distinct record in pool order (i2_eval.build_world)",
    "row_builder": "deterministic_criteria.question_row with a per-case world view",
    "output": "one evaluator row per case, same order as the frozen cases file",
}


def _constants():
    import i2b_eval as e  # importing it sets the B-1 configuration flags the frozen evaluation uses; the policy must be read through it

    h = e.h
    pol = h.POLICY
    return {"evaluation_clock_now": h.NOW.isoformat(), "admission_policy": {"expected_policy_version": pol.expected_policy_version, "auth_max_age_s": pol.auth_max_age.total_seconds(), "clock_skew_s": pol.clock_skew.total_seconds(),
                                                                         "allow_context": pol.allow_context, "qualified_object_check": pol.qualified_object_check, "equivalences": sorted(pol.equivalences)}}


def effective() -> dict:
    import candidate_freeze

    rel = json.dumps(candidate_freeze.relation_definitions(), indent=1, sort_keys=True) + "\n"
    return {**DECLARED, "relation_definitions_sha256": hashlib.sha256(rel.encode()).hexdigest(), **_constants()}


def write_declared() -> dict:
    cfg = effective()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=1, sort_keys=True) + "\n")
    return cfg


def verify_declared() -> list[str]:
    declared = json.loads(CONFIG_PATH.read_text())
    eff = effective()
    return [f"candidate configuration differs at {k}" for k in sorted(set(declared) | set(eff)) if declared.get(k) != eff.get(k)]


# --- per-case authorisation and rows -------------------------------------------------------------------------------------------------------------------------------------------------------------

class CaseWorld:
    """The two attributes `deterministic_criteria.question_row` reads from a world, specialised to one case's authorisation."""

    def __init__(self, world, auths):
        self.ref_of = world.ref_of
        self.unauth = {r for r, d in auths.items() if not d.authorized}


def record_violations(meta: dict, profile: dict):
    from kbench.security import violations

    def f(ref: str, case: dict | None = None) -> list[str]:
        key = ref.split("#")[0]
        return ["not_in_corpus"] if key not in meta else violations(key, meta, profile)

    return f


def case_auths(world, meta: dict, profile: dict) -> dict:
    from companion_core.knowledge.answerability_b1 import AuthDecision

    f = record_violations(meta, profile)
    return {ref: AuthDecision(not f(ref), d.checked_at, d.policy_version, d.acl_revision) for ref, d in world.auths.items()}


def candidate_rows(world, cases: list[dict], planner, meta: dict, profiles: dict) -> list[dict]:
    import deterministic_criteria as dc

    rows = []
    for q in cases:
        auths = case_auths(world, meta, profiles[q["access"]])
        plan, comps, _ = planner(q, auths=auths)
        rows.append(dc.question_row(CaseWorld(world, auths), q, plan, comps, "deterministic"))
    return rows


def load_world(corpus_path: Path):
    """The frozen World over a corpus file, plus the corpus's authoritative per-record facts and access profiles. KBENCH_CORPUS is set only while the corpus is read and restored afterwards, so nothing else
    in the process (or the test suite) is left pointing at this corpus."""
    import asyncio
    import os

    previous = os.environ.get("KBENCH_CORPUS")
    os.environ["KBENCH_CORPUS"] = str(corpus_path)
    try:
        import i2b_eval as e
        from kbench.corpus import build_corpus
        from kbench.fixtures import source_meta

        w = e.World(Path(corpus_path))
        spec = asyncio.run(build_corpus()).spec
        return w, source_meta(spec), spec["access_profiles"]
    finally:
        if previous is None:
            os.environ.pop("KBENCH_CORPUS", None)
        else:
            os.environ["KBENCH_CORPUS"] = previous


def review_helpers(world, meta: dict, profiles: dict, cand_rows: list[dict]):
    """(record_text, facts) for the criterion-6 packets and adjudication: record text from the frozen World, evidence-universe facts from the corpus facts of each case's access profile."""
    import dev16_criterion6 as c6

    manifests = {r["id"]: r["manifest"] for r in cand_rows}

    def record_text(case_id: str, eid: str) -> str:
        return world.texts.get(manifests[case_id][eid]["refs"][0], "")

    def facts(case: dict, eid: str) -> dict:
        return c6.universe_facts(case, eid, manifests[case["id"]], record_violations(meta, profiles[case["access"]]))

    titles = {i.ref: i.title for i in world.items}
    titles.update({rec.ref: getattr(rec, "title", "") for rec in world.structured})

    def record_context(case_id: str, eid: str) -> str:
        """The admissible context of a cited record: its title (and, for a resolved meeting segment, the speaker is already part of its text). Nothing else is shown."""
        ref = manifests[case_id][eid]["refs"][0]
        return titles.get(ref, "") or ""

    return record_text, facts, record_context
