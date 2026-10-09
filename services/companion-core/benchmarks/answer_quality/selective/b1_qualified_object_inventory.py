"""Inventory of every sentence the qualified-object rule rejects across all atoms of a world (dev15 or val17), to separate correct safety-driven withholding from over-strict rejection.
    python b1_qualified_object_inventory.py [--val17]   (no model; development data)"""
import collections
import contextlib
import io
import sys

import b1_dev15_check as h
import companion_core.knowledge.answerability_b1.admission as adm

sys.argv = [sys.argv[0], "--harness-fixes", "--structured", "--context", "--text", *[a for a in sys.argv[1:] if a == "--val17"]]
orig = adm._qualified_object
hits = collections.Counter()


def wrap(sentence, *a, **k):
    r = orig(sentence, *a, **k)
    if r:
        hits[sentence] += 1
    return r


adm._qualified_object = wrap
with contextlib.redirect_stdout(io.StringIO()):
    h.main()
print(len(hits), "distinct sentences rejected as qualified-object")
for s, n in sorted(hits.items()):
    print(f"{n:3d}  {s}")
