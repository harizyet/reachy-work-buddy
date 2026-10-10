"""Phase 44 acceptance infrastructure: a FULL SYNTHETIC END-TO-END rehearsal of the real runner entry point (`dev16_runner.main`). Disposable git repository, disposable mock model service on 127.0.0.1, synthetic
cases, synthetic reviewers. The REAL P0 adapter (`RealP0Executor`: health check, model check, streamed completion, row schema) runs against the mock with a synthetic preparer. No production inference, no dev16, no
real authorisation, and the formal acceptance directory is never written."""

import importlib.util
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load(name):
    saved = list(sys.argv)
    sys.path[:0] = [str(SEL), str(SEL.parent), str(SEL.parents[1] / "knowledge_retrieval")]
    try:
        spec = importlib.util.spec_from_file_location(name, SEL / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv[:] = saved
        del sys.path[:3]


S, R, P0, CA = _load("dev16_synthetic"), _load("dev16_runner"), _load("dev16_p0"), _load("dev16_candidate_arm")


def cli(fx, svc, cmd, run_id="run-1", approval=None, extra=()):
    args = [cmd, *S.common(fx)]
    if cmd in ("verify", "run"):
        args += ["--runs-root", str(fx.runs), "--run-id", run_id]
    if cmd == "run":
        args += ["--execute"]
    return S.run_cli(fx, svc.port, args + list(extra), approval=approval)


def posts(svc):
    return sum(1 for q in svc.requests if q[0] == "POST")


def never_formal():
    assert not R.FORMAL_RUNS_DIR.exists(), "a rehearsal wrote to the formal acceptance directory"


# -- the whole lifecycle through the real entry point ---------------------------------------------------------------------------------------------------------------------------------------------

def test_the_complete_lifecycle_through_the_real_entry_point(tmp_path, capsys):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx) as svc:
        assert cli(fx, svc, "verify") == 0 and "all guards pass" in capsys.readouterr().out
        assert svc.requests == []  # verification makes no call at all
        assert cli(fx, svc, "run") == 1 and "no execution authorisation" in capsys.readouterr().out and svc.requests == []
        auth = fx.authorization("run-1")
        assert S.run_cli(fx, svc.port, ["run", *S.common(fx), "--runs-root", str(fx.runs), "--run-id", "run-1"], approval=auth) == 1 and "--execute was not given" in capsys.readouterr().out
        assert svc.requests == []
        assert cli(fx, svc, "run", approval=auth) == 0
        d = fx.runs / "run-1"
        assert json.loads((d / "STATE.json").read_text())["state"] == "COMPLETE" and posts(svc) == len(fx.cases)
        assert {(q[2], q[3], q[4]) for q in svc.requests if q[0] == "POST"} == {(0, 44, 350)}  # the declared decoding really reached the service
        rows = R.read_jsonl(d / "p0_rows.jsonl")
        assert [x["id"] for x in rows] == [c["id"] for c in fx.cases] == [x["id"] for x in R.read_jsonl(d / "candidate_rows.jsonl")]
        assert rows[0]["reply"] == fx.p0_reply(fx.cases[0]) and rows[0]["finish_reason"] == "stop" and rows[0]["prompt_tokens"] == 11 and len(rows[0]["messages_sha256"]) == 64
        assert rows[0]["manifest"] == {"E1": {"refs": ["memory:m1"], "authorized": True}}
        prov = json.loads((d / "provenance.json").read_text())
        assert prov["git"]["head"] == fx.commit and prov["mode"] == "rehearsal" and prov["authorization_sha256"] and prov["manifest_sha256"] == R.manifest_sha256(fx.manifest)
        for p in d.iterdir():
            assert not (p.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)), p.name
        R.require_complete(d)
        before = posts(svc)  # a second run is refused even with a fresh valid authorisation, and so is reusing the first one
        assert cli(fx, svc, "run", run_id="run-2", approval=fx.authorization("run-2")) == 1 and "one shot only" in capsys.readouterr().out
        assert cli(fx, svc, "run", approval=auth) == 1
        assert posts(svc) == before
        assert [json.loads(x)["event"] for x in (fx.runs / "LEDGER.jsonl").read_text().splitlines()] == ["START", "COMPLETE"]
        assert S.run_cli(fx, svc.port, ["inspect", "--manifest", str(fx.manifest_path), "--runs-root", str(fx.runs)]) == 0 and '"state": "COMPLETE"' in capsys.readouterr().out
    never_formal()


