"""Evaluate the knowledge-query qualifier on the labelled utterances. Prints accuracy, precision, recall and every error.

    python qualify_eval.py --split dev        # while building the rules
    python qualify_eval.py --split test       # once, for the reported figures
Known terms come from the invented corpus (titles, people, projects), as the shadow would take them from the owner's records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aq import cases as caselib  # noqa: F401  (puts kbench on the path)
from companion_core.knowledge.qualify import (
    qualify,
    vocabulary_from_texts,
)
from kbench.fixtures import load_corpus

COMMON = {"about", "after", "again", "always", "because", "before", "being", "could", "every", "first", "found", "great", "other", "should", "still", "their", "there", "these", "thing", "things", "those", "through", "under", "until", "using", "where", "which", "while", "would", "write"}


def content_terms() -> frozenset[str]:
    """Titles and names plus the content words of the records' own text (a richer vocabulary: it catches domain questions with no record noun, and also
    lets a world question that happens to use a domain word through)."""
    c = load_corpus()
    texts = [m["text"] for m in c["memories"]] + [d["content"] for d in c["documents"]] + [n["body"] for n in c["notes"]] + [t["text"] for t in c["tasks"]]
    texts += [s["text"] for m in c["meetings"] if m["sensitivity"] != "sensitive" for s in m["segments"]]
    return vocabulary_from_texts(texts, stop=COMMON) | corpus_terms()


def rare_terms(max_records: int = 3) -> frozenset[str]:
    """Titles and names plus content words that occur in at most `max_records` of the owner's records: specific enough to anchor a question
    ("rollback", "benchmark") without letting frequent words like "time" or "model" make world questions look like record questions."""
    from collections import Counter

    c = load_corpus()
    texts = [m["text"] for m in c["memories"]] + [d["content"] for d in c["documents"]] + [n["body"] for n in c["notes"]] + [t["text"] for t in c["tasks"]]
    texts += [s["text"] for m in c["meetings"] if m["sensitivity"] != "sensitive" for s in m["segments"]]
    df: Counter = Counter()
    for t in texts:
        df.update({w for w in vocabulary_from_texts([t], stop=COMMON, limit=10**6)})
    return frozenset(w for w, n in df.items() if n <= max_records) | corpus_terms()


def corpus_terms() -> frozenset[str]:
    c = load_corpus()
    titles = [d["title"] for d in c["documents"]] + [m["title"] for m in c["meetings"]] + [n["title"] for n in c["notes"]]
    names = [e["name"] for e in c["entities"]] + [a for e in c["entities"] for a in e["aliases"]]
    return vocabulary_from_texts(titles + names, stop={"note", "weekly", "sync", "review", "vendor", "office", "wifi", "architecture"})


def adapter_terms() -> frozenset[str]:
    """The production function (`build_vocabulary`) over the invented corpus built into in-memory stores and read through the source adapters."""
    import asyncio

    from companion_core.knowledge.qualify import build_vocabulary
    from companion_core.knowledge.sources import build_adapters
    from kbench.corpus import build_corpus

    async def go():
        b = await build_corpus()
        return await build_vocabulary(build_adapters(memory=b.memory, documents=b.documents, meetings=b.meetings, planner=b.planner, tasks=b.tasks))

    return asyncio.run(go())


def evaluate(split: str, vocabulary: str = "titles") -> dict:
    cases = json.loads((HERE / "qualify_cases.json").read_text())[split]
    terms = {"titles": corpus_terms, "content": content_terms, "rare": rare_terms, "adapters": adapter_terms}[vocabulary]()
    tp = fp = tn = fn = 0
    errors = []
    for c in cases:
        q = qualify(c["text"], known_terms=terms)
        if q.qualifies and c["knowledge"]:
            tp += 1
        elif q.qualifies and not c["knowledge"]:
            fp += 1
            errors.append(("false_positive", c["text"], q.reasons))
        elif not q.qualifies and c["knowledge"]:
            fn += 1
            errors.append(("missed", c["text"], q.reasons))
        else:
            tn += 1
    n = len(cases)
    return {"split": split, "vocabulary": vocabulary, "n": n, "accuracy": round((tp + tn) / n, 3), "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None, "tp": tp, "fp": fp, "tn": tn, "fn": fn, "errors": errors}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=("dev", "test", "test2", "test3", "test4"), default="dev")
    p.add_argument("--vocabulary", choices=("titles", "content", "rare", "adapters"), default="titles")
    a = p.parse_args()
    r = evaluate(a.split, a.vocabulary)
    print(json.dumps({k: v for k, v in r.items() if k != "errors"}))
    for e in r["errors"]:
        print(e)
