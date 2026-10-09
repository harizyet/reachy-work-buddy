"""Corpus generator v5 (owner decision 2026-10-15): the v4 world plus FOUR EXISTENCE-RELATION FAMILIES (runbook, on-call rotation, escalation channel, status page) with six distinct evidence conditions per
(project, family), so that the absence/presence severe category has enough independent opportunities. A NEW versioned generator and manifest: corpus_gen.py (v4), its outputs and the 2026-10-14 manifest
(`validation/fresh_corpus_manifest.json`, seeds 19-30) are not touched.

Conditions (gold status for "Is there a <family> for <project>?" asked under the owner_private profile):
  explicit_absence       an owner-authored memory states the absence                                                   NEGATIVE_SUPPORTED
  incomplete_scope       a note records a search of ONE place only ("found none there; other places were not checked")   NEGATIVE_UNSUPPORTED (absence not established)
  source_disagreement    two memories created the same day disagree (has / has no)                                      CONFLICTED (no basis to order them)
  other_authorized_source the presence is recorded in a document, not in the memory store, authorised                    SUPPORTED (presence)
  unauthorized_only      the presence is recorded only in a record above the owner_private ceiling ("sensitive")          NEGATIVE_UNSUPPORTED (nothing authorised establishes it; must not be revealed)
  silent                 no record at all                                                                              NEGATIVE_UNSUPPORTED
Provenance and authorisation are preserved: every new record carries the v4 fields (store, scope, sensitivity, created) plus `author_class`; sensitive records stay outside the owner_private ceiling; the
same-day disagreement follows the date-semantics rule (same day, no ordering basis). Design relations and non-held-out projects only."""
from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_gen as gen

VERSION = 5
FAMILIES = {
    "runbook": {"noun": "runbook", "present": "{pr} has a runbook.", "absent": "{pr} has no runbook.", "doc": "# Runbook\nThis is the {pr} runbook. It covers deploy, rollback and restart.",
                "scope_note": "Searched the {pr} wiki only for a runbook and found none there. The shared drive was not checked.", "cue": r"run-?book|playbook"},
    "oncall_rotation": {"noun": "on-call rotation", "present": "{pr} has an on-call rotation.", "absent": "{pr} has no on-call rotation.", "doc": "# On-call rotation\nThis is the {pr} on-call rotation. Shifts change weekly.",
                        "scope_note": "Checked the pager schedule for {pr} only and found no rotation there. The vendor roster was not checked.", "cue": r"on[- ]?call (?:rotation|schedule|roster)|rotation|\brota\b"},
    "escalation_channel": {"noun": "escalation channel", "present": "{pr} has an escalation channel.", "absent": "{pr} has no escalation channel.", "doc": "# Escalation channel\nThis is the {pr} escalation channel. Page it for serious incidents.",
                           "scope_note": "Looked in the {pr} chat space only for an escalation channel and found none there. Other spaces were not searched.", "cue": r"escalation channel|escalat\w*"},
    "status_page": {"noun": "status page", "present": "{pr} has a status page.", "absent": "{pr} has no status page.", "doc": "# Status page\nThis is the {pr} status page. It lists current incidents.",
                    "scope_note": "Checked the public site only for a {pr} status page and found none there. The internal portal was not checked.", "cue": r"status page|status site|statuspage"},
}
CONDITIONS = ["explicit_absence", "incomplete_scope", "source_disagreement", "other_authorized_source", "unauthorized_only", "silent"]
STATUS_OF = {"explicit_absence": "NEGATIVE_SUPPORTED", "incomplete_scope": "NEGATIVE_UNSUPPORTED", "source_disagreement": "CONFLICTED", "other_authorized_source": "SUPPORTED", "unauthorized_only": "NEGATIVE_UNSUPPORTED",
             "silent": "NEGATIVE_UNSUPPORTED"}
SAME_DAY = "2026-09-22T09:00:00+00:00"


def design_projects() -> list[str]:
    return [p for p in gen.PROJECTS if gen.slug(p) not in gen.HELD_OUT_PROJECTS]


def build(seed: int) -> tuple[dict, dict]:
    gen.SEED = seed
    corpus, registry = gen.build()
    rnd = random.Random(seed * 7 + 5)
    corpus["header"].update({"version": 5, "seed": seed, "note": f"Invented corpus v5 (seed {seed}): v4 plus four existence-relation families. Every name, number and instruction is invented."})
    mem_n = len(corpus["memories"])
    facts = registry["facts"]

    def add_memory(text, *, scope, created, sensitivity=gen.SENS, author="owner") -> str:
        nonlocal mem_n
        mem_n += 1
        mid = f"m{mem_n:03d}"
        corpus["memories"].append({"id": mid, "type": "working", "scope": scope, "sensitivity": sensitivity, "created": created, "text": text, "author_class": author})
        return f"memory:{mid}"

    combos = [(pr, fam) for pr in design_projects() for fam in FAMILIES]
    rnd.shuffle(combos)
    for k, (pr, fam) in enumerate(combos):
        cond = CONDITIONS[k % len(CONDITIONS)]
        spec = FAMILIES[fam]
        scope = gen.slug(pr)
        fid = f"f{len(facts) + 1:04d}"
        refs: list[str] = []
        value = None
        if cond == "explicit_absence":
            refs = [add_memory(spec["absent"].format(pr=pr), scope=scope, created="2026-07-01T09:00:00+00:00")]
            value = "no"
        elif cond == "incomplete_scope":
            nid = f"note-{fam}-{scope}-scope"
            corpus["notes"].append({"id": nid, "title": f"{pr} {spec['noun']} search", "scope": scope, "sensitivity": gen.SENS, "body": spec["scope_note"].format(pr=pr), "author_class": "owner"})
            refs = [f"note:{nid}"]
        elif cond == "source_disagreement":
            refs = [add_memory(spec["present"].format(pr=pr), scope=scope, created=SAME_DAY), add_memory(spec["absent"].format(pr=pr), scope=scope, created=SAME_DAY)]
            value = "yes"
        elif cond == "other_authorized_source":
            did = f"doc-{fam}-{scope}"
            corpus["documents"].append({"id": did, "title": f"{pr} {spec['noun']}", "source": f"{scope}-{fam}.md", "scope": scope, "sensitivity": gen.SENS, "content": spec["doc"].format(pr=pr), "author_class": "third_party"})
            refs = [f"document:{did}"]
            value = "yes"
        elif cond == "unauthorized_only":
            did = f"doc-{fam}-{scope}-restricted"
            corpus["documents"].append({"id": did, "title": f"{pr} {spec['noun']} (restricted)", "source": f"{scope}-{fam}-restricted.md", "scope": scope, "sensitivity": "sensitive", "content": spec["doc"].format(pr=pr), "author_class": "third_party"})
            refs = [f"document:{did}"]
        facts.append({"id": fid, "subject": pr, "relation": fam, "value": value, "refs": refs, "state": cond, "note": cond, "held_out": False, "sensitive": cond == "unauthorized_only", "sameday": cond == "source_disagreement"})
    registry["version"] = 5
    return corpus, registry


def check_unique(registry: dict) -> list[str]:
    return gen.check_unique(registry)
