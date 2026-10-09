"""The blind-review workflow for the 21 Phase 44E answers: the sheet reveals no condition, case id or score; the key is created outside the package with mode 0600 and a committed seal;
unsealing refuses incomplete ratings and a tampered key. Built on a throwaway package in a temporary directory from the stored first-look results; the real answer key is never opened
(only its hash is compared with the committed seal)."""

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

AQ = Path(__file__).resolve().parents[1] / "benchmarks" / "answer_quality"
RESULTS = AQ / "results" / "holdout-44E-first-look.json"
REAL = AQ / "blind_review" / "phase-44e"
LEAKS = re.compile(r"\b(b1a|b1b|b1a_nopre|b1b_nopre|oracle|p43|distractor|none)\b|\bB-[A-Z]\d\b|correctness|\bfull\b|\bpartial\b", re.IGNORECASE)


def item_leaks(sheet: str) -> list[str]:
    body = re.sub(r"\(no evidence was given to the assistant\)", "", "\n".join(sheet.split("## R")[1:]))
    return [m.group(0) for m in LEAKS.finditer(body) if m.group(0).lower() not in ("none", "full")]


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(AQ / script), *args], capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    root = tmp_path_factory.mktemp("blind")
    out, keys = root / "pkg", root / "keys"
    done = run("blind_package.py", "--run", str(RESULTS), "--out", str(out), "--key-dir", str(keys))
    assert done.returncode == 0, done.stderr
    return out, keys / "KEY-do-not-open-until-rated.json"


def test_the_sheet_has_twenty_one_items_and_reveals_no_condition_case_or_score(package):
    out, _ = package
    sheet = (out / "sheet.md").read_text()
    assert len(re.findall(r"^## R\d\d$", sheet, re.MULTILINE)) == 21
    assert item_leaks(sheet) == []  # no system name, case id or score word in any item


def test_the_key_is_outside_the_package_private_and_sealed(package):
    out, key = package
    assert not list(out.glob("KEY-*.json")) and key.exists() and oct(key.stat().st_mode & 0o777) == "0o600"
    assert (out / "KEY.sha256").read_text().strip() == hashlib.sha256(key.read_bytes()).hexdigest()
    items = json.loads(key.read_text())["items"]
    assert len(items) == 21 and {v["condition"] for v in items.values()} >= {"b1a", "b1b", "oracle"}


def ratings_file(path: Path, complete: bool) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item"] + [f"q{i}" for i in range(1, 9)])
        for n in range(1, 22):
            row = [f"R{n:02d}", "yes", "yes", "no", "not applicable", "no", "no", "yes", "yes"]
            if not complete and n == 7:
                row[3] = ""
            w.writerow(row)
    return path


def test_unsealing_refuses_incomplete_ratings_without_opening_the_key(package, tmp_path):
    out, key = package
    done = run("blind_compare.py", "--dir", str(out), "--ratings", str(ratings_file(tmp_path / "r.csv", complete=False)), "--key", str(key))
    assert done.returncode != 0 and "R07" in (done.stderr + done.stdout) and "sealed" in (done.stderr + done.stdout)


def test_a_key_that_no_longer_matches_its_seal_is_refused(package, tmp_path):
    out, key = package
    tampered = tmp_path / "KEY.json"
    tampered.write_text(key.read_text().replace("b1a", "b1b", 1))
    done = run("blind_compare.py", "--dir", str(out), "--ratings", str(ratings_file(tmp_path / "r.csv", complete=True)), "--key", str(tampered))
    assert done.returncode != 0 and "seal" in (done.stderr + done.stdout)


def test_complete_ratings_unseal_and_compare_every_item(package, tmp_path):
    out, key = package
    done = run("blind_compare.py", "--dir", str(out), "--ratings", str(ratings_file(tmp_path / "r.csv", complete=True)), "--key", str(key))
    assert done.returncode == 0 and "Agreement on correctness" in done.stdout and done.stdout.count("| R") == 21


def test_the_real_package_is_sealed_the_key_lives_outside_the_repository_and_matches_its_seal():
    key = Path.home() / ".local/share/reachy-blind-review/phase-44e/KEY-do-not-open-until-rated.json"
    assert not list(REAL.glob("KEY-*.json"))  # nothing but the seal travels with the package
    if key.exists():  # only the hash is compared: the key is never opened by a test
        assert hashlib.sha256(key.read_bytes()).hexdigest() == (REAL / "KEY.sha256").read_text().strip()
        assert oct(key.stat().st_mode & 0o777) == "0o600"
    sheet = (REAL / "sheet.md").read_text()
    assert len(re.findall(r"^## R\d\d$", sheet, re.MULTILINE)) == 21 and "KEY.sha256" not in sheet


def test_an_item_with_an_attached_meeting_names_it_so_a_wrong_meeting_answer_can_be_seen(package):
    out, _ = package
    sheet = (out / "sheet.md").read_text()
    assert re.search(r'the meeting "(Harbor planning|Lantern review|Weekly sync)" was attached', sheet) and "; a meeting was attached" not in sheet


def test_finalizing_helper_shows_no_system_names_and_merges_overrides_without_touching_the_submitted_ratings(tmp_path):
    submitted = REAL / "ratings-submitted-2026-10-10.csv"
    before = submitted.read_bytes()
    (tmp_path / "sheet.md").write_text((REAL / "sheet.md").read_text())
    done = run("blind_finalize.py", "sheet", "--dir", str(tmp_path), "--ratings", str(submitted), "--out", str(tmp_path / "c.md"))
    assert done.returncode == 0, done.stderr
    text = (tmp_path / "c.md").read_text()
    assert len(re.findall(r"^## R\d\d$", text, re.MULTILINE)) == 21
    assert not re.search(r"\b(b1a|b1b|oracle|p43)\b|\bB-[A-Z]\d\b", text, re.IGNORECASE)  # no system name or case id (a rater's own word such as "distractor" is theirs)
    (tmp_path / "owner.csv").write_text("item,q1_owner,q8_owner,note\nR02,partly,,wrong meeting\nR05,accept,with checks,\n")
    merged = run("blind_finalize.py", "merge", "--dir", str(tmp_path), "--ratings", str(submitted), "--owner", str(tmp_path / "owner.csv"), "--out", str(tmp_path / "final.csv"))
    assert merged.returncode == 0 and "R02" in merged.stdout and "R05" in merged.stdout
    final = {r["item"]: r for r in csv.DictReader((tmp_path / "final.csv").open())}
    assert final["R02"]["q1"].startswith("partly") and "wrong meeting" in final["R02"]["q1"] and final["R05"]["q8"].startswith("with checks")
    assert final["R03"]["q1"] == "yes" and len(final) == 21  # untouched items keep the submitted values
    bad = tmp_path / "bad.csv"
    bad.write_text("item,q1_owner,q8_owner,note\nR01,maybe,,\n")
    assert run("blind_finalize.py", "merge", "--dir", str(tmp_path), "--ratings", str(submitted), "--owner", str(bad), "--out", str(tmp_path / "x.csv")).returncode != 0
    assert submitted.read_bytes() == before  # the submitted ratings are never edited
