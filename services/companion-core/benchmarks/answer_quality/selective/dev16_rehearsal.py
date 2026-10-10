"""End-to-end REHEARSAL of the acceptance runner on already-consumed development data (dev15), never on dev16 (Phase 44, acceptance infrastructure, 2026-10-10). The candidate arm is the real frozen candidate
(per-case authorisation); the P0 arm REPLAYS the stored B1a pilot replies (`results/pilot-dev15-7b.json`), so no model is called. The manifest has purpose "rehearsal" and the same guards, authorisation file,
lock, ledger and immutability rules apply. The output is evidence that the machinery works, not a result about any system.

    python dev16_rehearsal.py <output-dir>
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG_ARGV = list(sys.argv)  # importing the frozen evaluation replaces sys.argv; capture ours first
sys.path.insert(0, str(HERE))
import candidate_freeze
import dev16_candidate_arm as ca
import dev16_freeze_proposal as fp
import dev16_p0 as p0
import dev16_runner as r
import i2b_eval as e

REPO = fp.REPO
AQ = HERE.parent
REL = "services/companion-core/benchmarks/answer_quality"


def rehearse(out: Path, *, head: str = "rehearsal-commit", with_p0_config_check: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cases = json.loads((AQ / "cases_dev15.json").read_text())["cases"]
    by = {c["id"]: c for c in cases}
    world, meta, profiles = ca.load_world(HERE / "corpus_v4.json")
    planner = e.make_planners(world, cases)["T-new"]
    pilot = json.loads((AQ / "results" / "pilot-dev15-7b.json").read_text())
    replay = p0.ReplayP0Executor([x for x in pilot["rows"] if x["arm"] == "b1a"])
    files = dict(fp.ROLES)
    files["cases"] = f"{REL}/cases_dev15.json"
    files["p0_config"] = f"{REL}/selective/dev16_p0_config.json"
    manifest = r.build_manifest(REPO, files, purpose="rehearsal", seed=20261012, commit=head, cases_path=files["cases"])
    mpath = out / "manifest.json"
    r.write_once(mpath, r.canonical(manifest))
    run_id = "run-rehearsal-dev15"
    now = datetime.now(UTC)
    auth = out / "authorization.json"
    r.write_once(auth, json.dumps({"decision": r.AUTH_DECISION, "manifest_sha256": r.manifest_sha256(manifest), "run_id": run_id, "authorized_by": "REHEARSAL ONLY (no owner authorisation; dev15 consumed data)",
                                   "authorized_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(), "single_use": True, "p0_model_calls_authorized": True, "purpose": "rehearsal"}))
    checks = (lambda: ca.verify_declared() + (p0.verify_declared() if with_p0_config_check else []))
    run_dir = r.execute(mpath, REPO, out / "runs", run_id, p0_executor=replay, candidate_arm=lambda cs: ca.candidate_rows(world, cs, planner, meta, profiles), authorization_path=auth, execute_flag=True, now=now,
                        git=lambda root: {"head": head, "dirty_tracked": []}, candidate_check=candidate_freeze.check, config_checks=checks)
    cand = r.read_jsonl(run_dir / "candidate_rows.jsonl")
    record_text, facts, record_context = ca.review_helpers(world, meta, profiles, cand)

    sizes = r.build_review_packets(run_dir, by, record_text, facts, seed=manifest["seed"], rules_sha256=r.sha256_file(HERE / "dev16_criterion6_rules.json"), record_context=record_context)
    report = r.evaluate_run(run_dir, by, record_text, facts, seed=manifest["seed"], rules_sha256=r.sha256_file(HERE / "dev16_criterion6_rules.json"), labels_a=None, labels_b=None, c6_a=None, c6_b=None, record_context=record_context)
    summary = {"purpose": "rehearsal on consumed dev15 data; P0 replies replayed, no model call", "run": run_dir.name, "state": json.loads((run_dir / "STATE.json").read_text())["state"], "packet_sizes": sizes,
               "overall_without_labels": report["variants"]["reviewer_A"]["overall"], "statuses_without_labels": {c["number"]: c["status"] for c in report["variants"]["reviewer_A"]["criteria"]},
               "criterion6": {k: report["criterion6"][k] for k in ("cited_claims", "mechanical_supported", "mechanical_fraction", "pending", "adjudicated_fraction", "best_case_fraction", "status")}}
    r.write_once(out / "REHEARSAL_SUMMARY.json", r.canonical(summary))
    return summary


if __name__ == "__main__":
    print(json.dumps(rehearse(Path(ORIG_ARGV[1])), indent=1))
