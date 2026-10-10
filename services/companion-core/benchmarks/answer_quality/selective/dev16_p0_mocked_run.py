"""Production-path rehearsal of the corrected P0 executor with a MOCK model service (Phase 44, P0 reproducibility correction, 2026-10-10). The real `RealP0Executor` default path runs: offline mode, the
database-image requirement and docker verification, the real embedding load from the local cache, a real PostgreSQL build with STABLE ids, real access-context retrieval and prompt assembly, the real runner and
the real frozen candidate arm. Only the model is a disposable mock on 127.0.0.1 (the executor refuses any other target). NO PRODUCTION INFERENCE. A socket guard records every connection attempt: any non-loopback
connection fails the run.

    python dev16_p0_mocked_run.py <output-dir>     (KBENCH_DATABASE_URL, AQ_PG_IMAGE_DIGEST and AQ_PG_CONTAINER must name the disposable database)
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ORIG = list(sys.argv)
sys.path.insert(0, str(HERE))
import candidate_freeze
import dev16_candidate_arm as ca
import dev16_freeze_proposal as fp
import dev16_p0 as p0
import dev16_runner as r
import dev16_synthetic as s
import i2b_eval as e

REL = "services/companion-core/benchmarks/answer_quality"


def main(out: Path) -> dict:
    out.mkdir(parents=True)
    cases_src = HERE.parent / "results" / "dev16-p0-smoke-dev15" / "cases_smoke_dev15.json"
    cases = json.loads(cases_src.read_text())["cases"]
    (out / "cases_smoke_dev15.json").write_text(cases_src.read_text())
    attempts = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        attempts.append(str(host))
        if isinstance(address, tuple) and host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"non-loopback connection blocked by the rehearsal guard: {host}")
        return real_connect(self, address)

    shim = SimpleNamespace(cases=cases, p0_reply=lambda c: f"Mock reply for {c['id']} [E1].")
    world, meta, profiles = ca.load_world(HERE / "corpus_v4.json")
    planner = e.make_planners(world, cases)["T-new"]
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=HERE).stdout.strip()
    files = dict(fp.ROLES)
    files["cases"] = f"{REL}/results/dev16-p0-mocked-run/cases_smoke_dev15.json"
    manifest = r.build_manifest(fp.REPO, files, purpose="rehearsal", seed=16044, commit=head, cases_path=files["cases"])
    mpath = out / "manifest.json"
    r.write_once(mpath, r.canonical(manifest))
    now = datetime.now(UTC)
    auth = out / "authorization.json"
    r.write_once(auth, json.dumps({"decision": r.AUTH_DECISION, "manifest_sha256": r.manifest_sha256(manifest), "run_id": "mocked-1", "authorized_by": "REHEARSAL ONLY: mock model service, no production inference", "authorized_at": now.isoformat(),
                                   "expires_at": (now + timedelta(hours=1)).isoformat(), "single_use": True, "p0_model_calls_authorized": True, "purpose": "rehearsal"}))
    before = {k: os.environ.get(k) for k in (*p0.OFFLINE_VARS, "KBENCH_CORPUS")}
    with s.MockService(shim) as svc:
        executor = p0.RealP0Executor(HERE / "corpus_v4.json", llm_factory=lambda: s.local_client(svc.port), rehearsal_mock_port=svc.port)
        socket.socket.connect = guarded
        try:
            run_dir = r.execute(mpath, fp.REPO, out / "runs", "mocked-1", p0_executor=executor, candidate_arm=lambda cs: ca.candidate_rows(world, cs, planner, meta, profiles), authorization_path=auth, execute_flag=True, now=now,
                                git=lambda root: {"head": head, "dirty_tracked": []}, candidate_check=candidate_freeze.check, config_checks=list)
        finally:
            socket.socket.connect = real_connect
        requests = list(svc.requests)
    after = {k: os.environ.get(k) for k in before}
    env_art = json.loads((run_dir / "p0_environment.json").read_text())
    rows = r.read_jsonl(run_dir / "p0_rows.jsonl")
    non_loopback = [a for a in attempts if a not in ("127.0.0.1", "::1", "localhost")]
    report = {"purpose": "production-path rehearsal with a mock model service; no production inference", "state": json.loads((run_dir / "STATE.json").read_text())["state"], "rows": len(rows),
              "completions_sent_to_the_mock": sum(1 for q in requests if q[0] == "POST"), "tokenizer_calls_to_the_mock": sum(1 for q in requests if q[0] == "POST-tokenize"), "connection_attempts": len(attempts), "non_loopback_connection_attempts": non_loopback,
              "environment_artifact": {"database": env_art["database"], "embedding_model": env_art["embedding_model"], "offline_during_run": env_art["offline"], "served_models_response_recorded": "served_models_response" in env_art},
              "environment_restored_after_run": before == after, "env_before": before, "env_after": after}
    (out / "MOCKED_RUN_REPORT.json").write_text(json.dumps(report, indent=1, default=str))
    return report


if __name__ == "__main__":
    print(json.dumps(main(Path(ORIG[1])), indent=1, default=str))
