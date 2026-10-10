"""Phase 44 acceptance infrastructure: the guarded one-shot runner (benchmarks/answer_quality/selective/dev16_runner.py). Synthetic fixtures only: tiny invented cases, a fake candidate arm and a fake P0
executor. No model call, no dev16 content, no frozen candidate involved."""

import importlib.util
import json
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SEL = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality" / "selective"


def _load(name):
    saved = list(sys.argv)
    sys.path[:0] = [str(SEL), str(SEL.parent)]
    try:
        spec = importlib.util.spec_from_file_location(name, SEL / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv[:] = saved
        del sys.path[:2]


R = _load("dev16_runner")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
P0_CFG = {"arm": "P0", "setting": 1}
CASES = [{"id": f"Q{i}", "family": "mixed", "question": f"q{i}", "atoms": []} for i in range(1, 4)]


class FakeP0:
    def __init__(self, cfg=None, fail_at=None, interrupt_at=None, touch=None):
        self.cfg, self.fail_at, self.interrupt_at, self.touch = cfg or P0_CFG, fail_at, interrupt_at, touch
        self.calls, self.opened, self.closed = [], False, False

    def effective_config(self):
        return dict(self.cfg)

    def open(self):
        self.opened = True

    def run_case(self, case):
        self.calls.append(case["id"])
        if self.fail_at == case["id"]:
            raise RuntimeError("server went away")
        if self.interrupt_at == case["id"]:
            raise KeyboardInterrupt
        if self.touch is not None:
            self.touch.write_text("changed during the run")
        return {"id": case["id"], "family": case["family"], "arm": "P0", "question": case["question"], "reply": f"reply {case['id']}", "manifest": {}, "ms": 1}

    def close(self):
        self.closed = True


def cand_arm(cases):
    return [{"id": c["id"], "family": c["family"], "arm": "deterministic", "question": c["question"], "reply": "x", "manifest": {}, "outcome": {"atoms": []}} for c in cases]


class Env:
    def __init__(self, tmp_path):
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.runs = tmp_path / "runs"
        files = {}
        for role in R.REQUIRED_ROLES:
            p = self.root / f"{role}.txt"
            p.write_text(f"content of {role}")
            files[role] = f"{role}.txt"
        (self.root / "cases.json").write_text(json.dumps({"cases": CASES}))
        files["cases"] = "cases.json"
        (self.root / "p0_config.txt").write_text(R.canonical(P0_CFG))
        self.commit = "a" * 40
        self.manifest = R.build_manifest(self.root, files, purpose="rehearsal", seed=7, commit=self.commit, cases_path="cases.json")
        self.mpath = tmp_path / "manifest.json"
        self.write_manifest()
        self.auth_n = 0

    def write_manifest(self):
        self.mpath.write_text(R.canonical(self.manifest))

    def auth(self, run_id="run-1", **over):
        self.auth_n += 1
        a = {"decision": R.AUTH_DECISION, "manifest_sha256": R.manifest_sha256(self.manifest), "run_id": run_id, "authorized_by": "owner", "authorized_at": NOW.isoformat(), "expires_at": (NOW + timedelta(days=1)).isoformat(),
             "single_use": True, "p0_model_calls_authorized": True, "purpose": "rehearsal", "n": self.auth_n}
        a.update(over)
        p = self.mpath.parent / f"auth-{self.auth_n}.json"
        p.write_text(json.dumps(a))
        return p

    def git(self, head=None, dirty=()):
        return lambda root: {"head": head or self.commit, "dirty_tracked": list(dirty)}

    def run(self, run_id="run-1", p0=None, arm=cand_arm, auth="default", execute=True, **kw):
        return R.execute(self.mpath, self.root, self.runs, run_id, p0_executor=p0 if p0 is not None else FakeP0(), candidate_arm=arm, authorization_path=self.auth(run_id) if auth == "default" else auth,
                         execute_flag=execute, now=NOW, git=kw.pop("git", self.git()), **kw)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def refused(env, **kw):
    with pytest.raises(R.RunRefused) as e:
        env.run(**kw)
    return e.value.problems


# -- the happy path and what it leaves behind ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_complete_run_leaves_immutable_artifacts_provenance_and_a_ledger(env):
    p0 = FakeP0()
    d = env.run(p0=p0)
    st = json.loads((d / "STATE.json").read_text())
    assert st["state"] == "COMPLETE" and st["completed"] == 3 and p0.opened and p0.closed
    assert [json.loads(x)["id"] for x in (d / "candidate_rows.jsonl").read_text().splitlines()] == ["Q1", "Q2", "Q3"]
    assert [json.loads(x)["id"] for x in (d / "p0_rows.jsonl").read_text().splitlines()] == ["Q1", "Q2", "Q3"]  # paired ids, in file order
    prov = json.loads((d / "provenance.json").read_text())
    assert prov["git"]["head"] == env.commit and prov["manifest_sha256"] == R.manifest_sha256(env.manifest) and prov["authorization_sha256"] and prov["mode"] == "rehearsal"
    for p in d.iterdir():
        assert not (p.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)), p.name
    events = [json.loads(x)["event"] for x in (env.runs / "LEDGER.jsonl").read_text().splitlines()]
    assert events == ["START", "COMPLETE"]
    R.require_complete(d)