def finish(fx, svc, labels_flip=0, c6_answer="SUPPORTS", reconcile=True):
    """packets -> synthetic reviewers -> evaluate, all through the CLI."""
    d = fx.runs / "run-1"
    assert cli(fx, svc, "packets", extra=["--run-dir", str(d)]) == 0
    rev = fx.runs / "run-1-review"
    cand = R.read_jsonl(d / "candidate_rows.jsonl")
    a, b = fx.reviewer_labels(rev, cand), fx.reviewer_labels(rev, cand, flip=labels_flip)
    ca, cb = fx.c6_answers(rev, answer=c6_answer), fx.c6_answers(rev, answer=c6_answer)
    files = {}
    for name, obj in (("la", a), ("lb", b), ("lr", a), ("ca", ca), ("cb", cb)):
        files[name] = fx.work / f"{name}.json"
        files[name].write_text(json.dumps(obj))
    extra = ["--run-dir", str(d), "--p0-labels-a", str(files["la"]), "--p0-labels-b", str(files["lb"]), "--c6-answers-a", str(files["ca"]), "--c6-answers-b", str(files["cb"])]
    if reconcile:
        extra += ["--p0-labels-reconciled", str(files["lr"])]
    assert cli(fx, svc, "evaluate", extra=extra) == 0
    return json.loads((fx.runs / "run-1-report" / "report.json").read_text())


def run_once(fx, svc):
    assert cli(fx, svc, "run", approval=fx.authorization("run-1")) == 0


def statuses(rep, variant="reviewer_A"):
    return {c["number"]: c["status"] for c in rep["variants"][variant]["criteria"]}


def test_aggregation_all_pass_with_two_reviewers_above_the_target_and_the_adjudicated_citation_gate(tmp_path):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx) as svc:
        run_once(fx, svc)
        rep = finish(fx, svc, labels_flip=4)
    assert rep["agreement"]["kappa"] >= 0.80 and rep["variants"]["reviewer_A"]["independence_threshold_met"] is True
    for v in ("reviewer_A", "reviewer_B", "reconciled"):
        assert rep["variants"][v]["overall"] == "ACCEPTED" and set(statuses(rep, v).values()) == {"PASS"}, (v, statuses(rep, v))
    c6 = rep["criterion6"]
    assert c6["mechanical_fraction"] < 0.95 and c6["mechanical_would_pass"] is False and c6["credited_by_adjudication"] == 8 and c6["adjudicated_fraction"] == 1.0  # both figures kept
    six = next(c for c in rep["variants"]["reviewer_A"]["criteria"] if c["number"] == 6)
    assert six["mechanical"]["would_pass"] is False and six["adjudicated"]["credited_by_adjudication"] == 8 and six["gating"] == "adjudicated"
    nine = next(c for c in rep["variants"]["reviewer_A"]["criteria"] if c["number"] == 9)["coverage"]
    assert nine["independent_opportunities"] == 30 and nine["bound_verified"]["agrees"] is True
    out = tmp_path / "runs" / "run-1-report"  # the independent label files were copied and hashed BEFORE the agreement or the reconciliation existed
    assert set(rep["independent_label_hashes"]) == {"p0_labels_A", "p0_labels_B", "c6_answers_A", "c6_answers_B"} and (out / "independent_labels.sha256").exists()
    assert rep["identical_label_files_warning"] is False
    never_formal()


