"""Export-only Apache Ossie adapter (docs/phase-44.md D1): Reachy's stores as an Ossie semantic model.

Import is deliberately not implemented; an imported model would be untrusted data and nothing needs it yet. The ontology
(`companion_core.semantic.model`) does not depend on this package; this package reads store models, never the other way round."""

from __future__ import annotations

import json
from typing import Any

from companion_core.semantic.ossie.mapping import (
    DATASETS,
    METRICS,
    MODEL_NAME,
    PINNED_SPEC_VERSION,
    UNSUPPORTED_CONCEPTS,
    VENDOR,
    DatasetSpec,
    column_names,
    datatype,
)
from shared.models.response import Privacy


def _expression(sql: str) -> dict[str, Any]:
    return {"dialects": [{"dialect": "ANSI_SQL", "expression": sql}]}


def _extension(data: dict[str, Any]) -> dict[str, str]:
    # Ossie extension data is a JSON string; sort keys so the export is byte-stable.
    return {"vendor_name": VENDOR, "data": json.dumps(data, sort_keys=True, separators=(",", ":"))}


def _dataset(spec: DatasetSpec) -> dict[str, Any]:
    fields = []
    for name in column_names(spec):
        annotation = spec.model.model_fields[name].annotation
        field: dict[str, Any] = {"name": name, "expression": _expression(name)}
        kind = datatype(annotation)
        if kind != "Opaque":
            field["datatype"] = kind
        fields.append(field)
    return {
        "name": spec.name,
        "source": f"public.{spec.table}",
        "primary_key": ["id"],
        "description": spec.description,
        "fields": fields,
        "custom_extensions": [
            _extension({
                "authoritative_store": True,
                "default_sensitivity": Privacy.WORK_PRIVATE.value,
                "scope_column": spec.scope_column,
                "sensitivity_column": spec.sensitivity_column if "sensitivity" in column_names(spec) else None,
                "unscoped_means": "unscoped, neither public nor every project",
            })
        ],
    }


def export_semantic_model() -> dict[str, Any]:
    """The structural model of Reachy's stores, as a plain dict ready for `validation.validate` and `json.dumps`.

    No relationships are emitted: Ossie relationships are foreign keys between datasets, and the stores declare none (a document
    chunk's `document_id` has no parent table). Nothing in the export reflects row contents."""
    return {
        "version": PINNED_SPEC_VERSION,
        "name": MODEL_NAME,
        "description": "Structure of Reachy's authoritative stores (memory, documents, meetings, notes, tasks, reminders).",
        "datasets": [_dataset(spec) for spec in DATASETS],
        "metrics": [
            {"name": name, "expression": _expression(sql), "description": description, "datatype": kind}
            for name, sql, description, kind in METRICS
        ],
        "custom_extensions": [
            _extension({
                "not_expressed": list(UNSUPPORTED_CONCEPTS),
                "note": "Structural description only. Reachy's knowledge ontology is not represented in this model.",
            })
        ],
    }


def export_json() -> str:
    return json.dumps(export_semantic_model(), indent=2, sort_keys=False) + "\n"
