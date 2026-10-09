"""Freeze the rater labels: every (population, category) sequence must be done (event target reached or sequence exhausted) and every control labelled. Then the label file hash is recorded and the state moves to
'labels_frozen'. Expansion (pre-registered): a sequence that is exhausted with 28 <= confirmed events < 46 triggers the next block of six worlds, decided by label counts only; this script only reports it."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import acceptance_config as cfg
import acceptance_packet as ap
import acceptance_state as st

if __name__ == "__main__":
    st.require("generated")
    plan, _, labels = ap.load()
    status = ap.sequence_status(plan, labels)
    notdone = [k for k, v in status.items() if not v["done"]]
    if notdone:
        raise SystemExit(f"labelling not finished: {notdone}")
    trigger = [k for k, v in status.items() if not k.endswith("control") and v["labelled"] >= v["planned"] and cfg.MIN_EVENTS - 1 <= v["confirmed_events"] < cfg.TARGET_EVENTS]
    print(json.dumps(status, indent=1))
    print("expansion triggered (28 <= events < 46 with the sequence exhausted):", trigger)
    if "--confirm" in sys.argv:
        st.advance("labels_frozen", labels_sha256=st.sha(ap.LABELS), labelled=len(labels), expansion_triggered=trigger)
        print("labels frozen")
