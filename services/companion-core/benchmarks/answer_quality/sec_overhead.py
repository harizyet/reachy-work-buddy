"""Computational overhead of the coverage assessors, no model and no database: time per assessment of the item-level comparator, the section-level variant and the descriptor variant, on the gold or
distractor evidence of every DESIGN-set case (dev..dev7, dev9; never dev8 or dev10). Median and p95 microseconds over repeated runs."""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aq import cases as caselib
from companion_core.knowledge.sufficiency import assess
from companion_core.knowledge.sufficiency_section import assess_sections
from kbench.fixtures import load_corpus, source_meta, source_texts
from sufficiency_eval import pieces_for

corpus = load_corpus()
texts, meta = source_texts(corpus), source_meta(corpus)
work = []
for split in ("dev", "dev2", "dev3", "dev4", "dev5", "dev6", "dev7", "dev9"):
    for c in caselib.load_cases(split):
        work.append((c["question"], pieces_for(c["distractor_refs"] if c["abstain"] else c["gold_refs"], corpus, texts, meta)))
out = {"cases": len(work), "evidence_pieces_median": statistics.median(len(p) for _, p in work)}
for name, fn in (("item_level", assess), ("section", assess_sections), ("section_descriptors", lambda q, p: assess_sections(q, p, descriptors=True))):
    times = []
    for _ in range(20):
        for q, p in work:
            t = time.perf_counter()
            fn(q, p)
            times.append((time.perf_counter() - t) * 1e6)
    times.sort()
    out[name] = {"median_us": round(statistics.median(times), 1), "p95_us": round(times[int(0.95 * len(times)) - 1], 1), "max_us": round(times[-1], 1)}
print(json.dumps(out, indent=1))
(HERE / "results/section-overhead.json").write_text(json.dumps(out, indent=1))
