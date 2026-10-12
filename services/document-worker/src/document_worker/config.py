"""Worker settings, all from the environment. Conservative provisional limits; 50A tunes them on the real worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from shared.models.document_worker import WorkerTier


@dataclass(frozen=True)
class Settings:
    token: str  # empty means every route except /health answers 503 (fail closed)
    work_dir: Path  # per-document working copies; derived state, rebuildable from Reachy's source store
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pages: int = 200
    tiers: tuple[WorkerTier, ...] = (WorkerTier.FLASH, WorkerTier.BASIC, WorkerTier.STANDARD, WorkerTier.ADVANCED)
    search_scan_limit: int = 200  # backend results examined per scoped search
    search_locate_max_pages: int = 60  # pages read to establish which page a hit is on

    @classmethod
    def from_env(cls) -> Settings:
        tiers = tuple(
            WorkerTier(t.strip()) for t in os.environ.get("DOCUMENT_WORKER_TIERS", "flash,basic,standard,advanced").split(",") if t.strip()
        )
        return cls(
            token=os.environ.get("DOCUMENT_WORKER_TOKEN", ""),
            work_dir=Path(os.environ.get("DOCUMENT_WORKER_WORK_DIR", "/data/work")),
            max_upload_bytes=int(os.environ.get("DOCUMENT_WORKER_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))),
            max_pages=int(os.environ.get("DOCUMENT_WORKER_MAX_PAGES", "200")),
            tiers=tiers,
        )
