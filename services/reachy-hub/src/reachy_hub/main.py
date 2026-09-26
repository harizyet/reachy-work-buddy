"""Production entrypoint: `uvicorn reachy_hub.main:app`.

Kept separate from app.py so create_app() can be imported and called with
test doubles (an InMemoryRobotRegistry, an ASGI-backed EmbodimentClient)
without requiring DATABASE_URL to be set.
"""

from __future__ import annotations

import logging

from reachy_hub.app import create_app

# uvicorn configures only its own loggers, so this package's INFO lines
# (robot connections, voice session ends and turn outcomes, palm stop and
# model warm-up) were dropped; the 24e physical run had no hub-side record
# of them. These lines carry ids, outcomes and timings, never conversation
# text.
_package_log = logging.getLogger("reachy_hub")
if not _package_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _package_log.addHandler(_handler)
    _package_log.setLevel(logging.INFO)

app = create_app(warm_voice_providers=True)
