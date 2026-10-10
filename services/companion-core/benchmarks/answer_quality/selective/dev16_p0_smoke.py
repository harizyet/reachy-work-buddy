"""Development-only smoke test of the REAL P0 execution path (Phase 44, 2026-10-10). Consumed dev15 cases only; never dev16. This module only SELECTS and BUILDS the smoke fixture; the run itself is the
real acceptance runner (`dev16_runner.py run`) with a manifest of purpose `rehearsal`, so every guard of the one-shot path is exercised too.

Selection (fixed BEFORE execution, hashed, seed 16044): one dev15 case per question family, chosen by a seeded draw from the sorted ids of that family; plus two ACCESS-PROFILE VARIANTS of consumed cases
(same question, `access` changed to `shared_speaker` and `harbor_only`) to exercise access-context enforcement end to end. The variants are derived development fixtures, labelled as such by their ids.

    python dev16_p0_smoke.py select <output-dir>
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 16044
VARIANT_PROFILES = ("shared_speaker", "harbor_only")


def select(cases: list[dict]) -> tuple[list[dict], dict]:
    rnd = random.Random(SEED)
    chosen = []
    for family in sorted({c["family"] for c in cases}):
        ids = sorted(c["id"] for c in cases if c["family"] == family)
        pick = rnd.choice(ids)
        chosen.append(next(c for c in cases if c["id"] == pick))
    base = [c for c in chosen if c["family"] in ("control_supported", "mixed")]
    variants = [{**c, "id": f"{c['id']}-AX-{p}", "access": p} for c, p in zip(base, VARIANT_PROFILES, strict=True)]
    info = {"seed": SEED, "rule": "one case per family by a seeded draw over sorted ids; two derived access-profile variants of consumed cases", "cases": [c["id"] for c in chosen], "variants": [v["id"] for v in variants]}
    return chosen + variants, info


def main(out: Path) -> None:
    cases = json.loads((HERE.parent / "cases_dev15.json").read_text())["cases"]
    picked, info = select(cases)
    out.mkdir(parents=True)
    (out / "cases_smoke_dev15.json").write_text(json.dumps({"note": "development-only smoke fixture built from consumed dev15 cases", "cases": picked}, indent=1))
    info["cases_sha256"] = hashlib.sha256((out / "cases_smoke_dev15.json").read_bytes()).hexdigest()
    info["questions"] = {c["id"]: c["question"] for c in picked}
    (out / "SELECTION.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "select":
    main(Path(sys.argv[2]))
