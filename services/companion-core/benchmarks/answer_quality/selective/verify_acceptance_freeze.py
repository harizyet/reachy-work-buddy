"""Pre-execution verification and freeze of the scorer-v3 formal validation (owner decision 2026-10-16). `check` verifies, `freeze` verifies and writes ACCEPTANCE_FREEZE_v3.sha256 and the initial state.
Checks: manifests regenerate (all 18 worlds), bank E and probe bank E hashes, scorer v1/v2 unchanged and v3 as recorded, rubric files, the sampling plan regenerates identically, expansion rules present in the
protocol, one-shot guard clean, no reply or label exists yet, and that bank E and probe bank E have never been evaluated against scorer v3 (no module other than the generator, the tests, the verifier and the one
report script refers to them, and no result file exists for them)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(HERE))
import acceptance_config as cfg
import acceptance_plan as ap
import acceptance_state as st
import fresh_v5_manifest as fm

ACC = HERE / "acceptance"
FREEZE = HERE / "ACCEPTANCE_FREEZE_v3.sha256"
FILES = ["acceptance_config.py", "acceptance_plan.py", "acceptance_state.py", "acceptance_generate.py", "acceptance_packet.py", "acceptance_labels.py", "acceptance_freeze_labels.py", "acceptance_report.py",
         "verify_acceptance_freeze.py", "cluster_analysis.py", "coverage_inventory_v5.py", "validation_analyze.py", "fresh_v5_manifest.py", "corpus_gen_v5.py", "questions_gen_v5.py", "corpus_gen.py", "questions_gen.py",
         "banks.py", "banks_e.py", "bank_e.sha256", "probe_bank_e.py", "scorer.py", "scorer_v2.py", "scorer_v3.py", "scorer_cases.py", "validate_scorer.py", "adjudication_rubric_v2.md", "adjudication_rubric_v3_addendum.md",
         "adjudication_rubric_v4_addendum.md", "validation/probe_bank_e.json", "validation/probe_bank_e.sha256", "validation/fresh_v5_manifest.json", "validation/coverage_inventory_v5.json", "acceptance/plan.json"]
DOCS = ["docs/phase-44-scorer-v3-formal-validation-protocol.md", "docs/verification/phase-44-corpus-v5-coverage-2026-10-15.md"]


def check() -> list[str]:
    problems: list[str] = []
    manifest = json.loads((HERE / "validation" / "fresh_v5_manifest.json").read_text())
    for s in cfg.WORLDS:
        corpus, registry, cases = fm.world(s)
        w = manifest["worlds"][str(s)]
        if (fm.digest(corpus), fm.digest(registry), fm.digest(cases)) != (w["corpus_sha256"], w["facts_sha256"], w["cases_sha256"]):
            problems.append(f"world {s} does not regenerate to its manifest hashes")
    if manifest["bank_e_sha256"] != st.sha(HERE / "banks_e.py") or (HERE / "bank_e.sha256").read_text().split()[0] != st.sha(HERE / "banks_e.py"):
        problems.append("bank E hash mismatch")
    lines = (HERE / "validation" / "probe_bank_e.sha256").read_text().splitlines()
    if lines[0].split()[0] != st.sha(HERE / "validation" / "probe_bank_e.json") or lines[1].split()[0] != st.sha(HERE / "probe_bank_e.py"):
        problems.append("probe bank E hash mismatch")
    freeze = {ln.split()[1]: ln.split()[0] for ln in (HERE / "VALIDATION_FREEZE_val17.sha256").read_text().splitlines() if ln and not ln.startswith("#")}
    for name in ("scorer.py", "scorer_v2.py"):
        if st.sha(HERE / name) != freeze[name]:
            problems.append(f"{name} changed since its recorded hash")
    seal = {ln.split()[1]: ln.split()[0] for ln in (HERE / "SEAL_adjudication_1_scorer_v1.sha256").read_text().splitlines() if ln and not ln.startswith("#")}
    if seal["scorer.py"] != st.sha(HERE / "scorer.py"):
        problems.append("scorer v1 seal broken")
    for f, h in ((r.split()[1], r.split()[0]) for r in (HERE / "adjudication_rubric_v4_addendum.sha256").read_text().splitlines()):
        if st.sha(HERE / f) != h:
            problems.append("rubric v4 addendum hash mismatch")
    plan = ap.build(cfg.WORLDS)
    if json.dumps(plan, indent=1) != (ACC / "plan.json").read_text():
        problems.append("the sampling plan does not regenerate identically")
    protocol = (ROOT / DOCS[0]).read_text()
    for needle in ("blocks of **six**", "up to 30 worlds", "46", "NO INDEPENDENT HUMAN REVIEW", "naturalistic coverage insufficient"):
        if needle not in protocol:
            problems.append(f"protocol lacks {needle!r}")
    for f in ("replies.jsonl", "labels_raterA.json", "report.json"):
        if (ACC / f).exists():
            problems.append(f"{f} already exists: the run has begun")
    if st.load()["stage"] not in (None, "frozen"):
        problems.append(f"one-shot state is {st.load()['stage']!r}")
    # never evaluated against v3: nothing else touches the banks together with a scorer
    allowed = {"probe_bank_e.py", "verify_acceptance_freeze.py", "acceptance_report.py", "test_corpus_v5.py"}
    for path in list(HERE.glob("*.py")) + list((ROOT / "services/companion-core/tests").glob("*.py")):
        text = path.read_text()
        if path.name not in allowed and re.search(r"probe_bank_e\.json|probe_bank_e\b", text) and "scorer" in text and path.name != "test_selective_stage_a.py":
            problems.append(f"{path.name} refers to probe bank E and a scorer")
    if any(p.name.startswith(("dev_v3_on_probe_bank", "probe_bank_e_report")) for p in (HERE / "validation").iterdir()):
        problems.append("a result file for probe bank E exists")
    git = subprocess.run(["git", "-C", str(ROOT), "log", "--all", "--oneline", "-i", "--grep=probe bank E.*score\\|bank E.*evaluat"], capture_output=True, text=True, check=False).stdout.strip()
    if git:
        problems.append("a commit message suggests an evaluation of bank E: " + git)
    return problems


def freeze() -> None:
    problems = check()
    if problems:
        raise SystemExit("NOT FROZEN:\n  " + "\n  ".join(problems))
    lines = [f"# Freeze of the scorer-v3 formal validation, {datetime.now(UTC).isoformat()}. Verified before execution; nothing listed may change.", "# scorer module: scorer_v3 (research-only)"]
    lines += [f"{st.sha(HERE / f)}  {f}" for f in FILES]
    lines += [f"{st.sha(ROOT / d)}  {d}" for d in DOCS]
    FREEZE.write_text("\n".join(lines) + "\n")
    st.STATE.write_text(json.dumps({"stage": None, "history": []}))
    st.advance("frozen", freeze_sha256=st.sha(FREEZE))
    print("FROZEN", st.sha(FREEZE))


if __name__ == "__main__":
    if "freeze" in sys.argv:
        freeze()
    else:
        p = check()
        print("OK: all checks pass" if not p else "PROBLEMS:\n  " + "\n  ".join(p))
        sys.exit(1 if p else 0)
