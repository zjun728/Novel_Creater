from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

import pytest

from backend.domain.chapter_outlines import (
    DraftChapterOutline,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.contracts import ContractRepository
from backend.repositories.planning import PlanningRepository
from backend.services.chapter_sessions import (
    ChapterSessionConflict,
    ChapterSessionService,
    CreateChapterSession,
)
from backend.services.contracts import (
    ConfirmContracts,
    ContractService,
    SaveContractDraft,
)
from backend.services.planning import (
    ConfirmPlanningDraft,
    CreatePlanningDraft,
    PlanningConflict,
    PlanningPreconditionFailed,
    PlanningService,
    SavePlanningDraft,
)
from backend.services.projections import build_projection_bundle
from backend.tests.integration.test_contract_drafts import (
    PROJECT,
    SEED,
    _bootstrap,
    _draft,
)
from backend.tests.integration.test_project_archive import _insert_confirmed_bible
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql

NOW = 1_930_000_000_000
SEED_B = "97000000-0000-0000-0000-000000000001"
SEED_B_REVISION = "97000000-0000-0000-0000-000000000002"


def _payload(title: str = "第一卷"):
    return {
        "activeStoryBlockRef": "block",
        "volumes": [
            {
                "clientNodeKey": "volume",
                "order": 1,
                "title": title,
                "coreChange": "主角建立第一个可靠据点。",
                "mainPressure": "追兵逼近。",
                "ensembleFocus": ["主角", "同伴"],
                "forbiddenEvents": ["不可提前揭示幕后人"],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "plot",
                "order": 1,
                "title": "立足主线",
                "plotType": "main",
                "storyQuestion": "主角如何活下来？",
                "futureDirection": "从逃亡转为主动布局。",
                "expectedPayoff": "建立据点。",
                "relatedCharacters": ["主角"],
            }
        ],
        "storyBlocks": [
            {
                "clientNodeKey": "block",
                "order": 1,
                "title": "夜渡封锁线",
                "volumeRef": "volume",
                "plotRefs": ["plot"],
                "entrySituation": "二人被困。",
                "blockGoal": "穿过封锁线。",
                "mainPressure": "追兵压缩路线。",
                "expectedChange": "二人建立信任。",
                "openQuestions": ["内应是谁"],
                "involvedCharacters": ["主角", "同伴"],
                "stages": [
                    {
                        "clientNodeKey": "stage",
                        "order": 1,
                        "title": "寻找缺口",
                        "purpose": "确认封锁薄弱处。",
                        "dramaticQuestion": "能否在暴露前找到缺口？",
                        "sceneTasks": [
                            {
                                "clientNodeKey": "task",
                                "order": 1,
                                "task": "观察换岗。",
                                "completionEvidence": "取得换岗间隔。",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _editable(content, *, title: str | None = None):
    payload = content.model_dump(mode="json", by_alias=True)
    payload["activeStoryBlockRef"] = payload.pop("activeStoryBlockId")
    payload.pop("schemaVersion")
    payload.pop("contentHash")
    for volume in payload["volumes"]:
        if title is not None:
            volume["title"] = title
    for block in payload["storyBlocks"]:
        block["volumeRef"] = block.pop("volumeId")
        block["plotRefs"] = block.pop("plotIds")
        for stage in block["stages"]:
            stage.pop("storyBlockId")
            for task in stage["sceneTasks"]:
                task.pop("stageId")
    return payload


async def _prepare(disposable_mysql, *, failpoint=None):
    facts = await _bootstrap(disposable_mysql.session)
    transaction = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    ids = iter(
        f"95000000-0000-0000-0000-{number:012d}"
        for number in range(1, 1000)
    )
    contracts = ContractService(
        ContractRepository(),
        transaction_factory=transaction,
        connection_factory=read_connection,
        id_factory=ids.__next__,
        clock=lambda: NOW,
    )
    saved = await contracts.save_draft(
        SaveContractDraft(PROJECT, 0, _draft(facts))
    )
    confirmed = await contracts.confirm(
        ConfirmContracts(
            PROJECT,
            "planning-contract-confirm",
            saved.draft_version,
            saved.content_hash,
        )
    )
    await _insert_confirmed_bible(
        disposable_mysql.session,
        confirmed,
        bible_id="95000000-0000-0000-0001-000000000001",
        now=NOW,
    )
    bundle = build_projection_bundle(0, ())
    await disposable_mysql.session.execute(
        """INSERT INTO canon_revisions
           (id,project_id,revision_number,parent_revision_number,
            idempotency_key,source_type,source_id,content_hash,created_at)
           VALUES ('95000000-0000-0000-0001-000000000002',%s,0,0,
                   'planning-bootstrap','bootstrap',NULL,%s,%s)""",
        (PROJECT, bundle.content_hash, NOW),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO projection_heads
           (project_id,canon_revision_number,projection_revision_number,
            content_hash,updated_at)
           VALUES (%s,0,0,%s,%s)""",
        (PROJECT, bundle.content_hash, NOW),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_planning_heads
           (project_id,revision,planning_revision_id,content_hash,updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (PROJECT, NOW),
    )
    service = PlanningService(
        PlanningRepository(),
        transaction_factory=transaction,
        id_factory=ids.__next__,
        clock=lambda: NOW,
        failpoint=failpoint,
    )
    selected = await disposable_mysql.session.fetchone(
        "SELECT DATABASE() AS database_name"
    )
    assert selected["database_name"] == disposable_mysql.database_name
    return service


async def _save_complete(service):
    draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-planning")
    )
    return await service.save_draft(
        SavePlanningDraft(
            PROJECT,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            _payload(),
            "save-planning",
        )
    )


async def _snapshot(session):
    tables = (
        "planning_drafts",
        "planning_revisions",
        "project_planning_heads",
        "planning_confirmation_requests",
        "canon_revisions",
        "projection_heads",
    )
    return {
        table: tuple(
            await session.fetchall(
                f"SELECT * FROM {table} WHERE project_id=%s ORDER BY 1",
                (PROJECT,),
            )
        )
        for table in tables
    }


def _node_ref(node):
    return {
        "id": node.id,
        "revision": node.revision,
        "contentHash": node.content_hash,
    }


async def _insert_outline_for_planning(session, revision):
    projection = await session.fetchone(
        "SELECT * FROM projection_heads WHERE project_id=%s",
        (PROJECT,),
    )
    volume = revision.content.volumes[0]
    block = revision.content.story_blocks[0]
    stage = block.stages[0]
    task = stage.scene_tasks[0]
    capacity = OutlineCapacityPolicy.model_validate(
        {"targetMin": 3000, "targetMax": 5000, "softCeiling": 5000}
    )
    outline = normalize_chapter_outline(
        DraftChapterOutline.model_validate(
            {
                "schemaVersion": "chapter-outline-v1",
                "chapterNumber": 1,
                "planningRevisionId": revision.planning_revision_id,
                "planningRevision": revision.revision,
                "planningHash": revision.content_hash,
                "volumeRef": _node_ref(volume),
                "storyBlockRef": _node_ref(block),
                "stageRefs": [_node_ref(stage)],
                "sceneTaskRefs": [_node_ref(task)],
                "chapterGoal": "找到封锁线缺口。",
                "expectedCharacters": ["主角", "同伴"],
                "continuation": ["承接被困局面"],
                "plannedTasks": ["观察换岗"],
                "scenes": ["废弃驿站侦察"],
                "forbiddenEarlyEvents": ["不可提前揭示内应"],
                "capacityPolicy": capacity.model_dump(
                    mode="json",
                    by_alias=True,
                ),
            }
        ),
        planning=revision.content,
        authoritative_chapter_number=1,
        planning_revision_id=revision.planning_revision_id,
        planning_revision=revision.revision,
        capacity_policy=capacity,
        canon_revision=projection["canon_revision_number"],
        projection_revision=projection["projection_revision_number"],
        projection_hash=projection["content_hash"],
    )
    outline_id = "98000000-0000-0000-0000-000000000001"
    await session.execute(
        """INSERT INTO chapter_outline_revisions
           (id,project_id,chapter_num,revision,parent_revision,
            planning_revision_id,planning_revision,planning_hash,
            canon_revision,projection_revision,projection_hash,
            content_json,content_hash,created_at)
           VALUES (%s,%s,1,1,0,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            outline_id,
            PROJECT,
            revision.planning_revision_id,
            revision.revision,
            revision.content_hash,
            projection["canon_revision_number"],
            projection["projection_revision_number"],
            projection["content_hash"],
            canonical_json(outline.model_dump(mode="json", by_alias=True)),
            outline.content_hash,
            NOW + 1,
        ),
    )
    await session.execute(
        """INSERT INTO project_chapter_outline_heads
           (project_id,chapter_num,revision,outline_revision_id,
            content_hash,updated_at)
           VALUES (%s,1,1,%s,%s,%s)""",
        (PROJECT, outline_id, outline.content_hash, NOW + 1),
    )
    return outline


@pytest.mark.asyncio
async def test_real_mysql_lifecycle_is_zero_to_one_to_two_with_exact_clone(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    first_draft = await _save_complete(service)
    first = await service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            first_draft.draft_id,
            first_draft.draft_revision,
            first_draft.content_hash,
            "confirm-planning-1",
        )
    )

    clone = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-adjustment")
    )
    assert clone.base_head_revision == 1
    assert clone.content == first.content
    assert clone.content_hash == first.content_hash
    assert canonical_json(
        clone.content.model_dump(mode="json", by_alias=True)
    ) == canonical_json(first.content.model_dump(mode="json", by_alias=True))

    adjusted = await service.save_draft(
        SavePlanningDraft(
            PROJECT,
            clone.draft_id,
            clone.draft_revision,
            clone.content_hash,
            _editable(clone.content, title="第二版第一卷"),
            "save-adjustment",
        )
    )
    second = await service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            adjusted.draft_id,
            adjusted.draft_revision,
            adjusted.content_hash,
            "confirm-planning-2",
        )
    )
    history = await service.history(PROJECT)

    assert (first.revision, second.revision) == (1, 2)
    assert tuple(item.revision for item in history) == (2, 1)
    assert history[1].content == first.content
    assert history[1].content_hash == first.content_hash
    assert history[1].planning_revision_id == first.planning_revision_id
    assert history[1].display_status == "superseded"
    head = await disposable_mysql.session.fetchone(
        "SELECT * FROM project_planning_heads WHERE project_id=%s",
        (PROJECT,),
    )
    assert head["revision"] == 2


@pytest.mark.asyncio
async def test_real_mysql_history_and_capabilities_derive_from_current_authority(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    first_saved = await _save_complete(service)
    await service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            first_saved.draft_id,
            first_saved.draft_revision,
            first_saved.content_hash,
            "confirm-history-status-1",
        )
    )
    second_draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-history-status-2")
    )
    second_saved = await service.save_draft(
        SavePlanningDraft(
            PROJECT,
            second_draft.draft_id,
            second_draft.draft_revision,
            second_draft.content_hash,
            _editable(second_draft.content, title="第二版第一卷"),
            "save-history-status-2",
        )
    )
    await service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            second_saved.draft_id,
            second_saved.draft_revision,
            second_saved.content_hash,
            "confirm-history-status-2",
        )
    )
    active_draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-history-status-3")
    )

    state = await service.get_state(PROJECT)
    history = await service.history(PROJECT)

    assert state.project_lifecycle == "active"
    assert state.basis_status == "current"
    assert state.draft.draft_id == active_draft.draft_id
    assert state.capabilities.generate is True
    assert [
        (item.display_status, item.display_reason) for item in history
    ] == [
        ("current", "currentPlanningHead"),
        ("superseded", "newerPlanningOrBasis"),
    ]

    await disposable_mysql.session.execute(
        "UPDATE projects SET archived_at=%s WHERE id=%s",
        (NOW + 20, PROJECT),
    )
    archived_state = await service.get_state(PROJECT)
    archived_history = await service.history(PROJECT)
    assert archived_state.project_lifecycle == "archived"
    assert archived_state.capabilities.generate is False
    assert archived_state.capabilities.edit is False
    assert {
        (item.display_status, item.display_reason)
        for item in archived_history
    } == {("archived", "projectArchived")}


