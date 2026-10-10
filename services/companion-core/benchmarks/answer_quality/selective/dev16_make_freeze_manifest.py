"""Build the dev16 acceptance manifest (Phase 44, final freeze command, prepared 2026-10-10; NOT YET RUN). A one-off helper: it is NOT one of the manifest's listed files, and the runner does not depend on it; its
output is the manifest, whose hash the owner records in the single-use authorisation.

THIS IS THE FIRST MOMENT A dev16 FILE IS HASHED AND PARSED (for its ordered case ids). Run it only after the owner's explicit freeze decision, at the freeze commit, with a clean tree. Seed 16044 is approved.

    python dev16_make_freeze_manifest.py <cases-path> <purpose> <output-dir> [<extra-file-path> ...]
        real freeze:  <cases-path>  services/companion-core/benchmarks/answer_quality/cases_dev16.json
                      <purpose>     dev16-acceptance
                      <output-dir>  services/companion-core/benchmarks/answer_quality/selective/dev16_acceptance_runs/FREEZE
                      extra paths   the bank D files, each hashed as an extra role (bank_0, bank_1, ...)
        rehearsal:    any consumed cases file, purpose `rehearsal`, an output directory outside dev16_acceptance_runs
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARGV = list(sys.argv)  # importing the frozen evaluation modules replaces sys.argv
sys.path.insert(0, str(HERE))
import dev16_freeze_proposal as fp
import dev16_runner as r

SEED = 16044  # approved prospectively by the owner


def main(cases: str, purpose: str, out: Path, extra: list[str]) -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=fp.REPO).stdout.strip()
    dirty = r.git_info(fp.REPO)["dirty_tracked"]
    if dirty:
        raise SystemExit(f"refusing to build a manifest with modified tracked files: {dirty}")
    files = dict(fp.ROLES)
    files["cases"] = cases
    files.update({f"bank_{i}": path for i, path in enumerate(extra)})
    manifest = r.build_manifest(fp.REPO, files, purpose=purpose, seed=SEED, commit=head, cases_path=cases)
    out.mkdir(parents=True, exist_ok=True)
    r.write_once(out / "manifest.json", r.canonical(manifest))
    return {"manifest": str(out / "manifest.json"), "manifest_sha256": r.manifest_sha256(manifest), "commit": head, "seed": SEED, "purpose": purpose, "cases": manifest["case_count"], "files": len(manifest["files"])}


if __name__ == "__main__":
    if len(ARGV) < 4:
        raise SystemExit(__doc__)
    print(main(ARGV[1], ARGV[2], Path(ARGV[3]), ARGV[4:]))
