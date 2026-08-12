from __future__ import annotations

from hashlib import sha256

import pytest

from backend.domain.chapter_outlines import (
    DraftChapterOutline,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.finalization import (
    FinalizationChangeSet,
    QualityReportPayload,
    change_set_hash,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import DraftPlanningAggregate, normalize_planning_aggregate
from backend.repositories.canon import CanonRepository
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.planning import PlanningRepository
from backend.services.canon import CanonService
from backend.services.finalization import FinalizationService, PrepareFinalization
from backend.services.finalization_commit import (
    AtomicFinalizationService,
    CommitFinalization,
    FinalizationCommitInvalid,
)
from backend.services.projections import build_projection_bundle
from backend.tests.integration.test_schema_bootstrap import (
    _insert_revision_one_contracts,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


PROJECT_ID = "10000000-0000-4000-8000-000000000001"
BINDING_ID = "10000000-0000-4000-8000-000000000002"
SEED_ID = "10000000-0000-4000-8000-000000000003"
SEED_REVISION_ID = "10000000-0000-4000-8000-000000000004"
CONTRACT_ID = "10000000-0000-4000-8000-000000000005"
STYLE_ID = "10000000-0000-4000-8000-000000000006"
BIBLE_ID = "10000000-0000-4000-8000-000000000007"
PLANNING_ID = "10000000-0000-4000-8000-000000000008"
OUTLINE_ID = "10000000-0000-4000-8000-000000000009"
SESSION_ID = "10000000-0000-4000-8000-000000000010"
WORKING_ID = "10000000-0000-4000-8000-000000000011"
CANDIDATE_ID = "10000000-0000-4000-8000-000000000012"
REPORT_ID = "10000000-0000-4000-8000-000000000013"
ATTEMPT_ID = "10000000-0000-4000-8000-000000000014"
CHANGE_REVISION_ID = "10000000-0000-4000-8000-000000000015"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = 2_100_000_000_000


def _planning():
    draft = DraftPlanningAggregate.model_validate({
        "activeStoryBlockRef": "block",
        "volumes": [{
            "clientNodeKey": "volume", "order": 1, "title": "第一卷",
            "coreChange": "逃亡转为立足。", "mainPressure": "追兵逼近。",
            "ensembleFocus": ["主角"], "forbiddenEvents": [],
        }],
        "plots": [{
            "clientNodeKey": "plot", "order": 1, "title": "追查",
            "plotType": "mystery", "storyQuestion": "幕后人是谁？",
            "futureDirection": "寻找线索。", "expectedPayoff": "揭示内应。",
            "relatedCharacters": ["主角"],
        }],
        "storyBlocks": [{
            "clientNodeKey": "block", "order": 1, "title": "入城",
            "volumeRef": "volume", "plotRefs": ["plot"],
            "entrySituation": "城门封锁。", "blockGoal": "进入城中。",
            "mainPressure": "追兵将至。", "expectedChange": "取得身份。",
            "openQuestions": [], "involvedCharacters": ["主角"],
            "stages": [{
                "clientNodeKey": "stage", "order": 1, "title": "过门",
                "purpose": "通过盘查。", "dramaticQuestion": "会暴露吗？",
                "sceneTasks": [{
                    "clientNodeKey": "task", "order": 1,
                    "task": "应对盘查。", "completionEvidence": "成功入城。",
                }],
            }],
        }],
    })
    ids = iter((
        "20000000-0000-4000-8000-000000000001",
        "20000000-0000-4000-8000-000000000002",
        "20000000-0000-4000-8000-000000000003",
        "20000000-0000-4000-8000-000000000004",
        "20000000-0000-4000-8000-000000000005",
    ))
    return normalize_planning_aggregate(
        draft, previous_confirmed=None, previous_draft=None,
        id_factory=ids.__next__,
    )


def _ref(node):
    return {"id": node.id, "revision": node.revision, "contentHash": node.content_hash}


def _outline(planning, projection_hash):
    block = planning.story_blocks[0]
    capacity = OutlineCapacityPolicy.model_validate({
        "targetMin": 1, "targetMax": 2, "softCeiling": 3,
    })
    return normalize_chapter_outline(
        DraftChapterOutline.model_validate({
            "schemaVersion": "chapter-outline-v1", "chapterNumber": 1,
            "planningRevisionId": PLANNING_ID, "planningRevision": 1,
            "planningHash": planning.content_hash,
            "volumeRef": _ref(planning.volumes[0]),
            "storyBlockRef": _ref(block),
            "stageRefs": [_ref(block.stages[0])],
            "sceneTaskRefs": [_ref(block.stages[0].scene_tasks[0])],
            "chapterGoal": "进入城中。", "expectedCharacters": ["主角"],
            "continuation": [], "plannedTasks": ["应对盘查。"],
            "scenes": ["城门"], "forbiddenEarlyEvents": [],
            "capacityPolicy": capacity.model_dump(by_alias=True, mode="json"),
        }),
        planning=planning, authoritative_chapter_number=1,
        planning_revision_id=PLANNING_ID, planning_revision=1,
        capacity_policy=capacity, canon_revision=0, projection_revision=0,
        projection_hash=projection_hash,
    )


def _change_set(planning, content):
    evidence = {
        "startScalar": 0, "endScalar": 2,
        "excerptHash": sha256(content[:2].encode()).hexdigest(),
        "confidence": 1.0, "rationale": "正文直接证据。",
    }
    plot = planning.plots[0]
    block = planning.story_blocks[0]
    return FinalizationChangeSet.model_validate({
        "schemaVersion": "finalization-changeset-v1",
        "title": "第一章", "summary": "主角成功入城。",
        "existingEntityIds": [],
        "entities": [{
            "id": "30000000-0000-4000-8000-000000000001",
            "entityType": "person", "canonicalName": "守门人",
        }],
        "aliases": [{
            "id": "30000000-0000-4000-8000-000000000002",
            "entityId": "30000000-0000-4000-8000-000000000001",
            "alias": "老卒",
        }],
        "canonEvents": [{
            "id": "30000000-0000-4000-8000-000000000003",
            "entityId": "30000000-0000-4000-8000-000000000001",
            "factKind": "dynamic_event", "fieldPath": "location",
            "value": "城门", "evidence": evidence,
            "effectiveStartChapter": 1, "effectiveEndChapter": None,
            "assertionOperator": "equals", "valueCardinality": "single",
        }],
        "storyProgressEvents": [{
            "id": "30000000-0000-4000-8000-000000000004",
            "targetType": "story_block", "targetId": block.id,
            "status": "completed", "evidence": evidence,
        }],
        "planningPatches": [{
            "id": "30000000-0000-4000-8000-000000000005",
            "targetType": "plot", "targetId": plot.id,
            "expectedRevision": plot.revision, "expectedHash": plot.content_hash,
            "fieldPath": "futureDirection", "replacement": "追查城内接头人。",
            "evidence": evidence,
        }],
        "planningSuggestions": [],
    })


async def _seed(session, transaction_factory):
    creation_id, style_id = await _insert_revision_one_contracts(
        session, project_id=PROJECT_ID, binding_id=BINDING_ID,
        seed_id=SEED_ID, seed_revision_id=SEED_REVISION_ID,
        creation_id=CONTRACT_ID, style_id=STYLE_ID,
    )
    bible_content = {"characters": [], "worldRules": []}
    bible_hash = canonical_hash(bible_content)
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,creation_contract_id,creation_hash,
            style_contract_id,style_hash,binding_revision_id,binding_hash,
            policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,1,1,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,'quality-v1',%s,%s,%s)""",
        (BIBLE_ID, PROJECT_ID, SEED_ID, SEED_REVISION_ID, HASH_A,
         creation_id, HASH_B, style_id, HASH_C, BINDING_ID, HASH_A,
         canonical_json(bible_content), bible_hash, NOW),
    )
    await session.execute(
        """UPDATE project_contract_heads SET revision=1,creation_contract_id=%s,
           style_contract_id=%s,creation_hash=%s,style_hash=%s,updated_at=%s
           WHERE project_id=%s""",
        (creation_id, style_id, HASH_B, HASH_C, NOW, PROJECT_ID),
    )
    await session.execute(
        """UPDATE project_bible_heads SET revision=1,bible_revision_id=%s,
           content_hash=%s,updated_at=%s WHERE project_id=%s""",
        (BIBLE_ID, bible_hash, NOW, PROJECT_ID),
    )
    planning = _planning()
    await session.execute(
        """INSERT INTO planning_revisions
           (id,project_id,revision,parent_revision,selection_revision,seed_id,
            seed_revision_id,seed_hash,contract_revision,creation_contract_id,
            creation_hash,style_contract_id,style_hash,bible_revision,
            bible_revision_id,bible_hash,content_json,content_hash,created_at)
           VALUES (%s,%s,1,0,1,%s,%s,%s,1,%s,%s,%s,%s,1,%s,%s,%s,%s,%s)""",
        (PLANNING_ID, PROJECT_ID, SEED_ID, SEED_REVISION_ID, HASH_A,
         creation_id, HASH_B, style_id, HASH_C, BIBLE_ID, bible_hash,
         canonical_json(planning.model_dump(by_alias=True, mode="json")),
         planning.content_hash, NOW),
    )
    await session.execute(
        """UPDATE project_planning_heads SET revision=1,planning_revision_id=%s,
           content_hash=%s,updated_at=%s WHERE project_id=%s""",
        (PLANNING_ID, planning.content_hash, NOW, PROJECT_ID),
    )
    projection_hash = build_projection_bundle(0, ()).content_hash
    await session.execute(
        """INSERT INTO projection_heads
           (project_id,canon_revision_number,projection_revision_number,
            content_hash,updated_at) VALUES (%s,0,0,%s,%s)""",
        (PROJECT_ID, projection_hash, NOW),
    )
    outline = _outline(planning, projection_hash)
    await session.execute(
        """INSERT INTO chapter_outline_revisions
           (id,project_id,chapter_num,revision,parent_revision,
            planning_revision_id,planning_revision,planning_hash,
            canon_revision,projection_revision,projection_hash,content_json,
            content_hash,created_at)
           VALUES (%s,%s,1,1,0,%s,1,%s,0,0,%s,%s,%s,%s)""",
        (OUTLINE_ID, PROJECT_ID, PLANNING_ID, planning.content_hash,
         projection_hash,
         canonical_json(outline.model_dump(by_alias=True, mode="json")),
         outline.content_hash, NOW),
    )
    await session.execute(
        """INSERT INTO project_chapter_outline_heads
           (project_id,chapter_num,revision,outline_revision_id,content_hash,updated_at)
           VALUES (%s,1,1,%s,%s,%s)""",
        (PROJECT_ID, OUTLINE_ID, outline.content_hash, NOW),
    )
    content = "正文证据。" * 30
    content_hash = sha256(content.encode()).hexdigest()
    basis = {
        "schemaVersion": "draft-candidate-basis-v1",
        "outlineRevisionId": OUTLINE_ID, "outlineRevision": 1,
        "outlineHash": outline.content_hash,
        "planningRevisionId": PLANNING_ID, "planningRevision": 1,
        "planningHash": planning.content_hash,
        "canonRevision": 0, "projectionRevision": 0,
        "projectionHash": projection_hash,
    }
    await session.execute(
        """INSERT INTO chapter_sessions
           (id,project_id,planning_revision_id,planning_revision,planning_hash,
            story_block_id,story_block_revision,story_block_hash,
            chapter_outline_revision_id,chapter_outline_revision,
            chapter_outline_hash,chapter_num,expected_canon_revision,status,
            created_at,finalized_at)
           VALUES (%s,%s,%s,1,%s,%s,1,%s,%s,1,%s,1,0,'drafting',%s,NULL)""",
        (SESSION_ID, PROJECT_ID, PLANNING_ID, planning.content_hash,
         planning.story_blocks[0].id, planning.story_blocks[0].content_hash,
         OUTLINE_ID, outline.content_hash, NOW),
    )
    await session.execute(
        """INSERT INTO working_drafts
           (id,project_id,chapter_session_id,revision,content,content_hash,
            source_payload_json,updated_at) VALUES (%s,%s,%s,1,%s,%s,'{}',%s)""",
        (WORKING_ID, PROJECT_ID, SESSION_ID, content, content_hash, NOW),
    )
    await session.execute(
        """INSERT INTO draft_candidates
           (id,project_id,chapter_session_id,working_draft_revision,content,
            content_hash,basis_hash,provenance_json,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s)""",
        (CANDIDATE_ID, PROJECT_ID, SESSION_ID, content, content_hash,
         canonical_hash(basis), canonical_json(basis), NOW),
    )
    repository = FinalizationRepository()
    snapshot = await repository.load_preparation_context(session, PROJECT_ID, 1)
    prepare = PrepareFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        candidate_id=CANDIDATE_ID, candidate_hash=content_hash,
        expected_canon_revision=0, expected_planning_hash=planning.content_hash,
        expected_outline_hash=outline.content_hash, idempotency_key=HASH_A,
    )
    manifest = FinalizationService._context_manifest(prepare, 1, snapshot)
    manifest_hash = canonical_hash(manifest)
    await repository.insert_preparing_attempt(session, {
        "id": ATTEMPT_ID, "project_id": PROJECT_ID,
        "chapter_session_id": SESSION_ID, "draft_candidate_id": CANDIDATE_ID,
        "idempotency_key": HASH_A,
        "request_fingerprint": FinalizationService.request_fingerprint(prepare, snapshot, 1),
        "candidate_hash": content_hash, "expected_canon_revision": 0,
        "expected_planning_hash": planning.content_hash,
        "expected_outline_hash": outline.content_hash,
        "context_manifest": manifest, "context_manifest_hash": manifest_hash,
        "created_at": NOW, "updated_at": NOW,
    })
    report = QualityReportPayload.model_validate({
        "status": "completed", "deterministicBlocks": [], "findings": [],
    })
    report_payload = report.model_dump(by_alias=True, mode="json")
    await repository.insert_quality_report(session, {
        "id": REPORT_ID, "project_id": PROJECT_ID,
        "chapter_session_id": SESSION_ID, "draft_candidate_id": CANDIDATE_ID,
        "candidate_hash": content_hash, "expected_canon_revision": 0,
        "expected_planning_hash": planning.content_hash,
        "expected_outline_hash": outline.content_hash,
        "policy_version": "quality-v1", "context_manifest_hash": manifest_hash,
        "provider_id": None, "provider_profile_revision": None,
        "model_name_snapshot": None, "status": "completed",
        "deterministic_blocks": [], "findings": [],
        "content_hash": canonical_hash(report_payload), "created_at": NOW,
    })
    change_set = _change_set(planning, content)
    revision_hash = change_set_hash(change_set)
    await repository.insert_change_set_revision(session, {
        "id": CHANGE_REVISION_ID, "project_id": PROJECT_ID,
        "change_set_id": ATTEMPT_ID, "revision": 1,
        "change_set": change_set, "content_hash": revision_hash,
        "source": "extraction", "created_at": NOW,
    })
    assert await repository.publish_awaiting_author(
        session, project_id=PROJECT_ID, session_id=SESSION_ID,
        change_set_id=ATTEMPT_ID, report_id=REPORT_ID,
        extraction_id="extraction-1", revision=1,
        revision_hash=revision_hash, updated_at=NOW,
    )
    assert await repository.confirm_current_revision(
        session, project_id=PROJECT_ID, session_id=SESSION_ID,
        change_set_id=ATTEMPT_ID, revision=1,
        revision_hash=revision_hash, confirmed_at=NOW,
    )
    return planning, change_set


class _FailAfterFinalChapter(FinalizationRepository):
    async def insert_final_chapter(self, session, row):
        await super().insert_final_chapter(session, row)
        raise RuntimeError("injected late write failure")


def _service(transaction_factory, repository, ids):
    canon_repository = CanonRepository()
    return AtomicFinalizationService(
        transaction_factory=transaction_factory, repository=repository,
        planning_repository=PlanningRepository(),
        canon_committer=CanonService(
            canon_repository, transaction_factory=transaction_factory,
            id_factory=lambda: "40000000-0000-4000-8000-000000000001",
            clock=lambda: NOW + 1,
        ),
        id_factory=iter(ids).__next__, clock=lambda: NOW + 1,
    )


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_atomic_finalization_rolls_back_late_failure_then_commits_and_replays(
    disposable_mysql,
):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        planning, change_set = await _seed(session, transaction_factory)
    command = CommitFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        idempotency_key=HASH_B, expected_revision=1,
        expected_revision_hash=change_set_hash(change_set),
    )
    failed = _service(transaction_factory, _FailAfterFinalChapter(), (
        "50000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000002",
        "50000000-0000-4000-8000-000000000003",
    ))
    with pytest.raises(RuntimeError, match="injected late write failure"):
        await failed.commit(command)

    async with transaction_factory() as session:
        counts = {}
        for table in ("canon_revisions", "finalization_records", "final_chapters"):
            row = await session.fetchone(
                f"SELECT COUNT(*) AS count_value FROM {table} WHERE project_id=%s",
                (PROJECT_ID,),
            )
            counts[table] = row["count_value"]
        session_row = await session.fetchone(
            "SELECT status,finalized_at FROM chapter_sessions WHERE id=%s",
            (SESSION_ID,),
        )
        attempt = await session.fetchone(
            "SELECT status,active_slot FROM finalization_change_sets WHERE id=%s",
            (ATTEMPT_ID,),
        )
        head = await session.fetchone(
            "SELECT revision,content_hash FROM project_planning_heads WHERE project_id=%s",
            (PROJECT_ID,),
        )
    assert counts == {
        "canon_revisions": 0, "finalization_records": 0, "final_chapters": 0,
    }
    assert session_row == {"status": "drafting", "finalized_at": None}
    assert attempt == {"status": "awaiting_author", "active_slot": 1}
    assert head == {"revision": 1, "content_hash": planning.content_hash}

    service = _service(transaction_factory, FinalizationRepository(), (
        "50000000-0000-4000-8000-000000000011",
        "50000000-0000-4000-8000-000000000012",
        "50000000-0000-4000-8000-000000000013",
    ))
    committed = await service.commit(command)
    replayed = await service.commit(command)
    assert committed.canon_revision == 1
    assert committed.planning_revision == 2
    assert replayed.replayed is True
    assert replayed.record_id == committed.record_id

    with pytest.raises(FinalizationCommitInvalid):
        await service.commit(CommitFinalization(
            project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
            idempotency_key=HASH_C, expected_revision=1,
            expected_revision_hash=change_set_hash(change_set),
        ))

    async with transaction_factory() as session:
        final = await session.fetchone(
            """SELECT chapter.content_hash,chapter.canon_revision,
                      chapter.planning_revision,session.status,
                      attempt.status AS attempt_status,
                      head.canon_revision_number,head.projection_revision_number
                 FROM final_chapters chapter
                 JOIN chapter_sessions session ON session.id=chapter.chapter_session_id
                 JOIN finalization_change_sets attempt ON attempt.id=%s
                 JOIN projection_heads head ON head.project_id=chapter.project_id
                WHERE chapter.project_id=%s""",
            (ATTEMPT_ID, PROJECT_ID),
        )
        progress = await session.fetchone(
            """SELECT field_path,payload_json FROM plot_thread_projections
                WHERE project_id=%s AND field_path LIKE 'plot.progress.%%'""",
            (PROJECT_ID,),
        )
        planning_head = await session.fetchone(
            "SELECT revision,content_hash FROM project_planning_heads WHERE project_id=%s",
            (PROJECT_ID,),
        )
    assert final == {
        "content_hash": sha256(("正文证据。" * 30).encode()).hexdigest(),
        "canon_revision": 1, "planning_revision": 1,
        "status": "final", "attempt_status": "committed",
        "canon_revision_number": 1, "projection_revision_number": 1,
    }
    assert progress["field_path"].startswith("plot.progress.story_block.")
    assert planning_head["revision"] == 2
    assert planning_head["content_hash"] != planning.content_hash
