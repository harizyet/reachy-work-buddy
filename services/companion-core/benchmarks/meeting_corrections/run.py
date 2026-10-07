"""Benchmark transcript-correction approaches against cases.json.

    python run.py --base-url http://localhost:8001/v1 --model Qwen/Qwen2.5-7B-Instruct-AWQ

Approaches: `deterministic` (key terms only, no model), `resolver` (key terms + model choosing among candidates),
`scan` (model alone, free-form, no terms), `both` (resolver + scan, what the app runs). A suggestion counts as a hit
when it names the expected segment and replacement (original matched loosely); anything else is a false positive.
Cases marked `synthetic` were written for this benchmark; only `real` cases come from recordings."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
from companion_core.meetings import corrections as C
from companion_core.meetings.models import Meeting


def meeting_for(case: dict) -> Meeting:
    segments = [{"start": float(i), "end": float(i + 1), "text": line} for i, line in enumerate(case["transcript"])]
    return Meeting(title="Meeting", source_filename="f", content_type="c", audio_path="p", transcript_segments=segments,
                   key_terms=case["terms"])


def chat(client: httpx.Client, args, messages) -> str:
    body = {"model": args.model, "messages": messages, "temperature": 0, "max_tokens": args.max_tokens, **json.loads(args.extra_body)}
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    r = client.post(args.base_url + "/chat/completions", json=body, headers=headers, timeout=args.timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"].get("content") or ""


def run_case(client, args, case, approach):
    meeting = meeting_for(case)
    terms = C.collect_terms(meeting, [])
    found: list[C.Suggestion] = []
    if approach in ("deterministic", "resolver", "both"):
        candidates = C.find_term_candidates(meeting, terms)
        found += C.deterministic_suggestions(meeting, candidates)
        if approach != "deterministic":
            unresolved = [c for c in candidates if not c.spelling_variant]
            if args.resolver_mode == "single":
                for cand in unresolved:
                    term = C.parse_choice(chat(client, args, C.build_choice_messages(meeting, cand, terms)), cand)
                    if term:
                        found.append(C.suggestion_from_candidate(meeting, cand, term, confirmed_by="resolver"))
            else:
                pending = list(enumerate(unresolved))
                for k in range(0, len(pending), C.RESOLVER_BATCH):
                    batch = pending[k : k + C.RESOLVER_BATCH]
                    reply = chat(client, args, C.build_resolver_messages(meeting, batch, terms))
                    for number, term in C.parse_choices(reply, batch).items():
                        found.append(C.suggestion_from_candidate(meeting, dict(batch)[number], term, confirmed_by="resolver"))
    if approach in ("scan", "both"):
        for window in C.windows(meeting):
            found += C.parse_suggestions(chat(client, args, C.build_messages(meeting, window)), meeting)
    return found


def score(case, found):
    """Each expected correction counts once however many times it is suggested; duplicates are not false positives."""
    matched: set[int] = set()
    fp: set[tuple[int, str, str]] = set()
    for s in found:
        index = next(
            (
                n for n, e in enumerate(case["expected"])
                if e["segment"] == s.segment and e["suggested"].lower() == s.suggested.lower()
                and (e["original"].lower() in s.original.lower() or s.original.lower() in e["original"].lower())
            ),
            None,
        )
        if index is None:
            fp.add((s.segment, s.original.lower(), s.suggested.lower()))
        else:
            matched.add(index)
    forbidden = len({
        (s.segment, s.original.lower()) for s in found
        if any(f["segment"] == s.segment and f["original"].lower() in s.original.lower() for f in case["forbidden"])
    })
    return len(matched), len(case["expected"]) - len(matched), len(fp), forbidden


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--approaches", default="deterministic,resolver,scan,both")
    ap.add_argument("--max-tokens", type=int, default=600)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--resolver-mode", choices=["single", "batch"], default="single", help="single: one multiple-choice question per candidate (small models); batch: one JSON reply for ten candidates")
    ap.add_argument("--extra-body", default="{}", help='JSON merged into each request, e.g. \'{"chat_template_kwargs": {"enable_thinking": false}}\'')
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    cases = json.loads((Path(__file__).parent / "cases.json").read_text())
    print(f"model: {args.model}   cases: {len(cases)} ({sum(c['source'] == 'real' for c in cases)} real)")
    print(f"{'approach':14} {'recall':>7} {'precision':>9} {'F1':>5} {'FP':>4} {'forbidden':>9} {'seconds':>8}")
    with httpx.Client() as client:
        for approach in args.approaches.split(","):
            tp = fn = fp = bad = 0
            real_found = None
            started = time.time()
            for case in cases:
                try:
                    found = run_case(client, args, case, approach)
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    print(f"  {case['id']}: {approach} failed: {exc}")
                    fn += len(case["expected"])
                    continue
                h, m, f, b = score(case, found)
                if case["id"] == "real-gemini-germanite":
                    real_found = any(s.original.lower() == "germanite" and s.suggested == "Gemini" for s in found)
                tp, fn, fp, bad = tp + h, fn + m, fp + f, bad + b
                if args.verbose:
                    print(f"  [{approach}] {case['id']}: hit {h} miss {m} fp {f}", [(s.original, s.suggested) for s in found])
            recall = tp / max(tp + fn, 1)
            precision = tp / max(tp + fp, 1)
            f1 = 2 * recall * precision / max(recall + precision, 1e-9)
            print(f"{approach:14} {recall:7.2f} {precision:9.2f} {f1:5.2f} {fp:4d} {bad:9d} {time.time() - started:8.1f}"
                  f"   real germanite->Gemini: {'FOUND' if real_found else 'missed'}")


if __name__ == "__main__":
    main()
