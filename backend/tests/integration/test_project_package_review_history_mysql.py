"""Repeated and failed author reviews retain exact associations in real backups."""
from uuid import uuid4

import pytest

from backend.tests.integration.test_continuity_issue_packages_mysql import (
    PROJECT_ID, _seed_finalized_project, _packages, _lifecycle, _publish,
)


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_distinct_saves_of_one_candidate_survive_backup_restore(disposable_mysql, monkeypatch, tmp_path):
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    async with transaction() as session:
        original = await session.fetchone(
            "SELECT * FROM candidate_freeze_requests WHERE project_id=%s ORDER BY created_at,id LIMIT 1",
            (PROJECT_ID,),
        )
        assert original is not None
        repeated = {**original, "id": str(uuid4()), "idempotency_key": uuid4().hex * 2,
                    "created_at": original["created_at"] + 1}
        columns = tuple(repeated)
        await session.execute(
            f"INSERT INTO candidate_freeze_requests ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})",
            tuple(repeated.values()),
        )
        source = await session.fetchall(
            "SELECT COUNT(*) AS n FROM candidate_freeze_requests WHERE project_id=%s GROUP BY draft_candidate_id ORDER BY n",
            (PROJECT_ID,),
        )
    lifecycle = await _lifecycle(transaction).get(PROJECT_ID)
    async with _packages(disposable_mysql, tmp_path) as export:
        package = await export(PROJECT_ID, lifecycle.lifecycle_revision)
        plan = await _publish(package, transaction)
        async with transaction() as session:
            restored = await session.fetchall(
                "SELECT COUNT(*) AS n FROM candidate_freeze_requests WHERE project_id=%s GROUP BY draft_candidate_id ORDER BY n",
                (plan.target_project_id,),
            )
        assert restored == source
        await _assert_restored_reviews_readable(transaction, plan.target_project_id)


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_repeated_quality_and_failed_attempts_survive_restore(disposable_mysql, monkeypatch, tmp_path):
    from backend.tests.integration.test_continuity_issue_packages_mysql import finalized_fixture
    from backend.domain.finalization import FinalizationChangeSet
    original_extraction = finalized_fixture._Extraction

    class EntityExtraction(original_extraction):
        async def extract(self, *, manifest, **kwargs):
            result = await super().extract(manifest=manifest, **kwargs)
            if manifest.chapter_number == 1:
                payload = result.model_dump(mode="json", by_alias=True)
                payload["entities"] = [{"id": "review-history-person", "entityType": "person", "canonicalName": "Lin"}]
                return FinalizationChangeSet.model_validate(payload)
            return result

    monkeypatch.setattr(finalized_fixture, "_Extraction", EntityExtraction)
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    async with transaction() as session:
        original = await session.fetchone("SELECT * FROM finalization_change_sets WHERE project_id=%s ORDER BY created_at,id LIMIT 1", (PROJECT_ID,))
        quality = await session.fetchone("SELECT * FROM candidate_quality_reports WHERE id=%s", (original["quality_report_id"],))
        quality = {**quality, "id": str(uuid4()), "created_at": quality["created_at"] + 1}
        columns = tuple(quality)
        await session.execute(f"INSERT INTO candidate_quality_reports ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})", tuple(quality.values()))
        for with_quality in (True, False):
            failed = {**original, "id": str(uuid4()), "status": "failed", "active_slot": None,
                "quality_report_id": quality["id"] if with_quality else None, "extraction_id": None,
                "current_revision": None, "current_revision_hash": None, "confirmed_revision": None,
                "confirmed_revision_hash": None, "confirmed_at": None, "idempotency_key": uuid4().hex * 2,
                "created_at": original["created_at"] + 2 + int(with_quality)}
            columns = tuple(failed)
            await session.execute(f"INSERT INTO finalization_change_sets ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})", tuple(failed.values()))
        source = await session.fetchall("SELECT s.status,s.current_revision,s.confirmed_revision,q.created_at AS quality_created FROM finalization_change_sets s LEFT JOIN candidate_quality_reports q ON q.id=s.quality_report_id WHERE s.project_id=%s ORDER BY s.created_at,s.id", (PROJECT_ID,))
    await _assert_restored_reviews_readable(transaction, PROJECT_ID, restored_context=False)
    lifecycle = await _lifecycle(transaction).get(PROJECT_ID)
    async with _packages(disposable_mysql, tmp_path) as export:
        package = await export(PROJECT_ID, lifecycle.lifecycle_revision)
        attempts = [r for r in package.graph_index.values() if r.entity_type == "finalization-change-set"]
        assert all("qualityReportLogicalId" in r.data for r in attempts)
        assert sum(r.data["status"] == "failed" for r in attempts) == 2
        canon_logical_ids = {r.logical_id for r in package.graph_index.values() if r.entity_type == "canon-entity"}
        for r in package.graph_index.values():
            if r.entity_type == "finalization-change-set-revision":
                assert {item["id"] for item in r.data["payload"]["entities"]} <= canon_logical_ids
        plan = await _publish(package, transaction)
        async with transaction() as session:
            restored = await session.fetchall("SELECT s.status,s.current_revision,s.confirmed_revision,q.created_at AS quality_created FROM finalization_change_sets s LEFT JOIN candidate_quality_reports q ON q.id=s.quality_report_id WHERE s.project_id=%s ORDER BY s.created_at,s.id", (plan.target_project_id,))
        assert restored == source
        async with transaction() as session:
            canon = await session.fetchall("SELECT id,created_revision FROM canon_entities WHERE project_id=%s", (plan.target_project_id,))
            changes = await session.fetchall("SELECT payload_json FROM finalization_change_set_revisions WHERE project_id=%s", (plan.target_project_id,))
        import json
        canon_ids = {row["id"] for row in canon}
        for change in changes:
            assert {item["id"] for item in json.loads(change["payload_json"])["entities"]} <= canon_ids, (canon, json.loads(change["payload_json"])["entities"])
        await _assert_restored_reviews_readable(transaction, plan.target_project_id)
        restored_lifecycle = await _lifecycle(transaction).get(plan.target_project_id)
        restored_package = await export(plan.target_project_id, restored_lifecycle.lifecycle_revision)
        assert sum(r.entity_type == "finalization-change-set" for r in restored_package.graph_index.values()) == len(attempts)

