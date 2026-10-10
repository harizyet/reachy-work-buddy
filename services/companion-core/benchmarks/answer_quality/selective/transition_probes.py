"""Fresh synthetic probes for the changed wording and the explicit value transitions (Phase 44, final development pass, 2026-10-10). Written and frozen by hash (`TRANSITION_PROBES.sha256`) BEFORE the
review packet that renders them was built. Names are not in the invented corpus or in the unit tests; wordings differ from the test fixtures. dev16 and bank D were not used.

Each probe: records (ref, author, text), the question, and EXPECT = the state each answered or withheld part must have. The expected states are the contract (checked by `review_packet_b.py`, not the
wording); the wording is what the single-rater review reads.
"""
from __future__ import annotations

PROBES = [
    {"id": "T01", "q": "What is Bramble's default model?", "records": [("document:p1", "third_party", "As of September, the Bramble default model is Falcon-8B; the Wren-3B model has been retired.")], "expect": ["SUPPORTED"]},
    {"id": "T02", "q": "What was Bramble's default model before September?", "records": [("document:p1", "third_party", "As of September, the Bramble default model is Falcon-8B; the Wren-3B model has been retired.")], "expect": ["UNSUPPORTED"]},
    {"id": "T03", "q": "What was Bramble's default model before September?", "records": [("document:p1", "third_party", "As of September, the Bramble default model is Falcon-8B; the Wren-3B model has been retired."),
                                                                                         ("document:p2", "third_party", "As of June, the Bramble default model was Wren-3B.")], "expect": ["HISTORICAL"]},
    {"id": "T04", "q": "Which model does Pebble use by default?", "records": [("meeting:p3", "attendee", "We agreed to move the Pebble default model to Lynx-7B.")], "expect": ["UNSUPPORTED"]},
    {"id": "T05", "q": "Which model does Pebble use by default?", "records": [("note:p4", "owner", "The Pebble default model will be switched to Lynx-7B next quarter.")], "expect": ["UNSUPPORTED"]},
    {"id": "T06", "q": "Which model does Pebble use by default?", "records": [("note:p5", "owner", "The Pebble default model was switched from Wren-3B to Lynx-7B.")], "expect": ["SUPPORTED"]},
    {"id": "T07", "q": "What is Quill's default model?", "records": [("note:p6", "owner", "Quill rolled back its default model from Falcon-8B to Wren-3B.")], "expect": ["SUPPORTED"]},
    {"id": "T08", "q": "What is Quill's default model?", "records": [("document:p7", "third_party", "The Quill default model is Wren-3B."), ("note:p8", "owner", "As of October, the Quill default model is Falcon-8B; the Wren-3B model has been retired.")], "expect": ["CONFLICTED"]},
    {"id": "T09", "q": "Who is on call for Tern?", "records": [("note:p9", "owner", "Imani Okafor is on call for Tern this week.")], "expect": ["SUPPORTED"]},
    {"id": "T10", "q": "Who is on call for Tern?", "records": [("note:p9", "owner", "Imani Okafor is on call for Tern this week."), ("note:p10", "owner", "Imani Okafor is on call for Tern next week.")], "expect": ["UNSUPPORTED"]},
    {"id": "T11", "q": "Which day does Marten release, and who approved the Marten release?", "records": [("note:p11", "owner", "Marten releases every Wednesday."), ("note:p12", "owner", "Hana Sorensen approved the Marten release.")], "expect": ["SUPPORTED", "SUPPORTED"]},
    {"id": "T12", "q": "Who is the escalation contact for Heron-9B, and who owns the Dune gateway?", "records": [("note:p13", "owner", "Chidi Mbeki owns the Dune gateway.")], "expect": ["SUBJECT_TYPE_WITHHELD", "SUPPORTED"]},
    {"id": "T13", "q": "Who is the escalation contact for Marten, who is on call for Marten, and who owns the Dune gateway?", "records": [("note:p14", "owner", "Escalate serious Marten problems to Joon Park."), ("note:p13", "owner", "Chidi Mbeki owns the Dune gateway.")], "expect": ["SUPPORTED", "UNSUPPORTED", "SUPPORTED"]},
    {"id": "T14", "q": "What did Marten decide?", "records": [("meeting:p15", "attendee", "So the decision is to keep Lynx-7B as the default model.")], "expect": ["SUPPORTED"]},
]
