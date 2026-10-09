"""Deterministic evaluation of the evidence-sufficiency assessor (no model, no database): for every development case, the verdict on the evidence a perfect retriever would give.
Answerable cases (the gold sources) should read "sufficient"; abstention cases (the authorised-but-irrelevant distractors) should not. The consumed holdout is never read here.

    python sufficiency_eval.py [--splits dev,dev2,...] [--show-errors]"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aq import cases as caselib
from companion_core.knowledge.sufficiency import Piece, assess
from kbench.fixtures import load_corpus, source_meta, source_texts

DEV_SPLITS = ("dev", "dev2", "dev3", "dev4", "dev5", "dev6")


def pieces_for(refs, corpus, texts, meta):
    out = []
    titles = {}
    for kind, key in (("document", "documents"), ("note", "notes"), ("meeting", "meetings")):
        for x in corpus[key]:
            titles[f"{kind}:{x['id']}"] = x.get("title", "")
    speakers = {m["id"]: m["speaker_names"] for m in corpus["meetings"]}
    segs = {m["id"]: m["segments"] for m in corpus["meetings"]}
    seen = set()
    for ref in refs:
        keys = [ref] if ref in texts else [k for k in texts if k.startswith(ref + "#")]
        for k in keys:
            if k in seen:
                continue
            seen.add(k)
            whole = k.split("#")[0]
            text = texts[k]
            if k.startswith("meeting:") and "#" in k:
                mid, i = k[8:].split("#")
                text = f"{speakers[mid].get(segs[mid][int(i)]['speaker'], '')}: {text}"
            out.append(Piece(text=text, title=titles.get(whole, ""), scope=meta[whole]["scope"] or ""))
    return out


def evaluate(splits, show):
    corpus = load_corpus()
    texts, meta = source_texts(corpus), source_meta(corpus)
    rows = []
    for split in splits:
        for c in caselib.load_cases(split):
            refs = c["distractor_refs"] if c["abstain"] else c["gold_refs"]
            a = assess(c["question"], pieces_for(refs, corpus, texts, meta))
            ok = (a.verdict != "sufficient") if c["abstain"] else (a.verdict == "sufficient")
            rows.append({"split": split, "id": c["id"], "category": c["category"], "abstain": c["abstain"], "verdict": a.verdict, "ok": ok, "q": c["question"], "a": a})
    for label, subset in (("design splits dev..dev5", [r for r in rows if r["split"] != "dev6"]), ("dev6", [r for r in rows if r["split"] == "dev6"])):
        ans = [r for r in subset if not r["abstain"]]
        ab = [r for r in subset if r["abstain"]]
        print(f"\n== {label}: {len(subset)} cases")
        print(f"answerable {len(ans)}: flagged insufficient (false gate) {sum(1 for r in ans if r['verdict'] != 'sufficient')} -> {dict(collections.Counter(r['verdict'] for r in ans))}")
        print(f"abstention {len(ab)}: correctly flagged {sum(1 for r in ab if r['verdict'] != 'sufficient')} -> {dict(collections.Counter(r['verdict'] for r in ab))}")
        for r in subset:
            if not r["ok"] and show:
                print(f"  MISS {r['id']:6} {'abstain ' if r['abstain'] else 'answer  '}{r['verdict']:16} {r['q']}  | absent={r['a'].absent_entities} unc={r['a'].uncovered_aspects} ents={r['a'].entities} asp={r['a'].aspects}")
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--splits", default=",".join(DEV_SPLITS))
    p.add_argument("--show-errors", action="store_true")
    p.add_argument("--out")
    args = p.parse_args()
    if "holdout" in args.splits:
        raise SystemExit("the consumed holdout is not used for development")
    rows = evaluate(args.splits.split(","), args.show_errors)
    if args.out:
        Path(args.out).write_text(json.dumps([{k: v for k, v in r.items() if k != "a"} for r in rows], indent=1))
