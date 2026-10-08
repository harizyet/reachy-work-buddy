"""What Reachy's stores look like to an Apache Ossie consumer (docs/phase-44.md D1, section 4).

Ossie describes analytical datasets, fields, joins and metrics. This catalogue maps Reachy's authoritative stores onto exactly
that and nothing more: it does not express entities, typed relationships, provenance, confidence, validity or supersession
(Ossie has no place for them). Those stay in Reachy's own ontology (`companion_core.semantic.model`), and the Reachy-only
facts that matter to a reader travel in an opaque `custom_extensions` entry that no other tool is expected to interpret.

Field lists come from the pydantic models the stores use, so they cannot drift from the code; a Postgres test compares them
with the real tables."""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum

from pydantic import BaseModel

from companion_core.meetings.models import Meeting
from companion_core.planner.models import Note, Reminder
from companion_core.tasks.models import Task
from shared.models.memory import MemoryRecord
from shared.models.rag import DocumentChunk

PINNED_SPEC_VERSION = "0.2.0.dev0"
PINNED_COMMIT = "8dd6732da354f22ca71f16d82626a46039ecdcd9"
VENDOR = "REACHY"
MODEL_NAME = "reachy_work_buddy"


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    table: str
    model: type[BaseModel]
    description: str
    # None exports every model field. Meetings list scalar columns explicitly: the audio paths, segments and generated text
    # are neither analytical columns nor something a schema description should advertise.
    fields: tuple[str, ...] | None = None
    sensitivity_column: str | None = "sensitivity"
    scope_column: str | None = None


DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        "memories", "memories", MemoryRecord,
        "Work memory: profile, working and episodic facts with provenance (source), confidence and expiry.",
        scope_column="project_scope",
    ),
    DatasetSpec(
        "document_chunks", "document_chunks", DocumentChunk,
        "Chunks of ingested documents. Every chunk of one document carries the document's classification and scope.",
        scope_column="project_scope",
    ),
    DatasetSpec(
        "meetings", "meetings", Meeting,
        "Recorded meetings. Transcript segments, speaker data and generated summaries are stored on the row but are not exported here.",
        fields=(
            "id", "title", "description", "title_source", "project_scope", "sensitivity", "started_at",
            "duration_seconds", "status", "created_at", "updated_at",
        ),
        scope_column="project_scope",
    ),
    DatasetSpec(
        "notes", "notes", Note, "Owner notes.", scope_column="project_scope",
    ),
    DatasetSpec(
        "tasks", "tasks", Task, "Owner tasks.", scope_column="project_scope",
    ),
    DatasetSpec(
        "reminders", "reminders", Reminder, "Timed reminders.",
    ),
)

# Metric expressions are ANSI SQL over `dataset.column`, as in the Ossie examples.
METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("open_tasks", "COUNT(CASE WHEN tasks.status = 'open' THEN 1 END)", "Tasks that are not done.", "Integer"),
    ("pending_reminders", "COUNT(CASE WHEN reminders.status = 'pending' THEN 1 END)", "Reminders not yet completed.", "Integer"),
    (
        "active_memories",
        "COUNT(CASE WHEN memories.forgotten_at IS NULL AND (memories.expires_at IS NULL OR memories.expires_at > CURRENT_TIMESTAMP) THEN 1 END)",
        "Memories that are neither forgotten nor expired.",
        "Integer",
    ),
    ("meetings_total", "COUNT(meetings.id)", "All stored meetings, whatever their processing state.", "Integer"),
    ("document_chunks_total", "COUNT(document_chunks.id)", "All stored document chunks.", "Integer"),
)

# What this export cannot say. Listed in the model's extension so a reader does not assume the absence means "none".
UNSUPPORTED_CONCEPTS = (
    "entities", "typed relationships", "provenance", "confidence", "temporal validity and supersession", "evidence links",
)


def datatype(annotation: object) -> str:
    """Ossie logical type for a pydantic field annotation (Optional unwrapped; anything unportable is Opaque)."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        return datatype(members[0]) if len(members) == 1 else "Opaque"
    if annotation is bool:
        return "Boolean"
    if annotation is int:
        return "Integer"
    if annotation is float:
        return "Float"
    if annotation is datetime:
        return "DateTimeTz"  # every timestamp column is TIMESTAMPTZ
    if annotation is date:
        return "Date"
    if annotation is time:
        return "Time"
    if annotation is str or (isinstance(annotation, type) and issubclass(annotation, Enum)):
        return "String"
    return "Opaque"


def column_names(spec: DatasetSpec) -> list[str]:
    declared = list(spec.model.model_fields)
    if spec.fields is None:
        return declared
    unknown = set(spec.fields) - set(declared)
    if unknown:
        raise ValueError(f"{spec.name}: not model fields: {sorted(unknown)}")
    return [name for name in declared if name in spec.fields]
