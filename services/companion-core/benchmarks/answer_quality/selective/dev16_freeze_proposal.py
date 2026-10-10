"""PROPOSAL for the dev16 acceptance freeze manifest (Phase 44, acceptance infrastructure, 2026-10-10). It lists, with SHA-256 hashes, every file the runner needs fixed, INCLUDING `aq/scoring.py`, and marks the
dev16 files as TO BE HASHED AT THE FREEZE. It does not open, hash or parse any dev16 file. At the freeze, `dev16_runner.build_manifest` produces the real manifest from the same role list plus the dev16 cases
(and a commit and seed fixed by the owner), and the runner verifies that manifest before every execution.

    python dev16_freeze_proposal.py   -> ACCEPTANCE_FREEZE_PROPOSAL.json
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import dev16_runner as r

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
ROLES = {  # role -> path relative to the repository root
    "candidate_manifest": "services/companion-core/benchmarks/answer_quality/selective/CANDIDATE_FREEZE_2026-10-10.sha256",
    "evaluator": "services/companion-core/benchmarks/answer_quality/selective/evaluator.py",
    "scoring": "services/companion-core/benchmarks/answer_quality/aq/scoring.py",
    "corpus": "services/companion-core/benchmarks/answer_quality/selective/corpus_v4.json",
    "p0_config": "services/companion-core/benchmarks/answer_quality/selective/dev16_p0_config.json",
    "candidate_config": "services/companion-core/benchmarks/answer_quality/selective/dev16_candidate_config.json",
    "criterion6_rules": "services/companion-core/benchmarks/answer_quality/selective/dev16_criterion6_rules.json",
    "runner": "services/companion-core/benchmarks/answer_quality/selective/dev16_runner.py",
    "p0_module": "services/companion-core/benchmarks/answer_quality/selective/dev16_p0.py",
    "candidate_arm": "services/companion-core/benchmarks/answer_quality/selective/dev16_candidate_arm.py",
    "criteria_module": "services/companion-core/benchmarks/answer_quality/selective/dev16_criteria.py",
    "criterion6_module": "services/companion-core/benchmarks/answer_quality/selective/dev16_criterion6.py",
    "p0_adjudication": "services/companion-core/benchmarks/answer_quality/selective/p0_adjudication.py",
    "deterministic_criteria": "services/companion-core/benchmarks/answer_quality/selective/deterministic_criteria.py",
    "i2b_eval": "services/companion-core/benchmarks/answer_quality/selective/i2b_eval.py",
    "freeze_proposal_tool": "services/companion-core/benchmarks/answer_quality/selective/dev16_freeze_proposal.py",
    "benchmark_database_builder": "services/companion-core/benchmarks/knowledge_retrieval/kbench/pg_env.py",
    "embedding_module": "services/companion-core/src/companion_core/rag/embeddings.py",
    "reproducibility_probe": "services/companion-core/benchmarks/answer_quality/selective/dev16_p0_reproducibility.py",
    "tiebreak_probe": "services/companion-core/benchmarks/answer_quality/selective/dev16_p0_tiebreak_probe.py",
    "synthetic_fixtures": "services/companion-core/benchmarks/answer_quality/selective/dev16_synthetic.py",
}
AT_FREEZE = ["cases (the dev16 cases file: hash, count, ordered-id hash)", "bank files (the unseen phrasing banks)", "commit (the commit the owner freezes at)", "seed (the review and shuffle seed): 16044, approved prospectively by the owner", "authorisation file (created by the owner, bound to the final manifest hash)", "AQ_PG_IMAGE_DIGEST and AQ_PG_CONTAINER (the disposable database image, verified at run time)"]


def main() -> None:
    files = {role: {"path": rel, "sha256": r.sha256_file(REPO / rel)} for role, rel in ROLES.items()}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    proposal = {"status": "PROPOSAL, not a freeze. dev16 files are not opened, hashed or parsed.", "proposed_on_commit": head, "purpose_at_freeze": "dev16-acceptance", "files": files, "to_be_set_at_freeze": AT_FREEZE,
                "required_roles": list(r.REQUIRED_ROLES), "note": "files must be committed before the freeze; the runner refuses if HEAD differs from the manifest commit or a listed tracked file is modified"}
    (HERE / "ACCEPTANCE_FREEZE_PROPOSAL.json").write_text(r.canonical(proposal))
    print(f"{len(files)} files listed; aq/scoring.py included: {'scoring' in files}")


if __name__ == "__main__":
    main()