class _PlanningReadBarrierRepository(PlanningRepository):
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.armed = True

    def rearm(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.armed = True

    async def lock_active_project(self, session, project_id):
        row = await super().lock_active_project(session, project_id)
        if self.armed:
            self.armed = False
            self.entered.set()
            await self.release.wait()
        return row


class _PlanningConfirmProbeRepository(PlanningRepository):
    def __init__(self):
        self.lock_attempted = asyncio.Event()

    def rearm(self):
        self.lock_attempted = asyncio.Event()

    async def lock_active_project(self, session, project_id):
        self.lock_attempted.set()
        return await super().lock_active_project(session, project_id)


@pytest.mark.asyncio
async def test_real_mysql_planning_reads_fence_concurrent_confirmation(
    disposable_mysql,
):
    writer = await _prepare(disposable_mysql)
    first_saved = await _save_complete(writer)
    await writer.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            first_saved.draft_id,
            first_saved.draft_revision,
            first_saved.content_hash,
            "confirm-read-barrier-1",
        )
    )
    second_draft = await writer.create_draft(
        CreatePlanningDraft(PROJECT, "create-read-barrier-2")
    )
    second_saved = await writer.save_draft(
        SavePlanningDraft(
            PROJECT,
            second_draft.draft_id,
            second_draft.draft_revision,
            second_draft.content_hash,
            _editable(second_draft.content, title="读事务第二版"),
            "save-read-barrier-2",
        )
    )
    second_command = ConfirmPlanningDraft(
        PROJECT,
        second_saved.draft_id,
        second_saved.draft_revision,
        second_saved.content_hash,
        "confirm-read-barrier-2",
    )
    transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )
    barrier = _PlanningReadBarrierRepository()
    reader = PlanningService(
        barrier,
        transaction_factory=transaction,
    )
    confirm_probe = _PlanningConfirmProbeRepository()
    writer.repository = confirm_probe

    history_task = asyncio.create_task(reader.history(PROJECT))
    await asyncio.wait_for(barrier.entered.wait(), timeout=1)
    confirm_probe.rearm()
    confirm_two_task = asyncio.create_task(
        writer.confirm_draft(second_command)
    )
    await asyncio.wait_for(confirm_probe.lock_attempted.wait(), timeout=1)
    assert confirm_two_task.done() is False
    barrier.release.set()
    history_before = await history_task
    second_revision = await confirm_two_task

    assert [
        (item.revision, item.display_status) for item in history_before
    ] == [(1, "current")]
    assert second_revision.revision == 2

    third_draft = await writer.create_draft(
        CreatePlanningDraft(PROJECT, "create-read-barrier-3")
    )
    third_saved = await writer.save_draft(
        SavePlanningDraft(
            PROJECT,
            third_draft.draft_id,
            third_draft.draft_revision,
            third_draft.content_hash,
            _editable(third_draft.content, title="读事务第三版"),
            "save-read-barrier-3",
        )
    )
    third_command = ConfirmPlanningDraft(
        PROJECT,
        third_saved.draft_id,
        third_saved.draft_revision,
        third_saved.content_hash,
        "confirm-read-barrier-3",
    )
    barrier.rearm()
    confirm_probe.rearm()
    state_task = asyncio.create_task(reader.get_state(PROJECT))
    await asyncio.wait_for(barrier.entered.wait(), timeout=1)
    confirm_three_task = asyncio.create_task(
        writer.confirm_draft(third_command)
    )
    await asyncio.wait_for(confirm_probe.lock_attempted.wait(), timeout=1)
    assert confirm_three_task.done() is False
    barrier.release.set()
    state_before = await state_task
    third_revision = await confirm_three_task

    assert state_before.project_lifecycle == "active"
    assert state_before.basis_status == "current"
    assert state_before.head.revision == 2
    assert state_before.draft.draft_id == third_draft.draft_id
    assert state_before.capabilities.generate is True
    assert third_revision.revision == 3
    final_history = await reader.history(PROJECT)
    assert sum(
        item.display_status == "current" for item in final_history
    ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "drifted_value"),
    (
        ("revision", 99),
        ("planning_revision_id", "99000000-0000-0000-0000-000000000001"),
        ("content_hash", "f" * 64),
    ),
)
async def test_real_mysql_head_cas_rejects_each_drifted_expected_pin(
    disposable_mysql,
    field,
    drifted_value,
):
    service = await _prepare(disposable_mysql)
    saved = await _save_complete(service)
    await service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved.draft_id,
            saved.draft_revision,
            saved.content_hash,
            f"confirm-cas-{field}",
        )
    )
    actual = await disposable_mysql.session.fetchone(
        "SELECT * FROM project_planning_heads WHERE project_id=%s",
        (PROJECT,),
    )
    expected = dict(actual)
    expected[field] = drifted_value
    transaction = transaction_factory_for(
        disposable_mysql.connection_config,
    )
    async with transaction() as session:
        changed = await PlanningRepository().advance_head_cas(
            session,
            dict(actual),
            expected,
        )

    assert changed is False
    assert (
        await disposable_mysql.session.fetchone(
            "SELECT * FROM project_planning_heads WHERE project_id=%s",
            (PROJECT,),
        )
    ) == actual


