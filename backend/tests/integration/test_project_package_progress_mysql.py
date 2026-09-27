"""Committed progress and long review IDs survive real MySQL package boundaries."""

import json
from hashlib import sha256
from uuid import UUID, uuid5

import pytest

from backend.domain.finalization import FinalizationChangeSet
from backend.domain.project_import_plans import build_publication_plan
from backend.tests.integration.test_continuity_issue_packages_mysql import (
    PROJECT_ID, _seed_finalized_project, _packages, _lifecycle, finalized_fixture,
)


COMMAND_ID = "86000000-0000-4000-8000-000000000001"
LONG_EVENT_ID = "canon_event_author_progress_observation_" + "x" * 40
LONG_PROGRESS_ID = "scene_task_author_progress_completed_" + "y" * 40


class _ProgressExtraction:
    async def extract(self, *, manifest, **kwargs):
        payload = {
            "schemaVersion": "finalization-changeset-v1", "title": f"Chapter {manifest.chapter_number}",
            "summary": "Observed the guard change.", "existingEntityIds": [], "entities": [], "aliases": [],
            "canonEvents": [], "storyProgressEvents": [], "planningPatches": [], "planningSuggestions": [],
        }
        if manifest.chapter_number == 1:
            prose = manifest.candidate_prose
            evidence = {"startScalar": 0, "endScalar": len(prose),
                "excerptHash": sha256(prose.encode()).hexdigest(), "confidence": 1.0,
                "rationale": "The candidate directly describes the guard change."}
            task = manifest.planning_context["content"]["storyBlocks"][0]["stages"][0]["sceneTasks"][0]
            payload["canonEvents"] = [{
                "id": LONG_EVENT_ID, "entityId": None, "factKind": "dynamic_event",
                "fieldPath": "observations.guardChange", "value": "The guard change was observed.",
                "evidence": evidence, "effectiveStartChapter": 1, "effectiveEndChapter": None,
                "assertionOperator": "equals", "valueCardinality": "single",
            }]
            payload["storyProgressEvents"] = [{
                "id": LONG_PROGRESS_ID, "targetType": "scene_task", "targetId": task["id"],
                "status": "completed", "evidence": evidence,
            }]
        return FinalizationChangeSet.model_validate(payload)


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_committed_progress_export_preflight_and_publication_plan(
    disposable_mysql, monkeypatch, tmp_path,
):
    monkeypatch.setattr(finalized_fixture, "FINAL_ONE", "The guard change was observed.")
    monkeypatch.setattr(finalized_fixture, "_Extraction", _ProgressExtraction)
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    async with transaction() as session:
        source_events = await session.fetchall(
            "SELECT id,field_path,value_json FROM canon_events WHERE project_id=%s ORDER BY event_order",
            (PROJECT_ID,),
        )
        reviews = await session.fetchall(
            "SELECT payload_json FROM finalization_change_set_revisions WHERE project_id=%s", (PROJECT_ID,),
        )
    assert len(source_events) == 2
    assert all(len(row["id"]) == 36 for row in source_events)
    review_payloads = [json.loads(row["payload_json"]) for row in reviews]
    first_review = next(payload for payload in review_payloads if payload["canonEvents"])
    assert first_review["canonEvents"][0]["id"] == LONG_EVENT_ID
    assert first_review["storyProgressEvents"][0]["id"] == LONG_PROGRESS_ID
    source_progress = next(row for row in source_events if row["field_path"].startswith("plot.progress."))
    source_value = json.loads(source_progress["value_json"])
    source_target_id = source_value["targetId"]
    assert source_progress["field_path"] == f"plot.progress.scene_task.{source_target_id}"

    source_project = await _lifecycle(transaction).get(PROJECT_ID)
    async with _packages(disposable_mysql, tmp_path) as export:
        package = await export(PROJECT_ID, source_project.lifecycle_revision)
        progress = next(record for record in package.graph_index.values()
            if record.entity_type == "canon-event" and record.data["fieldPath"].startswith("plot.progress."))
        logical_target = progress.data["value"]["targetId"]
        assert logical_target.startswith("scene-task:")
        assert progress.data["fieldPath"] == f"plot.progress.scene_task.{logical_target}"
        assert progress.data.get("entityLogicalId") is None
        plan = build_publication_plan(package, COMMAND_ID, "Progress package regression")
        target_id = str(uuid5(UUID(COMMAND_ID), f"scene-task/{logical_target}"))
        batch = next(batch for batch in plan.batches if batch.table == "canon_events")
        rows = [dict(zip(batch.columns, row, strict=True)) for row in batch.rows]
        target_progress = next(row for row in rows if row["field_path"].startswith("plot.progress."))
        assert target_id != source_target_id
        assert target_progress["field_path"] == f"plot.progress.scene_task.{target_id}"
        assert json.loads(target_progress["value_json"]) == {**source_value, "targetId": target_id}
        assert target_progress["id"] != source_progress["id"]
        assert all(len(row["id"]) == 36 for row in rows)
        planning_batch = next(batch for batch in plan.batches if batch.table == "planning_revisions")
        assert any(target_id in str(row) for row in planning_batch.rows)
        assert source_target_id not in str(plan.expected_projection)
        assert target_id in str(plan.expected_projection)

    async with transaction() as session:
        assert await session.fetchall(
            "SELECT id,field_path,value_json FROM canon_events WHERE project_id=%s ORDER BY event_order",
            (PROJECT_ID,),
        ) == source_events