def test_write_once_never_overwrites(tmp_path):
    p = tmp_path / "f"
    R.write_once(p, "a")
    with pytest.raises(FileExistsError):
        R.write_once(p, "b")
    assert p.read_text() == "a"


# -- hash, file and configuration guards: every one fails closed and calls nothing -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["evaluator", "scoring", "corpus", "cases", "candidate_manifest", "criterion6_rules", "runner"])
def test_a_hash_mismatch_in_any_frozen_file_refuses_before_anything_runs(env, role):
    p0 = FakeP0()
    (env.root / env.manifest["files"][role]["path"]).write_text("tampered")
    problems = refused(env, p0=p0)
    assert any("hash mismatch" in x and role in x for x in problems) and p0.calls == [] and not p0.opened
    assert not list(env.runs.glob("run-*")) and (env.runs / "REFUSALS.jsonl").exists()


def test_a_missing_file_a_missing_role_and_missing_manifest_fields_refuse(env):
    (env.root / env.manifest["files"]["scoring"]["path"]).unlink()
    assert any("file missing" in x for x in refused(env))
    del env.manifest["files"]["evaluator"]
    del env.manifest["seed"]
    env.write_manifest()
    problems = refused(env, run_id="run-2")
    assert any("required role 'evaluator'" in x for x in problems) and any("'seed'" in x for x in problems)


def test_head_not_the_manifest_commit_and_a_modified_tracked_listed_file_refuse(env):
    assert any("HEAD" in x for x in refused(env, git=env.git(head="b" * 40)))
    assert any("tracked file changed" in x for x in refused(env, run_id="run-2", git=env.git(dirty=["scoring.txt"])))
    env.run(run_id="run-3", git=env.git(dirty=["unrelated.md"]))  # a change to an unlisted file is not this guard's business


def test_the_case_population_must_match_the_manifest_count_and_ordered_ids(env):
    env.manifest["case_ids_sha256"] = "0" * 64
    env.write_manifest()
    assert any("population" in x for x in refused(env))
    env.manifest["case_ids_sha256"] = R.case_ids_sha256(CASES)
    env.manifest["case_count"] = 4
    env.write_manifest()
    assert any("population" in x for x in refused(env, run_id="run-2"))


def test_duplicate_case_ids_refuse(tmp_path):
    e = Env(tmp_path)
    dup = CASES + [CASES[0]]
    (e.root / "cases.json").write_text(json.dumps({"cases": dup}))
    e.manifest = R.build_manifest(e.root, {r: f["path"] for r, f in e.manifest["files"].items()}, purpose="rehearsal", seed=7, commit=e.commit, cases_path="cases.json")
    e.write_manifest()
    assert any("duplicate" in x for x in refused(e))


def test_a_failing_frozen_candidate_check_or_configuration_check_refuses(env):
    assert any("frozen candidate: relation definitions differ" in x for x in refused(env, candidate_check=lambda: ["relation definitions differ"]))
    assert any("P0 configuration differs" in x for x in refused(env, run_id="run-2", config_checks=lambda: ["P0 configuration differs at model"]))


def test_a_missing_baseline_or_a_p0_executor_with_another_configuration_refuses(env):
    with pytest.raises(R.RunRefused) as e:
        R.execute(env.mpath, env.root, env.runs, "run-1", p0_executor=None, candidate_arm=cand_arm, authorization_path=env.auth("run-1"), execute_flag=True, now=NOW, git=env.git())
    assert any("no P0 baseline executor" in x for x in e.value.problems)
    other = FakeP0(cfg={"arm": "P0", "setting": 2})
    problems = refused(env, run_id="run-2", p0=other)
    assert any("effective configuration differs" in x for x in problems) and other.calls == []


# -- the explicit, single-use execution authorisation ------------------------------------------------------------------------------------------------------------------------------------

