"""Per-document working copies. One directory and one backend path per Reachy document id, so forgetting one document's
file never removes another's even when the bytes (and therefore the backend object) are identical."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from shared.models.document_types import TYPES
from shared.models.document_worker import DOCUMENT_ID_RE

EXTENSIONS = tuple(TYPES)  # shared/models/document_types.py: the types MinerU was shown to parse


@dataclass
class Meta:
    document_id: str
    source_hash: str
    extension: str
    tier: str
    backend_ref: str


class DocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, document_id: str) -> Path:
        if not DOCUMENT_ID_RE.match(document_id):
            raise ValueError("invalid document id")
        return self.root / document_id

    def source_path(self, document_id: str, extension: str) -> Path:
        return self._dir(document_id) / f"source.{extension}"

    def staging_path(self, document_id: str) -> Path:
        directory = self._dir(document_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "upload.part"

    def get(self, document_id: str) -> Meta | None:
        try:
            raw = (self._dir(document_id) / "meta.json").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return Meta(**json.loads(raw))

    def put(self, meta: Meta) -> None:
        target = self._dir(meta.document_id) / "meta.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(meta)), encoding="utf-8")
        os.replace(tmp, target)

    def remove(self, document_id: str) -> None:
        shutil.rmtree(self._dir(document_id), ignore_errors=True)

    def paths_for_hash(self, source_hash: str) -> int:
        """How many working copies hold these bytes (so deletion can tell a shared backend object remains)."""
        count = 0
        for child in self.root.iterdir():
            meta = self.get(child.name) if DOCUMENT_ID_RE.match(child.name) else None
            if meta is not None and meta.source_hash == source_hash:
                count += 1
        return count