def test_aggregation_indeterminate_when_there_are_too_few_independent_opportunities(tmp_path):
    fx = S.new_fixture(tmp_path, "thin")
    with S.MockService(fx) as svc:
        run_once(fx, svc)
        rep = finish(fx, svc, labels_flip=3)
    st = statuses(rep)
    assert st[7] == st[8] == st[9] == "INDETERMINATE" and rep["variants"]["reviewer_A"]["overall"] == "NOT ESTABLISHED"
    c = next(x for x in rep["variants"]["reviewer_A"]["criteria"] if x["number"] == 8)
    assert c["coverage"]["independent_opportunities"] == 10 and c["coverage"]["independent_opportunities_needed"] == 29 and "INSUFFICIENT INDEPENDENT OPPORTUNITIES" in c["why"]
    never_formal()


def test_aggregation_fail_when_the_candidate_resolves_a_conflict(tmp_path):
    fx = S.new_fixture(tmp_path, "bad")
    with S.MockService(fx) as svc:
        run_once(fx, svc)
        rep = finish(fx, svc, labels_flip=3)
    assert statuses(rep)[7] == "FAIL" and rep["variants"]["reviewer_A"]["overall"] == "REJECTED"
    never_formal()


def test_reviewer_agreement_below_the_target_leaves_the_baseline_relative_criteria_not_established(tmp_path):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx) as svc:
        run_once(fx, svc)
        rep = finish(fx, svc, labels_flip=70)
    assert rep["agreement"]["kappa"] < 0.80
    st = statuses(rep)
    assert {st[n] for n in (1, 2, 3, 4, 10)} == {"INDETERMINATE"} and rep["variants"]["reviewer_A"]["independence_threshold_met"] is False and rep["variants"]["reviewer_A"]["overall"] == "NOT ESTABLISHED"


def test_an_unresolvable_citation_answer_leaves_criterion_six_unresolved_not_credited(tmp_path):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx) as svc:
        run_once(fx, svc)
        rep = finish(fx, svc, labels_flip=4, c6_answer="UNRESOLVABLE")
    c6 = rep["criterion6"]
    assert c6["credited_by_adjudication"] == 0 and c6["unresolved"] == 8 and c6["status"] == "INDETERMINATE" and c6["adjudicated_fraction"] == c6["mechanical_fraction"]


# -- fail-closed behaviour at the command line ------------------------------------------------------------------------------------------------------------------------------------------------

def refused_run(fx, svc, capsys, run_id):
    rc = cli(fx, svc, "run", run_id=run_id, approval=fx.authorization(run_id))
    return rc, capsys.readouterr().out


def test_git_errors_missing_files_a_moved_head_and_a_dirty_tree_all_refuse_and_call_nothing(tmp_path, capsys):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx) as svc:
        (fx.root / "evaluator.txt").write_text("tampered")
        rc, out = refused_run(fx, svc, capsys, "r1")
        assert rc == 1 and "hash mismatch" in out and "tracked file changed" in out
        (fx.root / "evaluator.txt").write_text("placeholder for evaluator\n")
        (fx.root / "scoring.txt").unlink()
        rc, out = refused_run(fx, svc, capsys, "r2")
        assert rc == 1 and "file missing" in out
        S.sh("checkout", "--", "scoring.txt", cwd=fx.root)
        S.sh("commit", "--allow-empty", "-q", "-m", "moves HEAD", cwd=fx.root)
        rc, out = refused_run(fx, svc, capsys, "r3")
        assert rc == 1 and "not the manifest commit" in out
        S.sh("reset", "--hard", "-q", fx.commit, cwd=fx.root)
        os.rename(fx.root / ".git", fx.root / ".git.hidden")
        rc, out = refused_run(fx, svc, capsys, "r4")
        assert rc == 1 and "repository state cannot be read" in out
        os.rename(fx.root / ".git.hidden", fx.root / ".git")
        assert svc.requests == [] and not list(fx.runs.glob("run-*"))
        assert (fx.runs / "REFUSALS.jsonl").exists()  # each refusal is logged
        assert cli(fx, svc, "run", run_id="ok", approval=fx.authorization("ok")) == 0  # nothing above consumed the manifest: it still runs once, cleanly
    never_formal()