def test_there_is_no_execution_without_the_flag_and_a_bound_authorisation(env):
    assert any("--execute" in x for x in refused(env, execute=False))
    assert any("no execution authorisation" in x for x in refused(env, run_id="run-2", auth=None))
    assert any("different manifest" in x for x in refused(env, run_id="run-3", auth=env.auth("run-3", manifest_sha256="0" * 64)))
    assert any("different run id" in x for x in refused(env, run_id="run-4", auth=env.auth("other")))
    assert any("expired" in x for x in refused(env, run_id="run-5", auth=env.auth("run-5", expires_at=(NOW - timedelta(seconds=1)).isoformat())))
    assert any("single_use" in x for x in refused(env, run_id="run-6", auth=env.auth("run-6", single_use=False)))
    assert any("p0_model_calls_authorized" in x for x in refused(env, run_id="run-7", auth=env.auth("run-7", p0_model_calls_authorized=False)))
    assert any("execution decision" in x for x in refused(env, run_id="run-8", auth=env.auth("run-8", decision="LOOKS_FINE")))
    assert not list(env.runs.glob("run-*"))


def test_an_authorisation_cannot_be_used_twice(env):
    a = env.auth("run-1")
    env.run(auth=a)
    env2 = env  # the same manifest cannot run again either, so test the authorisation guard directly on the ledger
    problems, _ = R.check_authorization(a, R.manifest_sha256(env2.manifest), "run-1", NOW, env2.runs / "LEDGER.jsonl")
    assert "this authorisation was already used" in problems


# -- one shot: no rerun, no overwrite, no resume -----------------------------------------------------------------------------------------------------------------------------------------------

def test_a_second_attempt_for_the_same_manifest_is_refused_even_with_a_fresh_authorisation(env):
    env.run()
    p0 = FakeP0()
    problems = refused(env, run_id="run-2", p0=p0)
    assert any("one shot only" in x for x in problems) and any("ledger already records" in x for x in problems) and p0.calls == []
    assert len(list(env.runs.glob("run-*"))) == 1


def test_an_existing_run_directory_is_never_reused(env):
    (env.runs / "run-1").mkdir(parents=True)
    assert any("already exists" in x for x in refused(env))


def test_an_interrupted_run_leaves_a_lock_and_cannot_be_resumed(env):
    d = env.runs / "run-9"
    d.mkdir(parents=True)
    (env.runs / f"LOCK-{R.manifest_sha256(env.manifest)[:16]}").mkdir()
    (d / "STATE.json").write_text(json.dumps({"state": "P0_RUNNING", "manifest_sha256": R.manifest_sha256(env.manifest), "completed": 1}))
    assert any("one shot only" in x for x in refused(env, run_id="run-10"))
    info = R.inspect_runs(env.runs, R.manifest_sha256(env.manifest))
    assert info["lock"] and info["runs"] == [{"dir": "run-9", "state": "P0_RUNNING", "terminal": False}]


# -- failure handling: abort, log, preserve --------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_failure_mid_run_aborts_the_whole_run_and_keeps_partial_outputs_and_a_failure_log(env):
    p0 = FakeP0(fail_at="Q2")
    with pytest.raises(R.RunAborted):
        env.run(p0=p0)
    d = env.runs / "run-1"
    st = json.loads((d / "STATE.json").read_text())
    assert st["state"] == "ABORTED" and "server went away" in st["error"] and p0.closed and p0.calls == ["Q1", "Q2"]
    fail = json.loads((d / "failure.json").read_text())
    assert "RuntimeError" in fail["traceback"] and "owner decision" in fail["rule"]
    assert len((d / "p0_rows.jsonl").read_text().splitlines()) == 1  # the partial output is preserved, not hidden
    assert not (d / "ARTIFACTS.sha256").exists()
    assert not ((d / "failure.json").stat().st_mode & stat.S_IWUSR)
    assert [json.loads(x)["event"] for x in (env.runs / "LEDGER.jsonl").read_text().splitlines()] == ["START", "ABORTED"]
    with pytest.raises(R.RunRefused):
        R.require_complete(d)  # an aborted run is never usable for acceptance
    assert any("one shot only" in x for x in refused(env, run_id="run-2"))


def test_a_keyboard_interrupt_aborts_records_and_propagates(env):
    with pytest.raises(KeyboardInterrupt):
        env.run(p0=FakeP0(interrupt_at="Q2"))
    assert json.loads((env.runs / "run-1" / "STATE.json").read_text())["state"] == "ABORTED"


def test_a_candidate_arm_failure_aborts_before_any_p0_call(env):
    p0 = FakeP0()

    def boom(cases):
        raise ValueError("planner crashed")

    with pytest.raises(R.RunAborted):
        env.run(p0=p0, arm=boom)
    assert p0.calls == [] and not p0.opened
    assert json.loads((env.runs / "run-1" / "STATE.json").read_text())["state"] == "ABORTED"


