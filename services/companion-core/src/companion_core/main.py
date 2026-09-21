"""Production entrypoint: `uvicorn companion_core.main:app`."""

from __future__ import annotations

from companion_core.app import create_app

app = create_app()
