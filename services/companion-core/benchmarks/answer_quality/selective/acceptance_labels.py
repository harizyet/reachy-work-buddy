"""Add rater labels (rater A) for the formal validation. Codes: S stated, I identified, F false_abstention, L leaked, V severe, W wrong_value, A absence_claim, O invented_order, B both, 1 one_sided, R resolved,
C as_current, N none; a trailing ? marks the item borderline (rubric v4). Usage: python acceptance_labels.py "Q1abc=LVO Q2def=I? ..." """
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "acceptance" / "labels_raterA.json"
CODE = {"S": "stated", "I": "identified", "F": "false_abstention", "L": "leaked", "V": "severe", "W": "wrong_value", "A": "absence_claim", "O": "invented_order", "B": "both", "1": "one_sided", "R": "resolved", "C": "as_current"}


def add(spec: str, notes: dict | None = None) -> int:
    data = json.loads(OUT.read_text()) if OUT.exists() else {"rater": "rater_A (the assistant that wrote the scorer; labelled from the blinded packet; NO INDEPENDENT HUMAN REVIEW)", "rubric": ["v2", "v3 addendum", "v4 addendum"], "labels": {}, "notes": {}}
    for tok in spec.split():
        k, _, codes = tok.partition("=")
        border = codes.endswith("?")
        codes = codes.rstrip("?")
        data["labels"][k] = {"flags": [] if codes in ("N", "") else [CODE[c] for c in codes], "unclear": False, "borderline": border}
    data["notes"].update(notes or {})
    OUT.write_text(json.dumps(data, indent=1))
    return len(data["labels"])


if __name__ == "__main__":
    print(add(" ".join(sys.argv[1:])))
