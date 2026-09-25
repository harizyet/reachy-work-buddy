"""Production entrypoint: `uvicorn reachy_hub.main:app`.

Kept separate from app.py so create_app() can be imported and called with
test doubles (an InMemoryRobotRegistry, an ASGI-backed EmbodimentClient)
without requiring DATABASE_URL to be set.
"""

from __future__ import annotations

from reachy_hub.app import create_app

app = create_app(warm_voice_providers=True)
