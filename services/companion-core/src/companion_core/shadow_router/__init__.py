"""Shadow-mode semantic router -> extractor -> validator. See README in this package's docstrings and docs/shadow-router.md.

Contract: this package never executes a tool and never touches consent, draft, memory, task or robot state.
It runs after the production reply is final, as a background task, and only appends a record."""
from companion_core.shadow_router.shadow import ShadowPipeline, shadow_from_env

__all__ = ["ShadowPipeline", "shadow_from_env"]