def test_candidate_rows_must_cover_the_frozen_cases_in_order(env):
    with pytest.raises(R.RunAborted):
        env.run(arm=lambda cases: list(reversed(cand_arm(cases))))
    assert "in order" in json.loads((env.runs / "run-1" / "failure.json").read_text())["error"]


def test_a_malformed_p0_row_aborts(env):
    class Bad(FakeP0):
        def run_case(self, case):
            row = super().run_case(case)
            row["reply"] = None
            return row

    with pytest.raises(R.RunAborted):
        env.run(p0=Bad())


def test_a_listed_file_changed_during_the_run_marks_it_invalid_and_unusable(env):
    p0 = FakeP0(touch=env.root / env.manifest["files"]["evaluator"]["path"])
    d = env.run(p0=p0)
    assert json.loads((d / "STATE.json").read_text())["state"] == "COMPLETE_BUT_INVALID"
    assert json.loads((d / "post_run_check.json").read_text())["problems"]
    with pytest.raises(R.RunRefused):
        R.require_complete(d)


def test_tampering_with_a_finished_artifact_is_detected(env):
    d = env.run()
    os.chmod(d, 0o755)
    os.chmod(d / "p0_rows.jsonl", 0o644)
    (d / "p0_rows.jsonl").write_text("{}")
    with pytest.raises(R.RunRefused) as e:
        R.require_complete(d)
    assert "changed after the run" in e.value.problems[0]


def test_dry_verification_checks_readiness_without_executing_or_logging(env):
    facts = R.preflight(env.mpath, env.root, env.runs, "run-1", p0_executor=FakeP0(), candidate_arm=cand_arm, authorization_path=None, execute_flag=False, dry=True, git=env.git())
    assert facts["manifest_sha256"] and not env.runs.exists()
    (env.root / "evaluator.txt").write_text("x")
    with pytest.raises(R.RunRefused):
        R.preflight(env.mpath, env.root, env.runs, "run-1", p0_executor=FakeP0(), candidate_arm=cand_arm, authorization_path=None, execute_flag=False, dry=True, git=env.git())
    assert not env.runs.exists()  # a dry verification logs nothing


# -- command line and the dev16 boundary ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_command_line_run_refuses_without_the_flag_and_the_approval_variable_and_calls_no_model(env, monkeypatch, capsys):
    monkeypatch.delenv(R.APPROVAL_ENV, raising=False)
    rc = R.main(["run", "--manifest", str(env.mpath), "--root", str(env.root), "--runs-root", str(env.runs), "--run-id", "run-1"])
    out = capsys.readouterr().out
    assert rc == 1 and "REFUSED" in out and "--execute was not given" in out and "no execution authorisation" in out
    assert not list(env.runs.glob("run-*"))


def test_the_command_line_inspect_reports_state(env, capsys):
    assert R.main(["inspect", "--manifest", str(env.mpath), "--runs-root", str(env.runs)]) == 0
    assert json.loads(capsys.readouterr().out) == {"lock": False, "runs": []}


def test_no_runner_module_or_config_names_a_dev16_file():
    for name in ("dev16_runner", "dev16_p0", "dev16_candidate_arm", "dev16_criteria", "dev16_criterion6", "dev16_freeze_proposal", "dev16_rehearsal"):
        text = (SEL / f"{name}.py").read_text()
        assert "cases_dev16" not in text and "bank_d" not in text.lower(), name
    for name in ("dev16_p0_config.json", "dev16_candidate_config.json", "dev16_criterion6_rules.json", "ACCEPTANCE_FREEZE_PROPOSAL.json"):
        assert "cases_dev16" not in (SEL / name).read_text(), name


def test_an_unreadable_repository_state_refuses_instead_of_crashing(env):
    def broken(root):
        raise OSError("no git")

    assert any("repository state cannot be read" in x for x in refused(env, git=broken))


def test_git_info_reports_every_dirty_tracked_path_including_the_first(tmp_path):
    import subprocess

    def g(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@invalid", *a], cwd=tmp_path, check=True, capture_output=True)

    g("init", "-q")
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "b.txt").write_text("1")
    g("add", "-A")
    g("commit", "-q", "-m", "x")
    (tmp_path / "a.txt").write_text("2")
    (tmp_path / "b.txt").write_text("2")
    (tmp_path / "untracked.txt").write_text("u")
    info = R.git_info(tmp_path)
    assert sorted(info["dirty_tracked"]) == ["a.txt", "b.txt"] and len(info["head"]) == 40
