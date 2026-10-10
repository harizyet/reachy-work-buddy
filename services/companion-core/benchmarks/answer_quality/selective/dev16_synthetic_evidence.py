"""Run the synthetic end-to-end CLI rehearsal scenarios and write their outcomes as evidence (Phase 44, acceptance infrastructure, 2026-10-10). Synthetic cases, a disposable git repository, a disposable mock model
service on 127.0.0.1; no production inference, no dev16, no real authorisation, no write to the formal acceptance directory.

    python dev16_synthetic_evidence.py <output-dir>     (the directory must not exist)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIG_ARGV = list(sys.argv)
sys.path.insert(0, str(HERE))
import dev16_runner as r
import dev16_synthetic as s


def drive(fx, svc, cmd, run_id="run-1", approval=None, extra=()):
    args = [cmd, *s.common(fx)] + (["--runs-root", str(fx.runs), "--run-id", run_id] if cmd in ("verify", "run") else []) + (["--execute"] if cmd == "run" else []) + list(extra)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = s.run_cli(fx, svc.port, args, approval=approval)
    return rc, buf.getvalue()


def lifecycle(base: Path, scenario: str, flip: int) -> dict:
    fx = s.new_fixture(base, scenario)
    with s.MockService(fx) as svc:
        rc_run, _ = drive(fx, svc, "run", approval=fx.authorization("run-1"))
        rc_second, out_second = drive(fx, svc, "run", run_id="run-2", approval=fx.authorization("run-2"))
        d = fx.runs / "run-1"
        drive(fx, svc, "packets", extra=["--run-dir", str(d)])
        rev = fx.runs / "run-1-review"
        cand = r.read_jsonl(d / "candidate_rows.jsonl")
        paths = {}
        for name, obj in (("la", fx.reviewer_labels(rev, cand)), ("lb", fx.reviewer_labels(rev, cand, flip=flip)), ("ca", fx.c6_answers(rev)), ("cb", fx.c6_answers(rev))):
            paths[name] = fx.work / f"{name}.json"
            paths[name].write_text(json.dumps(obj))
        rc_eval, _ = drive(fx, svc, "evaluate", extra=["--run-dir", str(d), "--p0-labels-a", str(paths["la"]), "--p0-labels-b", str(paths["lb"]), "--c6-answers-a", str(paths["ca"]), "--c6-answers-b", str(paths["cb"]),
                                                       "--p0-labels-reconciled", str(paths["la"])])
        rep = json.loads((fx.runs / "run-1-report" / "report.json").read_text())
        a = rep["variants"]["reviewer_A"]
        return {"scenario": scenario, "run_exit": rc_run, "second_run_exit": rc_second, "second_run_refused": "one shot only" in out_second, "evaluate_exit": rc_eval, "p0_posts": sum(1 for q in svc.requests if q[0] == "POST"),
                "cases": len(fx.cases), "overall": {k: (v["overall"] if v else None) for k, v in rep["variants"].items()}, "criteria": {c["number"]: c["status"] for c in a["criteria"]}, "counts": a["counts"],
                "kappa": rep["agreement"]["kappa"], "criterion6": {k: rep["criterion6"][k] for k in ("cited_claims", "mechanical_fraction", "adjudicated_fraction", "credited_by_adjudication", "status")}}


def _rmtree(path: Path) -> None:
    """Run directories are read-only by design: make every directory and file writable first, then remove the tree."""
    for root, dirs, files in os.walk(path):
        os.chmod(root, stat.S_IRWXU)
        for name in dirs + files:
            full = os.path.join(root, name)
            if not os.path.islink(full):
                os.chmod(full, stat.S_IRWXU)
    shutil.rmtree(path)


def main(out: Path) -> dict:
    """Fixtures (disposable git repositories, read-only run directories) live in a temporary directory that is removed afterwards; only the summary is kept."""
    out.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="dev16-synthetic-"))
    try:
        result = {"purpose": "synthetic end-to-end CLI rehearsal; mock service only; nothing about any real system",
                  "scenarios": [lifecycle(tmp / "good", "good", 4), lifecycle(tmp / "thin", "thin", 3), lifecycle(tmp / "bad", "bad", 3)]}
        fx = s.new_fixture(tmp / "aborted", "good")
        with s.MockService(fx, fail_after=40) as svc:
            rc, _ = drive(fx, svc, "run", approval=fx.authorization("run-1"))
            rc2, out2 = drive(fx, svc, "run", run_id="run-2", approval=fx.authorization("run-2"))
            st = json.loads((fx.runs / "run-1" / "STATE.json").read_text())
            result["service_failure_mid_run"] = {"exit": rc, "state": st["state"], "rows_flushed": len(r.read_jsonl(fx.runs / "run-1" / "p0_rows.jsonl")), "rerun_exit": rc2, "rerun_refused": "one shot only" in out2}
        result["formal_acceptance_directory_exists"] = r.FORMAL_RUNS_DIR.exists()
    finally:
        _rmtree(tmp)
    (out / "SYNTHETIC_CLI_REHEARSAL.json").write_text(r.canonical(result))
    return result


if __name__ == "__main__":
    print(json.dumps(main(Path(ORIG_ARGV[1])), indent=1)[:3000])
