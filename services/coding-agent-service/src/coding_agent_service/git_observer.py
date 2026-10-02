"""29.9: deterministic repository state read straight from Git, so a
completion report never rests on the coding agent's own account of what it
changed. Runs `git` in a throwaway container over a read-only mount: the
service itself has no checkout of the host project path.
"""

from __future__ import annotations

import logging

from coding_agent_service.runtime import ContainerRuntime
from shared.models.coding_agent import GitState

logger = logging.getLogger(__name__)

# The mount is owned by a different uid than the container user.
_GIT = ["-c", "safe.directory=/workspace"]
_MAX_FILES = 50


class GitObserver:
    def __init__(self, runtime: ContainerRuntime, image: str) -> None:
        self._runtime = runtime
        self._image = image

    async def _git(self, host_path: str, *args: str) -> str:
        return await self._runtime.run_once(
            image=self._image,
            host_path=host_path,
            entrypoint="git",
            args=[*_GIT, *args],
        )

    async def observe(self, host_path: str) -> GitState | None:
        """None when the path is not a readable repository; an observation
        failure must never block a session transition."""
        try:
            head = (await self._git(host_path, "rev-parse", "HEAD")).strip()
            branch = (
                await self._git(host_path, "rev-parse", "--abbrev-ref", "HEAD")
            ).strip()
            status = await self._git(host_path, "status", "--porcelain")
        except Exception:
            logger.info("Git state unavailable for %s", host_path, exc_info=True)
            return None
        files = [line[3:] for line in status.splitlines() if len(line) > 3]
        return GitState(
            head=head or None,
            branch=branch or None,
            dirty=bool(files),
            changed_files=files[:_MAX_FILES],
        )
