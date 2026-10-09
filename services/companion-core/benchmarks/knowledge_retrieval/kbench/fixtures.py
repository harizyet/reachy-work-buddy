"""Loading and validating the frozen fixtures. Pure functions over the JSON files; no stores, no retrieval."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from companion_core.meetings.corrections import current_text
from companion_core.meetings.models import Meeting
from companion_core.meetings.outputs import CONTEXT_TRANSCRIPT_CHARS, transcript_lines
from companion_core.rag.chunking import split_into_chunks

ROOT = Path(__file__).resolve().parent.parent
FILES = {"corpus": "corpus.json", "dev": "cases_dev.json", "holdout": "cases_holdout.json"}
CATEGORIES = (
    "single_source", "cross_source", "relationship", "temporal", "contradiction", "provenance", "security", "negative",
)
SOURCE_TYPES = ("memory", "document", "meeting", "note", "task", "reminder")
# The holdout must be large enough for the entity-expansion investigation rule (docs/phase-44.md D9).
HOLDOUT_MINIMUMS = {"cross_source": 10, "relationship": 10}


class FixtureError(ValueError):
    pass


def load_json(name: str) -> dict[str, Any]:
    return json.loads((ROOT / FILES[name]).read_text())


def load_corpus() -> dict[str, Any]:
    """The 44A corpus, or the file named by KBENCH_CORPUS (the groundedness milestone's invented corpus v2, same shape)."""
    override = os.environ.get("KBENCH_CORPUS")
    if override:
        return json.loads(Path(override).read_text())
    return load_json("corpus")


def load_cases(split: str) -> list[dict[str, Any]]:
    if split not in ("dev", "holdout"):
        raise FixtureError(f"unknown split {split!r}")
    return load_json(split)["cases"]


def fixture_hashes() -> dict[str, str]:
    """SHA-256 of each fixture file and a combined hash; a report names the fixtures it was produced from."""
    hashes = {name: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for name, file in FILES.items()}
    combined = hashlib.sha256("".join(hashes[n] for n in FILES).encode()).hexdigest()
    return {**hashes, "combined": combined}


def parse_ref(ref: str) -> tuple[str, str, str | None]:
    """"type:id[#locator]" (the SourceRef.key format) to its parts."""
    source_type, _, rest = ref.partition(":")
    source_id, _, locator = rest.partition("#")
    if source_type not in SOURCE_TYPES or not source_id:
        raise FixtureError(f"bad reference {ref!r}")
    return source_type, source_id, (locator or None)


def meeting_object(entry: dict[str, Any]) -> Meeting:
    """The Meeting a corpus entry describes, built exactly as the stores would hold it."""
    return Meeting(
        id=entry["id"], title=entry["title"], source_filename="f", content_type="c", audio_path="p",
        transcript_segments=[{k: v for k, v in s.items() if k != "speaker"} for s in entry["segments"]],
        diarization_segments=[{"start": s["start"], "end": s["end"], "speaker": s["speaker"]} for s in entry["segments"]],
        speaker_names=entry["speaker_names"], transcript_corrections=entry["corrections"],
    )


def source_texts(corpus: dict[str, Any]) -> dict[str, str]:
    """Reference key to the text a reader sees: document chunks, meeting segments (speaker names and accepted corrections
    applied), memories, notes, tasks and reminders. Whole-source keys are included for chunked sources."""
    texts: dict[str, str] = {}
    for item in corpus["memories"]:
        texts[f"memory:{item['id']}"] = item["text"]
    for doc in corpus["documents"]:
        chunks = split_into_chunks(doc["content"])
        for index, (_, chunk) in enumerate(chunks):
            texts[f"document:{doc['id']}#{index}"] = chunk
        texts[f"document:{doc['id']}"] = "\n\n".join(chunk for _, chunk in chunks)
    for entry in corpus["meetings"]:
        meeting = meeting_object(entry)
        lines = transcript_lines(meeting)
        for index in range(len(entry["segments"])):
            texts[f"meeting:{entry['id']}#{index}"] = current_text(meeting, index)
        texts[f"meeting:{entry['id']}"] = "\n".join(lines)
    for note in corpus["notes"]:
        texts[f"note:{note['id']}"] = f"{note['title']}\n{note['body']}"
    for task in corpus["tasks"]:
        texts[f"task:{task['id']}"] = task["text"]
    for reminder in corpus["reminders"]:
        texts[f"reminder:{reminder['id']}"] = reminder["text"]
    return texts


def source_meta(corpus: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Whole-source key ("type:id") to the access-relevant facts the authoritative record carries."""
    meta: dict[str, dict[str, Any]] = {}

    def add(kind: str, item: dict[str, Any], *, local_only: bool = False, forgotten: bool = False, expired: bool = False) -> None:
        meta[f"{kind}:{item['id']}"] = {
            "sensitivity": item.get("sensitivity", "work-private"), "scope": item.get("scope"),
            "local_only": local_only, "forgotten": forgotten, "expired": expired,
        }

    for m in corpus["memories"]:
        add("memory", m, forgotten=bool(m.get("forgotten")), expired=bool(m.get("expires")))
    for d in corpus["documents"]:
        add("document", d)
    for mt in corpus["meetings"]:
        add("meeting", mt, local_only=True)  # meeting speech never leaves the local models (ADR 0032)
    for n in corpus["notes"]:
        add("note", n)
    for t in corpus["tasks"]:
        add("task", t)
    for r in corpus["reminders"]:
        add("reminder", r)
    return meta


def validate_fixtures(corpus: dict[str, Any] | None = None, cases: dict[str, list[dict[str, Any]]] | None = None) -> list[str]:
    """Every problem found, or an empty list. Checks that the fixtures are internally consistent and that the questions can be
    answered from the corpus at all, so a failing retrieval system is never blamed for a broken case."""
    corpus = corpus or load_corpus()
    cases = cases or {"dev": load_cases("dev"), "holdout": load_cases("holdout")}
    problems: list[str] = []
    texts = source_texts(corpus)
    meta = source_meta(corpus)
    meeting_ids = {m["id"] for m in corpus["meetings"]}
    profiles = corpus["access_profiles"]

    for entry in corpus["meetings"]:
        if any(not str(s["text"]).strip() for s in entry["segments"]):
            problems.append(f"meeting {entry['id']}: empty segment text (line and segment indexes must agree)")
        speakers = {s["speaker"] for s in entry["segments"]}
        if not speakers <= set(entry["speaker_names"]):
            problems.append(f"meeting {entry['id']}: speakers without names {sorted(speakers - set(entry['speaker_names']))}")
    long_meetings = [m for m in corpus["meetings"] if sum(len(s) + 1 for s in transcript_lines(meeting_object(m))) > CONTEXT_TRANSCRIPT_CHARS]
    if not long_meetings:
        problems.append("no meeting is long enough to exercise Phase 43 excerpt selection")

    seen_ids: set[str] = set()
    seen_questions: dict[str, str] = {}
    for split, split_cases in cases.items():
        for case in split_cases:
            cid = case["id"]
            if cid in seen_ids:
                problems.append(f"{cid}: duplicate case id")
            seen_ids.add(cid)
            question = case["question"].strip().lower()
            if question in seen_questions:
                problems.append(f"{cid}: same question as {seen_questions[question]} (dev and holdout must not share questions)")
            seen_questions[question] = cid
            if case["category"] not in CATEGORIES:
                problems.append(f"{cid}: unknown category {case['category']!r}")
            if case["access"] not in profiles:
                problems.append(f"{cid}: unknown access profile {case['access']!r}")
            if case.get("attached_meeting") and case["attached_meeting"] not in meeting_ids:
                problems.append(f"{cid}: unknown attached meeting")
            if case["temporal"] not in ("current", "include_historical"):
                problems.append(f"{cid}: bad temporal mode")
            refs = [*case["expected_refs"], *case.get("stale_refs", []), *(f["ref"] for f in case.get("forbidden_refs", []))]
            for ref in refs:
                try:
                    parse_ref(ref)
                except FixtureError as exc:
                    problems.append(f"{cid}: {exc}")
                    continue
                if ref not in texts:
                    problems.append(f"{cid}: {ref} does not exist in the corpus")
            expected_text = " ".join(texts.get(r, "") for r in case["expected_refs"]).lower()
            for fact in case["expected_facts"]:
                if fact.lower() not in expected_text:
                    problems.append(f"{cid}: expected fact {fact!r} is not in the expected sources")
            if case["expected_refs"] and not case["expected_facts"]:
                problems.append(f"{cid}: expected sources but no expected facts")
            if case["category"] == "negative" and case["expected_refs"]:
                problems.append(f"{cid}: a negative case expects nothing")
            if case["category"] == "temporal" and case["temporal"] == "current" and not case.get("stale_refs"):
                problems.append(f"{cid}: a current-state case needs a stale reference")
            for ref in case["expected_refs"]:
                record = meta.get(ref.partition("#")[0], {})
                if record.get("forgotten") or record.get("expired"):
                    problems.append(f"{cid}: expects a forgotten or expired source {ref}")
            for canary in case.get("injection_canaries", []):
                if not any(canary.lower() in t.lower() for t in texts.values()):
                    problems.append(f"{cid}: canary {canary!r} appears nowhere in the corpus")
            if split == "holdout" and case["id"].startswith("D-"):
                problems.append(f"{cid}: development case id in the holdout")
            if split == "dev" and case["id"].startswith("H-"):
                problems.append(f"{cid}: holdout case id in the development set")
    counts: dict[str, int] = {}
    for case in cases["holdout"]:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    for category, minimum in HOLDOUT_MINIMUMS.items():
        if counts.get(category, 0) < minimum:
            problems.append(f"holdout has {counts.get(category, 0)} {category} cases; at least {minimum} are required")
    for field in ("memory", "document", "meeting", "note", "task", "reminder"):
        if not any(case_ref.startswith(field) for c in cases["holdout"] for case_ref in c["expected_refs"]):
            problems.append(f"no holdout case expects a {field} source")
    return problems
