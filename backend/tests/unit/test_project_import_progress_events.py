from __future__ import annotations

import json
from uuid import UUID

import pytest

from backend.domain.project_import_plans import (
    _rewrite_record_data, _target_projection, _validate_graph,
    _validate_publication_references, _validate_canon_progress_reference,
)
from backend.domain.project_import_publication import encode_publication_batches
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import PackageRecord, thaw_json_value


KINDS = {
    "volume": "planning-volume", "plot": "planning-plot", "story_block": "story-block",
    "stage": "planning-stage", "scene_task": "scene-task",
}


def event(target_type="scene_task", target_id="scene-task:1", *, field_path=None):
    return PackageRecord("canon-event", "canon-event:1", data={
        "canonRevisionLogicalId": "canon-revision:1", "revisionNumber": 1, "eventOrder": 1,
        "entityLogicalId": None, "factKind": "dynamic_event",
        "fieldPath": field_path or f"plot.progress.{target_type}.{target_id}",
        "value": {"targetType": target_type, "targetId": target_id, "status": "completed", "chapterNumber": 3},
        "evidence": {}, "effectiveStartChapter": 3, "effectiveEndChapter": None,
        "assertionOperator": "equals", "valueCardinality": "single", "confirmationStatus": "confirmed",
        "createdAt": 1,
    })


def identities(kind="scene-task"):
    return {("canon-revision", "canon-revision:1"): str(UUID(int=1)),
            ("canon-event", "canon-event:1"): str(UUID(int=2)),
            (kind, f"{kind}:1"): str(UUID(int=3))}


@pytest.mark.parametrize("target_type,kind", KINDS.items())
def test_progress_reference_survives_rewrite_publication_and_projection(target_type, kind):
    record = event(target_type, f"{kind}:1")
    ids = identities(kind)
    data = _rewrite_record_data(record, ids, {})
    target_id = str(UUID(int=3))
    assert data["value"]["targetId"] == target_id
    assert data["fieldPath"] == f"plot.progress.{target_type}.{target_id}"
    assert record.data["value"]["targetId"] == f"{kind}:1"
    rewritten = {(record.entity_type, record.logical_id): data}
    batches = encode_publication_batches(
        (record,), rewritten, ids, command_id=str(UUID(int=4)),
        target_project_id=str(UUID(int=5)), new_title="Imported", source_records=(record,),
    )
    batch = next(item for item in batches if item.table == "canon_events")
    row = dict(zip(batch.columns, batch.rows[0], strict=True))
    assert json.loads(row["value_json"])["targetId"] == target_id
    assert row["field_path"] == data["fieldPath"]
    projection = thaw_json_value(_target_projection(rewritten, ids, revision=1))
    assert target_id in json.dumps(projection)
    assert f"{kind}:1" not in json.dumps(projection)


@pytest.mark.parametrize("record", [
    event(target_id="scene-task:2"),
    event(target_id="planning-stage:1"),
    event(field_path="plot.progress.scene_task.scene-task:2"),
    event(field_path="plot.progress.stage.scene-task:1"),
    event(target_type="unknown"),
])
def test_rewrite_rejects_dangling_wrong_kind_or_inconsistent_progress(record):
    with pytest.raises(ProjectImportInvalid):
        _rewrite_record_data(record, identities(), {})


def test_ordinary_fact_values_are_not_reinterpreted_as_planning_references():
    record = event(target_id="scene-task:999", field_path="observations.reportedProgress")
    data = _rewrite_record_data(record, identities(), {})
    assert data["value"] == thaw_json_value(record.data["value"])
    assert data["fieldPath"] == record.data["fieldPath"]


@pytest.mark.parametrize("target_type,kind", KINDS.items())
def test_preflight_progress_reference_requires_typed_existing_planning_identity(target_type, kind):
    record = event(target_type, f"{kind}:1")
    _validate_canon_progress_reference(record, {(kind, f"{kind}:1")})
    with pytest.raises(ProjectImportInvalid):
        _validate_canon_progress_reference(record, {(kind, f"{kind}:2")})
    with pytest.raises(ProjectImportInvalid):
        _validate_canon_progress_reference(record, {("canon-entity", f"{kind}:1")})


def test_graph_and_publication_preflight_reject_dangling_progress_with_nullable_entity():
    from backend.tests.unit.test_project_import_authority_rewrite import _package

    revision = PackageRecord("canon-revision", "canon-revision:1", data={
        "revisionNumber": 0, "parentRevisionNumber": 0, "sourceType": "bootstrap",
        "sourceLogicalId": None,
    })
    ordinary = event(field_path="observations.reportedProgress")
    ordinary_data = thaw_json_value(ordinary.data)
    ordinary_data["revisionNumber"] = 0
    ordinary = PackageRecord("canon-event", "canon-event:1", data=ordinary_data)
    records = (revision, ordinary)
    _validate_graph(records)
    _validate_publication_references(_package(records))
    invalid_data = dict(ordinary_data, fieldPath="plot.progress.scene_task.scene-task:1")
    invalid_records = (revision, PackageRecord("canon-event", "canon-event:1", data=invalid_data))
    with pytest.raises(ProjectImportInvalid):
        _validate_graph(invalid_records)
    with pytest.raises(ProjectImportInvalid):
        _validate_publication_references(_package(invalid_records))