@pytest.mark.mysql
@pytest.mark.asyncio
async def test_actual_author_backup_restores_in_isolated_mysql(disposable_mysql):
    """Opt-in evidence run; regular regression uses the self-contained fixture above."""
    import os
    from pathlib import Path
    from backend.domain.project_import_plans import read_verified_project_package
    from backend.tests.support.disposable_mysql import transaction_factory_for
    selected = os.environ.get("AUTHOR_REVIEW_BACKUP_TEST_PATH")
    if not selected:
        pytest.skip("No explicit author acceptance backup selected")
    package = read_verified_project_package(Path(selected))
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    plan = await _publish(package, transaction)
    source = [r for r in package.graph_index.values() if r.entity_type == "finalization-change-set"]
    async with transaction() as session:
        restored = await session.fetchall("SELECT id,status,quality_report_id,current_revision FROM finalization_change_sets WHERE project_id=%s", (plan.target_project_id,))
        chapters = await session.fetchall("SELECT chapter_num,content_hash FROM final_chapters WHERE project_id=%s ORDER BY chapter_num", (plan.target_project_id,))
    from collections import Counter
    assert Counter(r["status"] for r in restored) == Counter(r.data["status"] for r in source)
    assert len(chapters) == sum(r.entity_type == "final-chapter" for r in package.graph_index.values())
    from uuid import UUID, uuid5
    from backend.tests.integration.test_project_import_publication_mysql import COMMAND_ID
    by_id = {r["id"]: r for r in restored}
    for attempt in source:
        target_id = str(uuid5(UUID(COMMAND_ID), f"finalization-change-set/{attempt.logical_id}"))
        quality = attempt.data.get("qualityReportLogicalId")
        expected_quality = str(uuid5(UUID(COMMAND_ID), f"candidate-quality/{quality}")) if quality else None
        assert by_id[target_id]["quality_report_id"] == expected_quality
        revisions = [r.data["revision"] for r in package.graph_index.values()
            if r.entity_type == "finalization-change-set-revision" and r.data["changeSetLogicalId"] == attempt.logical_id]
        assert by_id[target_id]["current_revision"] == (max(revisions) if revisions else None)
    await _assert_restored_reviews_readable(transaction, plan.target_project_id)
    expected_chapters = sorted((r.data["chapterNumber"], r.data["contentHash"])
        for r in package.graph_index.values() if r.entity_type == "final-chapter")
    assert [(r["chapter_num"], r["content_hash"]) for r in chapters] == expected_chapters


async def _assert_restored_reviews_readable(transaction, project_id, restored_context=True):
    import json
    from backend.domain.json_contracts import canonical_hash
    from backend.repositories.workbench_reviews import WorkbenchReviewRepository
    from backend.services.workbench_reviews import WorkbenchReviewReader
    reader = WorkbenchReviewReader(WorkbenchReviewRepository(), transaction)
    async with transaction() as session:
        chapters = await session.fetchall("SELECT chapter_num FROM final_chapters WHERE project_id=%s ORDER BY chapter_num", (project_id,))
        attempts = await session.fetchall("SELECT s.context_manifest_json,s.context_manifest_hash,q.context_manifest_hash AS quality_hash FROM finalization_change_sets s JOIN candidate_quality_reports q ON q.id=s.quality_report_id WHERE s.project_id=%s", (project_id,))
    assert chapters
    for attempt in attempts if restored_context else ():
        manifest = json.loads(attempt["context_manifest_json"])
        assert manifest["kind"] == "project-backup-review-context-v1"
        assert manifest["projectId"] == project_id
        assert len(manifest["sourceContextManifestHash"]) == 64
        assert canonical_hash(manifest) == attempt["context_manifest_hash"] == attempt["quality_hash"]
    for chapter in chapters:
        review = await reader.review(project_id, chapter["chapter_num"])
        assert review.chapterNumber == chapter["chapter_num"]
        assert review.projectId == project_id