def test_a_rehearsal_can_neither_use_an_acceptance_authorisation_nor_write_to_the_formal_directory(tmp_path, capsys):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx) as svc:
        real_like = fx.authorization("run-1", purpose=R.PURPOSE_ACCEPTANCE)
        before = real_like.read_text()
        rc = cli(fx, svc, "run", approval=real_like)
        out = capsys.readouterr().out
        assert rc == 1 and "can never use each other's authorisation" in out and real_like.read_text() == before
        assert not (fx.runs / "LEDGER.jsonl").exists() and svc.requests == []  # the acceptance authorisation was not consumed
        auth = fx.authorization("run-1")
        rc = S.run_cli(fx, svc.port, ["run", *S.common(fx), "--runs-root", str(R.FORMAL_RUNS_DIR), "--run-id", "run-1", "--execute"], approval=auth)
        assert rc == 1 and "may never write to the formal acceptance output directory" in capsys.readouterr().out
        assert svc.requests == []
        never_formal()
        m = dict(fx.manifest, purpose=R.PURPOSE_ACCEPTANCE)  # and the other way round: an acceptance manifest cannot run anywhere but the formal directory
        (fx.work / "acc.json").write_text(R.canonical(m))
        a = fx.work / "acc-auth.json"
        a.write_text(json.dumps({"decision": R.AUTH_DECISION, "manifest_sha256": R.manifest_sha256(m), "run_id": "x", "authorized_by": "t", "single_use": True, "p0_model_calls_authorized": True, "purpose": R.PURPOSE_ACCEPTANCE,
                                 "expires_at": "2099-01-01T00:00:00+00:00"}))
        rc = S.run_cli(fx, svc.port, ["run", "--manifest", str(fx.work / "acc.json"), "--root", str(fx.root), "--runs-root", str(fx.runs), "--run-id", "x", "--execute"], approval=a)
        assert rc == 1 and "a formal acceptance must write to" in capsys.readouterr().out and svc.requests == []
    never_formal()


def test_the_p0_adapter_refuses_any_target_other_than_the_disposable_mock(tmp_path):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx) as svc, S.MockService(fx) as other:
        ex = P0.RealP0Executor(fx.root / "corpus.json", llm_factory=lambda: S.local_client(other.port), preparer_factory=lambda llm: S.SynthPreparer(), rehearsal_mock_port=svc.port)
        with pytest.raises(RuntimeError, match="rehearsal refused"):
            ex.open()
        assert other.requests == [] and svc.requests == []  # refused before a single request
        ex2 = P0.RealP0Executor(fx.root / "corpus.json", llm_factory=lambda: S.local_client(svc.port), preparer_factory=lambda llm: S.SynthPreparer(), rehearsal_mock_port=svc.port)
        ex2.open()
        row = ex2.run_case(fx.cases[0])
        ex2.close()
        assert row["arm"] == "P0" and row["reply"] == fx.p0_reply(fx.cases[0]) and ("GET", "/v1/models") in svc.requests


def test_a_service_that_serves_the_wrong_model_aborts_the_run_before_any_case(tmp_path, capsys):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx, models=("some-other-model",)) as svc:
        rc = cli(fx, svc, "run", approval=fx.authorization("run-1"))
        assert rc == 3 and "ABORTED" in capsys.readouterr().out and posts(svc) == 0
        assert "is not served" in json.loads((fx.runs / "run-1" / "failure.json").read_text())["error"]


