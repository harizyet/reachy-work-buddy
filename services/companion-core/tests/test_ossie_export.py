"""Phase 44A Ossie structural export (docs/phase-44.md D1): validity against the vendored schema, a golden file, fail-closed
versioning, and what the export does not claim."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from companion_core.semantic.ossie import export, mapping, validation

GOLDEN = Path(__file__).parent / "fixtures" / "ossie_structural_export.json"


def test_export_validates_against_the_pinned_schema() -> None:
    validation.validate(export.export_semantic_model())


def test_export_matches_the_golden_file() -> None:
    # Regenerate with: python -c "from companion_core.semantic.ossie import export; print(export.export_json(), end='')"
    assert json.loads(GOLDEN.read_text()) == export.export_semantic_model()
    assert GOLDEN.read_text() == export.export_json()


def test_export_is_deterministic() -> None:
    assert export.export_json() == export.export_json()


def test_vendored_schema_is_the_pinned_one() -> None:
    raw = validation.SCHEMA_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == validation.SCHEMA_SHA256
    assert json.loads(raw)["properties"]["version"]["const"] == mapping.PINNED_SPEC_VERSION
    source = (validation.SCHEMA_PATH.parent / "SOURCE.md").read_text()
    assert mapping.PINNED_COMMIT in source and validation.SCHEMA_SHA256 in source and mapping.PINNED_SPEC_VERSION in source
    assert "Apache License" in (validation.SCHEMA_PATH.parent / "LICENSE").read_text()
    assert "Apache Ossie" in (validation.SCHEMA_PATH.parent / "NOTICE").read_text()


def test_a_modified_schema_is_refused(monkeypatch, tmp_path) -> None:
    tampered = tmp_path / "ossie-schema.json"
    tampered.write_text(validation.SCHEMA_PATH.read_text().replace("Dataset", "Datasets", 1))
    monkeypatch.setattr(validation, "SCHEMA_PATH", tampered)
    validation.load_schema.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="pinned checksum"):
            validation.load_schema()
    finally:
        validation.load_schema.cache_clear()


def test_any_other_spec_version_fails_closed() -> None:
    document = export.export_semantic_model()
    for version in ("0.2.0", "0.1.0", "0.2.0.dev1", "", None):
        with pytest.raises(validation.UnsupportedSpecVersionError):
            validation.validate({**document, "version": version})
    missing = {k: v for k, v in document.items() if k != "version"}
    with pytest.raises(validation.UnsupportedSpecVersionError):
        validation.validate(missing)


def test_schema_violations_are_reported() -> None:
    document = export.export_semantic_model()
    broken = copy.deepcopy(document)
    del broken["datasets"][0]["source"]
    broken["datasets"][1]["fields"][0]["datatype"] = "Varchar"
    with pytest.raises(validation.OssieValidationError) as caught:
        validation.validate(broken)
    assert any("source" in e for e in caught.value.errors) and any("Varchar" in e for e in caught.value.errors)
    with pytest.raises(validation.OssieValidationError):
        validation.validate({**document, "surprise": True})


def test_every_exported_field_is_a_real_model_field_and_classification_is_exported() -> None:
    model = export.export_semantic_model()
    by_name = {d["name"]: d for d in model["datasets"]}
    assert set(by_name) == {spec.name for spec in mapping.DATASETS}
    for spec in mapping.DATASETS:
        exported = [f["name"] for f in by_name[spec.name]["fields"]]
        assert exported == mapping.column_names(spec)
        assert set(exported) <= set(spec.model.model_fields)
        assert "sensitivity" in exported, spec.name  # D2: every authoritative store carries it
        assert by_name[spec.name]["source"] == f"public.{spec.table}"


def test_meeting_content_is_not_advertised() -> None:
    meetings = {d["name"]: d for d in export.export_semantic_model()["datasets"]}["meetings"]
    names = {f["name"] for f in meetings["fields"]}
    assert not names & {
        "transcript_segments", "diarization_segments", "aligned_segments", "audio_path", "normalized_audio_path",
        "transcript_corrections", "summary", "minutes", "speaker_names", "context", "participants",
    }


def test_export_makes_no_knowledge_graph_claims() -> None:
    model = export.export_semantic_model()
    assert "relationships" not in model  # the stores declare no foreign keys, so none are invented
    extension = json.loads(model["custom_extensions"][0]["data"])
    assert {"entities", "typed relationships", "provenance", "confidence"} <= set(extension["not_expressed"])
    dataset_extension = json.loads(model["datasets"][0]["custom_extensions"][0]["data"])
    assert dataset_extension["default_sensitivity"] == "work-private"
    text = json.dumps(model).lower()
    assert "instructions" not in text and "ai_context" not in text  # nothing an AI consumer could read as a directive


def test_import_is_not_implemented() -> None:
    root = Path(export.__file__).parent
    assert not (root / "import.py").exists() and not hasattr(export, "import_semantic_model")


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [(str, "String"), (int, "Integer"), (float, "Float"), (bool, "Boolean"), (list, "Opaque"), (dict, "Opaque")],
)
def test_datatype_mapping(annotation, expected) -> None:
    assert mapping.datatype(annotation) == expected
    assert mapping.datatype(annotation | None) == expected


def test_jsonschema_is_a_runtime_dependency_of_the_service_not_a_dev_extra() -> None:
    """The service image installs with `--no-dev`; validation must not depend on the dev group."""
    import tomllib

    root = Path(__file__).parents[3]
    core = tomllib.loads((root / "services/companion-core/pyproject.toml").read_text())
    assert any(d.startswith("jsonschema") for d in core["project"]["dependencies"])
    dev = tomllib.loads((root / "pyproject.toml").read_text())["dependency-groups"]["dev"]
    assert not any(d.startswith("jsonschema") for d in dev)
