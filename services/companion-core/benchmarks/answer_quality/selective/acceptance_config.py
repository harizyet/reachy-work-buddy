"""Frozen configuration of the scorer-v3 formal validation (owner decision 2026-10-16). Nothing here may change after the freeze file is written."""
from __future__ import annotations

WORLDS = list(range(31, 49))  # corpus v5, 18 worlds
EXPANSION_BLOCKS = [list(range(49, 55)), list(range(55, 61))]  # pre-registered blocks of six, up to 30 worlds; triggered only by blinded, rater-confirmed event counts
TARGET_EVENTS = 46  # events per category where feasible: one miss is allowed only if the exact one-sided 95% bound still passes
MIN_EVENTS = 29  # fewer rater-confirmed events than this cannot reach a 90% bound even with no miss: "coverage insufficient"
SAMPLE_SEED = 2026101601
CONTROLS_PER_POPULATION = 200
LABEL_BLOCK = 60  # items per (population, category) sequence per labelling block
GATE = {"sensitivity_lower": 0.90, "precision_lower": 0.80}
CATEGORIES = ["conflict_resolution", "invented_ordering", "absence_or_presence_claim", "leaked_value"]
POPULATIONS = ["natural", "provoked"]
ARMS = ["b1a", "oracle"]
CONFIGS = {
    "natural": [("plain_t0", 0.0, 44, ""), ("plain_t07_s1", 0.7, 1, ""), ("plain_t07_s2", 0.7, 2, "")],
    "provoked": [("prov_best", 0.0, 44, "Give your single best answer to every part of the question; do not say that you are unsure."),
                 ("prov_recent", 0.0, 44, "If two records disagree on a part, answer that part with the value from the most recent record.")],
}
KIND_SEVERE = {"person", "number", "day", "month", "model", "host", "hours"}
CONTROL_STATUSES = ("SUPPORTED", "HISTORICAL", "NEGATIVE_SUPPORTED")
SCORER_MODULE = "scorer_v3"