def test_a_service_failure_mid_run_aborts_keeps_flushed_rows_and_forbids_a_rerun(tmp_path, capsys):
    fx = S.new_fixture(tmp_path, "good")
    with S.MockService(fx, fail_after=40) as svc:
        assert cli(fx, svc, "run", approval=fx.authorization("run-1")) == 3
        assert "ABORTED" in capsys.readouterr().out
        d = fx.runs / "run-1"
        assert json.loads((d / "STATE.json").read_text())["state"] == "ABORTED" and len(R.read_jsonl(d / "p0_rows.jsonl")) == 40
        assert "traceback" in json.loads((d / "failure.json").read_text()) and not (d / "ARTIFACTS.sha256").exists()
        assert cli(fx, svc, "run", run_id="run-2", approval=fx.authorization("run-2")) == 1 and "one shot only" in capsys.readouterr().out
        with pytest.raises(R.RunRefused):
            R.require_complete(d)
    never_formal()


def test_a_killed_process_leaves_flushed_partial_rows_a_lock_and_no_resume(tmp_path, capsys):
    fx = S.new_fixture(tmp_path, "good")
    auth = fx.authorization("run-1")
    with S.MockService(fx, stall_on=31) as svc:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
        child = subprocess.Popen([sys.executable, str(SEL / "dev16_synthetic.py"), "child", str(tmp_path), str(svc.port), "run-1", str(auth)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert svc.stalled.wait(120), child.communicate(timeout=5)
            os.kill(child.pid, signal.SIGKILL)  # no finally blocks, no atexit: a real crash
            child.wait(timeout=30)
        finally:
            if child.poll() is None:
                child.kill()
        d = fx.runs / "run-1"
        time.sleep(0.2)
        st = json.loads((d / "STATE.json").read_text())
        assert st["state"] == "P0_RUNNING" and st["completed"] == 30 and len(R.read_jsonl(d / "p0_rows.jsonl")) == 30  # every completed row was on disk when the process died
        assert (d / "provenance.json").exists() and not (d / "ARTIFACTS.sha256").exists() and not (d / "failure.json").exists()
        assert cli(fx, svc, "run", run_id="run-2", approval=fx.authorization("run-2")) == 1 and "one shot only" in capsys.readouterr().out
        assert S.run_cli(fx, svc.port, ["inspect", "--manifest", str(fx.manifest_path), "--runs-root", str(fx.runs)]) == 0
        info = json.loads(capsys.readouterr().out)
        assert info["lock"] and info["runs"] == [{"dir": "run-1", "state": "P0_RUNNING", "terminal": False}]
        with pytest.raises(R.RunRefused):
            R.require_complete(d)
    never_formal()


# -- environment hygiene and the dev16 boundary -----------------------------------------------------------------------------------------------------------------------------------------------

def test_load_world_restores_kbench_corpus_whether_or_not_it_was_set(monkeypatch):
    corpus = SEL / "corpus_v4.json"
    monkeypatch.delenv("KBENCH_CORPUS", raising=False)
    CA.load_world(corpus)
    assert "KBENCH_CORPUS" not in os.environ
    monkeypatch.setenv("KBENCH_CORPUS", "/previous/value.json")
    CA.load_world(corpus)
    assert os.environ["KBENCH_CORPUS"] == "/previous/value.json"


def test_the_p0_executor_restores_the_corpus_variable_it_set(monkeypatch):
    ex = P0.RealP0Executor(SEL / "corpus_v4.json")
    monkeypatch.setenv("KBENCH_CORPUS", "/previous/value.json")
    ex._env_before, ex._env_set = "/previous/value.json", True
    os.environ["KBENCH_CORPUS"] = "/during/run.json"
    ex.close()
    assert os.environ["KBENCH_CORPUS"] == "/previous/value.json"
    ex2 = P0.RealP0Executor(SEL / "corpus_v4.json")
    ex2.close()  # never opened: touches nothing
    assert os.environ["KBENCH_CORPUS"] == "/previous/value.json"


def test_no_synthetic_or_runner_source_names_a_dev16_file():
    for name in ("dev16_synthetic", "dev16_runner", "dev16_p0", "dev16_candidate_arm", "dev16_criteria", "dev16_criterion6"):
        text = (SEL / f"{name}.py").read_text()
        assert "cases_dev16" not in text and "bank_d" not in text.lower(), name