@pytest.mark.asyncio
async def test_real_mysql_stale_save_preserves_authoritative_draft(disposable_mysql):
    service = await _prepare(disposable_mysql)
    draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-planning")
    )
    saved = await service.save_draft(
        SavePlanningDraft(
            PROJECT,
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            _payload(),
            "save-current",
        )
    )
    before = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s", (draft.draft_id,)
    )

    with pytest.raises(PlanningConflict, match="draft revision"):
        await service.save_draft(
            SavePlanningDraft(
                PROJECT,
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                _payload("stale"),
                "save-stale",
            )
        )
    after = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s", (draft.draft_id,)
    )
    assert after == before
    assert after["draft_revision"] == saved.draft_revision


async def _insert_seed_b(session):
    payload = {
        "title": "Seed B",
        "genre": "fantasy",
        "logline": "A genuinely different integration seed.",
        "protagonist": "B",
        "desire": "Prove generation isolation.",
        "coreConflict": "Seed B must never borrow Seed A Planning.",
        "worldPressure": "The generation changes.",
        "openingHook": "A new seed is selected.",
        "differentiation": "Distinct seed identity and hash.",
    }
    seed_hash = canonical_hash(payload)
    await session.execute(
        """INSERT INTO creative_seeds
           (id,project_id,status,created_at,updated_at)
           VALUES (%s,%s,'candidate',%s,%s)""",
        (SEED_B, PROJECT, NOW + 2, NOW + 2),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (
            SEED_B_REVISION,
            PROJECT,
            SEED_B,
            canonical_json(payload),
            seed_hash,
            NOW + 2,
        ),
    )
    await session.execute(
        """INSERT INTO creative_seed_heads
           (seed_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (SEED_B, SEED_B_REVISION, seed_hash, NOW + 2),
    )


async def _advance_basis(
    session,
    revision: int,
    suffix: str,
    *,
    target_seed_id: str,
    target_seed_revision_id: str,
):
    previous = revision - 1
    target_seed = await session.fetchone(
        """SELECT seed_id,id AS seed_revision_id,content_hash AS seed_hash
             FROM creative_seed_revisions
            WHERE project_id=%s AND seed_id=%s AND id=%s""",
        (PROJECT, target_seed_id, target_seed_revision_id),
    )
    assert target_seed is not None
    contract = await session.fetchone(
        """SELECT creation.* FROM creation_contracts creation
             JOIN project_contract_heads head
               ON head.creation_contract_id=creation.id
            WHERE head.project_id=%s""",
        (PROJECT,),
    )
    style = await session.fetchone(
        """SELECT style.* FROM style_contracts style
             JOIN project_contract_heads head ON head.style_contract_id=style.id
            WHERE head.project_id=%s""",
        (PROJECT,),
    )
    bible = await session.fetchone(
        """SELECT bible.* FROM creation_bible_revisions bible
             JOIN project_bible_heads head ON head.bible_revision_id=bible.id
            WHERE head.project_id=%s""",
        (PROJECT,),
    )
    creation_id = f"96000000-0000-0000-{revision:04d}-000000000001"
    style_id = f"96000000-0000-0000-{revision:04d}-000000000002"
    bible_id = f"96000000-0000-0000-{revision:04d}-000000000003"
    await session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,
            selected_at)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (
            PROJECT,
            revision,
            target_seed["seed_id"],
            target_seed["seed_revision_id"],
            target_seed["seed_hash"],
            NOW + revision,
        ),
    )
    creation_hash = suffix * 64
    style_hash = chr(ord(suffix) + 1) * 64
    bible_hash = chr(ord(suffix) + 2) * 64
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,binding_revision_id,binding_hash,channel_profile_key,
            genre_profile_key,quality_charter_version,total_word_min,
            total_word_max,chapter_capacity_policy,reference_manifest_json,
            reference_manifest_hash,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   %s,%s,%s)""",
        (
            creation_id,
            PROJECT,
            revision,
            revision,
            target_seed["seed_id"],
            target_seed["seed_revision_id"],
            target_seed["seed_hash"],
            contract["binding_revision_id"],
            contract["binding_hash"],
            contract["channel_profile_key"],
            contract["genre_profile_key"],
            contract["quality_charter_version"],
            contract["total_word_min"],
            contract["total_word_max"],
            contract["chapter_capacity_policy"],
            contract["reference_manifest_json"],
            contract["reference_manifest_hash"],
            contract["content_json"],
            creation_hash,
            NOW + revision,
        ),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            style_id,
            PROJECT,
            creation_id,
            revision,
            style["merged_style_json"],
            style["likes_json"],
            style["dislikes_json"],
            style_hash,
            NOW + revision,
        ),
    )
    await session.execute(
        """INSERT INTO creation_bible_revisions
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,contract_revision,creation_contract_id,creation_hash,
            style_contract_id,style_hash,binding_revision_id,binding_hash,
            policy_version,content_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            bible_id,
            PROJECT,
            revision,
            revision,
            target_seed["seed_id"],
            target_seed["seed_revision_id"],
            target_seed["seed_hash"],
            revision,
            creation_id,
            creation_hash,
            style_id,
            style_hash,
            bible["binding_revision_id"],
            bible["binding_hash"],
            bible["policy_version"],
            bible["content_json"],
            bible_hash,
            NOW + revision,
        ),
    )
    await session.execute(
        """UPDATE project_contract_heads SET revision=%s,
                  creation_contract_id=%s,style_contract_id=%s,
                  creation_hash=%s,style_hash=%s,updated_at=%s
            WHERE project_id=%s AND revision=%s""",
        (
            revision,
            creation_id,
            style_id,
            creation_hash,
            style_hash,
            NOW + revision,
            PROJECT,
            previous,
        ),
    )
    await session.execute(
        """UPDATE project_bible_heads SET revision=%s,bible_revision_id=%s,
                  content_hash=%s,updated_at=%s
            WHERE project_id=%s AND revision=%s""",
        (
            revision,
            bible_id,
            bible_hash,
            NOW + revision,
            PROJECT,
            previous,
        ),
    )
    await session.execute(
        """UPDATE project_selected_seeds
              SET seed_id=%s,seed_revision_id=%s,seed_hash=%s,
                  selection_revision=%s,selected_at=%s,updated_at=%s
            WHERE project_id=%s AND selection_revision=%s""",
        (
            target_seed["seed_id"],
            target_seed["seed_revision_id"],
            target_seed["seed_hash"],
            revision,
            NOW + revision,
            NOW + revision,
            PROJECT,
            previous,
        ),
    )


@pytest.mark.asyncio
async def test_real_mysql_a_to_b_to_a_generation_never_reactivates_old_draft(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    first = await service.create_draft(CreatePlanningDraft(PROJECT, "create-a"))
    await _insert_seed_b(disposable_mysql.session)
    await _advance_basis(
        disposable_mysql.session,
        2,
        "4",
        target_seed_id=SEED_B,
        target_seed_revision_id=SEED_B_REVISION,
    )
    with pytest.raises(PlanningPreconditionFailed, match="superseded"):
        await service.save_draft(
            SavePlanningDraft(
                PROJECT,
                first.draft_id,
                first.draft_revision,
                first.content_hash,
                _payload(),
                "stale-a",
            )
        )
    second = await service.create_draft(CreatePlanningDraft(PROJECT, "create-b"))
    original_seed = await disposable_mysql.session.fetchone(
        """SELECT id FROM creative_seed_revisions
            WHERE project_id=%s AND seed_id=%s AND revision=1""",
        (PROJECT, SEED),
    )
    await _advance_basis(
        disposable_mysql.session,
        3,
        "7",
        target_seed_id=SEED,
        target_seed_revision_id=original_seed["id"],
    )
    with pytest.raises(PlanningPreconditionFailed, match="superseded"):
        await service.save_draft(
            SavePlanningDraft(
                PROJECT,
                second.draft_id,
                second.draft_revision,
                second.content_hash,
                _payload(),
                "stale-b",
            )
        )
    third = await service.create_draft(CreatePlanningDraft(PROJECT, "create-a3"))

    assert len({first.draft_id, second.draft_id, third.draft_id}) == 3
    rows = await disposable_mysql.session.fetchall(
        """SELECT id,status,active_slot,selection_revision,seed_id,seed_hash
             FROM planning_drafts WHERE project_id=%s ORDER BY created_at,id""",
        (PROJECT,),
    )
    assert [row["status"] for row in rows].count("active") == 1
    assert {row["selection_revision"] for row in rows} == {1, 2, 3}
    first_row = next(row for row in rows if row["id"] == first.draft_id)
    second_row = next(row for row in rows if row["id"] == second.draft_id)
    third_row = next(row for row in rows if row["id"] == third.draft_id)
    assert first_row["status"] == second_row["status"] == "superseded"
    assert third_row["status"] == "active"
    assert (first_row["seed_id"], second_row["seed_id"], third_row["seed_id"]) == (
        SEED,
        SEED_B,
        SEED,
    )
    assert first_row["seed_hash"] == third_row["seed_hash"]
    assert second_row["seed_hash"] != first_row["seed_hash"]


@pytest.mark.asyncio
async def test_real_mysql_confirmed_planning_and_session_are_history_after_generation_change(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    saved_a = await _save_complete(service)
    confirm_a = ConfirmPlanningDraft(
        PROJECT,
        saved_a.draft_id,
        saved_a.draft_revision,
        saved_a.content_hash,
        "confirm-a-with-session",
    )
    revision_a = await service.confirm_draft(confirm_a)
    outline_a = await _insert_outline_for_planning(
        disposable_mysql.session,
        revision_a,
    )
    transaction = transaction_factory_for(
        disposable_mysql.connection_config,
    )
    chapter_service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction,
    )
    chapter_command = CreateChapterSession(
        project_id=PROJECT,
        chapter_number=1,
        expected_planning_revision=revision_a.revision,
        expected_planning_hash=revision_a.content_hash,
        expected_outline_revision=1,
        expected_outline_hash=outline_a.content_hash,
        expected_canon_revision=0,
    )
    chapter_a = await chapter_service.create_session(chapter_command)
    before_counts = {
        table: (
            await disposable_mysql.session.fetchone(
                f"SELECT COUNT(*) AS count FROM {table} WHERE project_id=%s",
                (PROJECT,),
            )
        )["count"]
        for table in ("chapter_sessions", "working_drafts")
    }

    await _insert_seed_b(disposable_mysql.session)
    await _advance_basis(
        disposable_mysql.session,
        2,
        "4",
        target_seed_id=SEED_B,
        target_seed_revision_id=SEED_B_REVISION,
    )
    before_replay = await _snapshot(disposable_mysql.session)
    replay_a = await service.confirm_draft(confirm_a)
    assert replay_a == revision_a
    assert await _snapshot(disposable_mysql.session) == before_replay
    state_b = await service.get_state(PROJECT)
    assert state_b.basis_status == "current"
    assert state_b.future_plan is None
    with pytest.raises(ChapterSessionConflict, match="generation"):
        await chapter_service.create_session(chapter_command)
    after_counts = {
        table: (
            await disposable_mysql.session.fetchone(
                f"SELECT COUNT(*) AS count FROM {table} WHERE project_id=%s",
                (PROJECT,),
            )
        )["count"]
        for table in ("chapter_sessions", "working_drafts")
    }
    assert after_counts == before_counts == {
        "chapter_sessions": 1,
        "working_drafts": 1,
    }
    persisted = await disposable_mysql.session.fetchone(
        "SELECT id FROM chapter_sessions WHERE project_id=%s",
        (PROJECT,),
    )
    assert persisted["id"] == chapter_a.session.id

    draft_b = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-b-after-confirmed-a")
    )
    assert draft_b.base_head_revision == 1
    assert draft_b.content.volumes == ()
    assert draft_b.content.story_blocks == ()
    saved_b = await service.save_draft(
        SavePlanningDraft(
            PROJECT,
            draft_b.draft_id,
            draft_b.draft_revision,
            draft_b.content_hash,
            _payload("B 第一卷"),
            "save-b-after-confirmed-a",
        )
    )
    revision_b = await service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_b.draft_id,
            saved_b.draft_revision,
            saved_b.content_hash,
            "confirm-b-after-confirmed-a",
        )
    )
    assert (revision_b.revision, revision_b.parent_revision) == (2, 1)
    assert tuple(item.revision for item in await service.history(PROJECT)) == (
        2,
        1,
    )

    original_seed = await disposable_mysql.session.fetchone(
        """SELECT id FROM creative_seed_revisions
            WHERE project_id=%s AND seed_id=%s AND revision=1""",
        (PROJECT, SEED),
    )
    await _advance_basis(
        disposable_mysql.session,
        3,
        "7",
        target_seed_id=SEED,
        target_seed_revision_id=original_seed["id"],
    )
    state_a3 = await service.get_state(PROJECT)
    assert state_a3.future_plan is None
    draft_a3 = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-a3-after-b")
    )
    assert draft_a3.base_head_revision == 2
    assert draft_a3.content.volumes == ()
    assert draft_a3.content.story_blocks == ()


@pytest.mark.parametrize(
    "stage",
    (
        "after_confirmation_pending",
        "after_revision_insert",
        "after_head_advance",
        "after_draft_confirmed",
        "after_confirmation_succeeded",
    ),
)
@pytest.mark.asyncio
async def test_real_mysql_each_confirmation_write_failpoint_rolls_back(
    disposable_mysql, stage
):
    def failpoint(current):
        if current == stage:
            raise RuntimeError(f"failpoint:{stage}")

    service = await _prepare(disposable_mysql, failpoint=failpoint)
    saved = await _save_complete(service)
    before = await _snapshot(disposable_mysql.session)

    with pytest.raises(RuntimeError, match=f"failpoint:{stage}"):
        await service.confirm_draft(
            ConfirmPlanningDraft(
                PROJECT,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                f"confirm-{stage}",
            )
        )

    assert await _snapshot(disposable_mysql.session) == before


@pytest.mark.asyncio
async def test_real_mysql_projection_mismatch_has_zero_planning_or_fact_writes(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    saved = await _save_complete(service)
    await disposable_mysql.session.execute(
        """UPDATE projection_heads SET canon_revision_number=1
            WHERE project_id=%s""",
        (PROJECT,),
    )
    before = await _snapshot(disposable_mysql.session)

    with pytest.raises(PlanningPreconditionFailed, match="Projection"):
        await service.confirm_draft(
            ConfirmPlanningDraft(
                PROJECT,
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                "confirm-projection-mismatch",
            )
        )

    assert await _snapshot(disposable_mysql.session) == before
