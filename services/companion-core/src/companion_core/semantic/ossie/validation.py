"""Validation of an Ossie document against the schema vendored at the pinned commit (SOURCE.md). Fails closed: any other spec
version is refused rather than interpreted. `jsonschema` is a runtime dependency of companion-core, so validation works in the
service image wherever an export is produced."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from companion_core.semantic.ossie.mapping import PINNED_SPEC_VERSION

SCHEMA_PATH = Path(__file__).with_name("ossie-schema.json")
# SHA-256 of the vendored file, so a silent edit or a partial update of the schema is caught (see SOURCE.md).
SCHEMA_SHA256 = "5b9cf15d31057e2b7363194b1c254a6b669fc412b3f8f402d4efbdcfa25fcc87"


class UnsupportedSpecVersionError(ValueError):
    pass


class OssieValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    raw = SCHEMA_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise RuntimeError("vendored Ossie schema does not match the pinned checksum; see semantic/ossie/SOURCE.md")
    return json.loads(raw)


def validate(document: dict[str, Any]) -> None:
    """Raises UnsupportedSpecVersionError for any version but the pinned one, OssieValidationError for schema violations."""
    version = document.get("version")
    if version != PINNED_SPEC_VERSION:
        raise UnsupportedSpecVersionError(f"unsupported Ossie spec version {version!r}; this adapter supports {PINNED_SPEC_VERSION!r}")
    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        raise OssieValidationError([f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in errors])
