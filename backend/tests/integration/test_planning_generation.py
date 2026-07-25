from __future__ import annotations

import asyncio
import json

import pytest

from backend.domain.bibles import BiblePayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.repositories.planning import PlanningRepository
from backend.services.planning import CreatePlanningDraft
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.integration.test_contract_drafts import PROJECT
from backend.tests.integration.test_planning_aggregate_lifecycle import _prepare


pytestmark = pytest.mark.mysql

NOW = 1_940_000_000_000


def _confirmed_story_bible():
    payload = BiblePayload.model_validate(
        {
            "premiseAndPromise": (
                "一个被追捕的记录者必须保存真相，同时承担公开真相的关系代价。"
            ),
            "worldRules": (
                {
                    "id": "world-rule-1",
                    "text": "任何超常力量都必须留下可追踪且不可撤销的代价。",
                },
            ),
            "powerOrProgressionSystem": (
                "成长依靠选择、训练和有限资源，不允许无依据跃升。"
            ),
            "protagonist": "主角谨慎、重视证据，并会承担自己选择的后果。",
            "coreCast": (
                {
                    "id": "cast-1",
                    "text": "同伴拥有独立目标，不是主角的功能性附庸。",
                },
            ),
            "factions": (
                {
                    "id": "faction-1",
                    "text": "地方势力围绕安全、秩序与真相形成竞争。",
                },
            ),
            "longTermConflicts": (
                {
                    "id": "conflict-1",
                    "text": "保存真相与维持眼前秩序的冲突会逐步升级。",
                },
            ),
            "relationshipDynamics": (
                {
                    "id": "relationship-1",
                    "text": "信任只能通过共同选择和公开代价逐步建立。",
                },
            ),
            "toneAndNarrativeBoundaries": (
                "保持克制，让人物行动承担情绪和选择的后果。"
            ),
            "continuityGuardrails": (
                {
                    "id": "guardrail-1",
                    "text": "已经付出的代价不能被无条件撤销。",
                },
            ),
            "openDesignQuestions": (
                {
                    "id": "question-1",
                    "text": "第一阶段需要决定哪段关系最先承受代价。",
                },
            ),
        },
        strict=True,
    )
    return payload.model_dump(mode="json", by_alias=True)


async def _prepare_generation_basis(disposable_mysql):
    planning = await _prepare(disposable_mysql)
    content = _confirmed_story_bible()
    content_hash = canonical_hash(content)
    head = await disposable_mysql.session.fetchone(
        """SELECT bible_revision_id,revision,updated_at
             FROM project_bible_heads WHERE project_id=%s""",
        (PROJECT,),
    )
    await disposable_mysql.session.execute(
        "DELETE FROM project_bible_heads WHERE project_id=%s",
        (PROJECT,),
    )
    await disposable_mysql.session.execute(
        """UPDATE creation_bible_revisions
              SET content_json=%s,content_hash=%s
            WHERE project_id=%s AND id=%s AND revision=%s""",
        (
            canonical_json(content),
            content_hash,
            PROJECT,
            head["bible_revision_id"],
            head["revision"],
        ),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,%s,%s,%s,%s)""",
        (
            PROJECT,
            head["revision"],
            head["bible_revision_id"],
            content_hash,
            head["updated_at"],
        ),
    )
    return planning


async def _attempt_row(session, draft_id, *, number: int):
    binding = await session.fetchone(
        """SELECT head.binding_revision_id,head.revision AS binding_revision,
                  head.content_hash AS binding_hash,item.provider_id,
                  item.model_name_snapshot
             FROM project_model_binding_heads head
             JOIN project_model_binding_items item
               ON item.binding_revision_id=head.binding_revision_id
              AND item.task_key='planning'
            WHERE head.project_id=%s""",
        (PROJECT,),
    )
    return {
        "id": f"96000000-0000-0000-0000-{number:012d}",
        "project_id": PROJECT,
        "draft_id": draft_id,
        "operation_id": f"operation-{number}",
        "idempotency_key": f"planning-generation-{number}",
        "request_fingerprint": f"{number:x}".rjust(64, "0"),
        "binding_revision_id": binding["binding_revision_id"],
        "binding_revision": binding["binding_revision"],
        "binding_hash": binding["binding_hash"],
        "provider_id": binding["provider_id"],
        "model_name_snapshot": binding["model_name_snapshot"],
        "fencing_token": number,
        "lease_expires_at": NOW + 60_000,
        "input_manifest_json": canonical_json({"draftId": draft_id}),
        "input_manifest_hash": canonical_hash({"draftId": draft_id}),
        "created_at": NOW + number,
        "updated_at": NOW + number,
    }


@pytest.mark.asyncio
async def test_real_mysql_generation_fences_terminal_writes_and_loads_exact_draft(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-generation-draft")
    )
    repository = PlanningRepository()
    first = await _attempt_row(
        disposable_mysql.session,
        draft.draft_id,
        number=1,
    )

    assert await repository.next_fencing_token(
        disposable_mysql.session,
        draft.draft_id,
    ) == 1
    assert await repository.insert_generation_attempt(
        disposable_mysql.session,
        first,
    )
    assert (
        await repository.lock_generation_attempt_by_key(
            disposable_mysql.session,
            PROJECT,
            first["idempotency_key"],
        )
    )["operation_id"] == first["operation_id"]
    assert (
        await repository.lock_generation_attempt(
            disposable_mysql.session,
            PROJECT,
            first["operation_id"],
        )
    )["id"] == first["id"]
    assert (
        await repository.lock_active_generation_attempt(
            disposable_mysql.session,
            draft.draft_id,
        )
    )["id"] == first["id"]
    assert await repository.next_fencing_token(
        disposable_mysql.session,
        draft.draft_id,
    ) == 2
    assert await repository.supersede_generation_attempt(
        disposable_mysql.session,
        project_id=PROJECT,
        operation_id=first["operation_id"],
        fencing_token=1,
        updated_at=NOW + 10,
    )

    first_terminal = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (first["id"],),
    )
    assert first_terminal["status"] == "superseded"
    assert first_terminal["active_slot"] is None

    second = await _attempt_row(
        disposable_mysql.session,
        draft.draft_id,
        number=2,
    )
    assert await repository.insert_generation_attempt(
        disposable_mysql.session,
        second,
    )
    result = {"generated": True, "operation": second["operation_id"]}
    result_json = canonical_json(result)
    result_hash = canonical_hash(result)
    draft_before_stale = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s",
        (draft.draft_id,),
    )
    attempt_before_stale = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (second["id"],),
    )
    assert not await repository.load_generation_result_into_draft(
        disposable_mysql.session,
        project_id=PROJECT,
        draft_id=draft.draft_id,
        expected_revision=draft.draft_revision,
        expected_hash=draft.content_hash,
        operation_id=second["operation_id"],
        fencing_token=1,
        content_json=result_json,
        content_hash=result_hash,
        loaded_at=NOW + 20,
    )
    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s",
        (draft.draft_id,),
    ) == draft_before_stale
    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (second["id"],),
    ) == attempt_before_stale
    assert await repository.load_generation_result_into_draft(
        disposable_mysql.session,
        project_id=PROJECT,
        draft_id=draft.draft_id,
        expected_revision=draft.draft_revision,
        expected_hash=draft.content_hash,
        operation_id=second["operation_id"],
        fencing_token=2,
        content_json=result_json,
        content_hash=result_hash,
        loaded_at=NOW + 21,
    )

    loaded_draft = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s",
        (draft.draft_id,),
    )
    loaded_attempt = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (second["id"],),
    )
    assert loaded_draft["draft_revision"] == draft.draft_revision + 1
    assert loaded_draft["content_hash"] == result_hash
    assert loaded_draft["source_attempt_id"] == second["id"]
    assert loaded_attempt["status"] == "succeeded"
    assert loaded_attempt["active_slot"] is None
    assert loaded_attempt["loaded_draft_revision"] == draft.draft_revision + 1
    assert loaded_attempt["loaded_at"] == NOW + 21
    assert loaded_attempt["updated_at"] == NOW + 21


@pytest.mark.asyncio
async def test_real_mysql_failed_attempt_releases_active_slot_for_next_token(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-failure-draft")
    )
    repository = PlanningRepository()
    attempt = await _attempt_row(
        disposable_mysql.session,
        draft.draft_id,
        number=1,
    )
    assert await repository.insert_generation_attempt(
        disposable_mysql.session,
        attempt,
    )
    assert await repository.fail_generation_attempt(
        disposable_mysql.session,
        project_id=PROJECT,
        operation_id=attempt["operation_id"],
        fencing_token=1,
        failure_code="PlanningProviderFailed",
        updated_at=NOW + 30,
    )
    persisted = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (attempt["id"],),
    )
    assert persisted["status"] == "failed"
    assert persisted["active_slot"] is None
    assert persisted["failure_code"] == "PlanningProviderFailed"
    assert await repository.next_fencing_token(
        disposable_mysql.session,
        draft.draft_id,
    ) == 2


class _FakePlanningGateway:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def generate(
        self, *, provider, model_name, manifest, author_instructions
    ):
        self.calls.append(
            (dict(provider), model_name, manifest, author_instructions)
        )
        return self.output


class _BlockingPlanningGateway(_FakePlanningGateway):
    def __init__(self, output):
        super().__init__(output)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        self.entered.set()
        await self.release.wait()
        return self.output


class _ReplayBarrierPlanningRepository(PlanningRepository):
    def __init__(self):
        self.project_locked = asyncio.Event()
        self.allow_lookup = asyncio.Event()
        self.armed = True

    async def lock_active_project(self, session, project_id):
        row = await super().lock_active_project(session, project_id)
        if self.armed:
            self.armed = False
            self.project_locked.set()
            await self.allow_lookup.wait()
        return row


@pytest.mark.asyncio
async def test_real_mysql_service_reserves_and_atomically_loads_generation(
    disposable_mysql,
):
    from backend.services.planning_generation import (
        GeneratePlanningDraft,
        PlanningGenerationService,
    )

    planning = await _prepare_generation_basis(disposable_mysql)
    draft = await planning.create_draft(
        CreatePlanningDraft(PROJECT, "create-service-generation-draft")
    )
    output = {
        "activeStoryBlockRef": None,
        "volumes": [
            {
                "clientNodeKey": "generated-volume",
                "order": 1,
                "title": "AI 第一卷",
                "coreChange": "主角建立第一个据点。",
                "mainPressure": "追兵逼近。",
                "ensembleFocus": ["主角", "同伴"],
                "forbiddenEvents": ["不可提前揭示幕后人"],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "generated-plot",
                "order": 1,
                "title": "立足主线",
                "plotType": "main",
                "storyQuestion": "主角如何站稳脚跟？",
                "futureDirection": "从逃亡转向主动布局。",
                "expectedPayoff": "建立据点。",
                "relatedCharacters": ["主角"],
            }
        ],
        "storyBlocks": [],
    }
    gateway = _FakePlanningGateway(output)
    identifiers = iter(
        f"98000000-0000-0000-0000-{number:012d}"
        for number in range(1, 20)
    )
    service = PlanningGenerationService(
        PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        id_factory=identifiers.__next__,
        clock=lambda: NOW + 100,
    )

    result = await service.generate(
        GeneratePlanningDraft(
            project_id=PROJECT,
            draft_id=draft.draft_id,
            draft_revision=draft.draft_revision,
            draft_hash=draft.content_hash,
            idempotency_key="real-service-generation",
            author_instructions="强化群像变化。",
        )
    )

    assert result.status == "succeeded"
    assert result.loaded is True
    assert result.loaded_draft_revision == draft.draft_revision + 1
    assert result.model.model_name == "test-model"
    assert len(gateway.calls) == 1
    manifest = gateway.calls[0][2].model_dump(
        mode="json",
        by_alias=True,
    )
    assert manifest["draft"] == {
        "activeStoryBlockRef": None,
        "volumes": [],
        "plots": [],
        "storyBlocks": [],
    }
    assert manifest["storyContext"]["seed"]["logline"] == (
        "少年以县志镇压黑潮。"
    )
    assert manifest["storyContext"]["engine"]["storyPromise"]
    assert manifest["storyContext"]["engine"]["conflictLoop"]
    assert manifest["storyContext"]["engine"]["endingAnchor"]
    assert manifest["storyContext"]["longFormCapacity"] == {
        "targetTotalWords": 150_000,
        "expectedVolumeCount": 3,
        "expectedChapterCount": 60,
        "chapterWordRangePreference": [2_000, 3_000],
    }
    assert manifest["storyContext"]["premise"] == (
        "一个被追捕的记录者必须保存真相，同时承担公开真相的关系代价。"
    )
    assert manifest["storyContext"]["coreCharacters"] == [
        {
            "id": "cast-1",
            "text": "同伴拥有独立目标，不是主角的功能性附庸。",
        }
    ]
    assert manifest["storyContext"]["relationshipDynamics"] == [
        {
            "id": "relationship-1",
            "text": "信任只能通过共同选择和公开代价逐步建立。",
        }
    ]
    assert manifest["storyContext"]["worldRules"] == [
        {
            "id": "world-rule-1",
            "text": "任何超常力量都必须留下可追踪且不可撤销的代价。",
        }
    ]
    assert manifest["storyContext"]["prohibitedDirections"] == [
        "不写无代价升级"
    ]
    persisted_draft = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s",
        (draft.draft_id,),
    )
    persisted_attempt = await disposable_mysql.session.fetchone(
        """SELECT * FROM planning_generation_attempts
            WHERE operation_id=%s""",
        (result.operation_id,),
    )
    assert persisted_draft["source_attempt_id"] == persisted_attempt["id"]
    assert persisted_attempt["loaded_draft_revision"] == (
        draft.draft_revision + 1
    )
    assert json.loads(persisted_attempt["input_manifest_json"]) == manifest
    assert persisted_attempt["input_manifest_hash"] == canonical_hash(
        manifest
    )
    serialized_manifest = persisted_attempt["input_manifest_json"].casefold()
    assert all(
        marker not in serialized_manifest
        for marker in (
            "corpus",
            "raw_output",
            "prompt",
            "api_key",
            "test-only-key",
            "authorization",
            "_provenance",
            "publicnotes",
        )
    )
    selected = await disposable_mysql.session.fetchone(
        "SELECT DATABASE() AS database_name"
    )
    assert selected["database_name"] == disposable_mysql.database_name


@pytest.mark.asyncio
async def test_real_mysql_same_key_replay_cannot_deadlock_attempt_terminalization(
    disposable_mysql,
):
    from backend.services.planning_generation import (
        GeneratePlanningDraft,
        PlanningGenerationService,
    )

    planning = await _prepare_generation_basis(disposable_mysql)
    draft = await planning.create_draft(
        CreatePlanningDraft(PROJECT, "create-deadlock-regression-draft")
    )
    output = {
        "activeStoryBlockRef": None,
        "volumes": [],
        "plots": [],
        "storyBlocks": [],
    }
    gateway = _BlockingPlanningGateway(output)
    transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )
    identifiers = iter(
        f"99000000-0000-0000-0000-{number:012d}"
        for number in range(1, 20)
    )
    service = PlanningGenerationService(
        PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=identifiers.__next__,
        clock=lambda: NOW + 200,
    )
    command = GeneratePlanningDraft(
        project_id=PROJECT,
        draft_id=draft.draft_id,
        draft_revision=draft.draft_revision,
        draft_hash=draft.content_hash,
        idempotency_key="same-key-deadlock-regression",
        author_instructions="",
    )
    original = asyncio.create_task(service.generate(command))
    await gateway.entered.wait()
    persisted = await disposable_mysql.session.fetchone(
        """SELECT * FROM planning_generation_attempts
            WHERE project_id=%s AND idempotency_key=%s""",
        (PROJECT, command.idempotency_key),
    )
    operation_id = persisted["operation_id"]
    attempt_locked = asyncio.Event()
    replay_repository = _ReplayBarrierPlanningRepository()
    replay_service = PlanningGenerationService(
        replay_repository,
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=lambda: "must-not-allocate-on-replay",
        clock=lambda: NOW + 200,
    )

    async def terminalize_attempt():
        async with transaction() as session:
            attempt = await PlanningRepository().lock_generation_attempt(
                session, PROJECT, operation_id
            )
            attempt_locked.set()
            await replay_repository.project_locked.wait()
            project = await PlanningRepository().lock_active_project(
                session, PROJECT
            )
            assert project is not None
            assert await PlanningRepository().fail_generation_attempt(
                session,
                project_id=PROJECT,
                operation_id=operation_id,
                fencing_token=int(attempt["fencing_token"]),
                failure_code="PlanningProviderFailed",
                updated_at=NOW + 201,
            )

    terminalizer = asyncio.create_task(terminalize_attempt())
    await attempt_locked.wait()
    replay = asyncio.create_task(replay_service.generate(command))
    await replay_repository.project_locked.wait()
    await asyncio.sleep(0)
    replay_repository.allow_lookup.set()
    try:
        replay_result = await asyncio.wait_for(replay, timeout=5)
        await asyncio.wait_for(terminalizer, timeout=5)
    finally:
        gateway.release.set()
    original_result = await asyncio.wait_for(original, timeout=5)
    terminal_replay = await asyncio.wait_for(
        replay_service.generate(command),
        timeout=5,
    )

    assert replay_result.operation_id == operation_id
    assert replay_result.status == "pending"
    assert original_result.operation_id == operation_id
    assert original_result.status == "failed"
    assert terminal_replay.operation_id == operation_id
    assert terminal_replay.status == "failed"
    assert len(gateway.calls) == 1
    remaining = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count
             FROM planning_generation_attempts
            WHERE project_id=%s AND status='pending' AND active_slot=1""",
        (PROJECT,),
    )
    assert remaining["count"] == 0


@pytest.mark.asyncio
async def test_real_mysql_different_key_cannot_deadlock_active_attempt_terminalization(
    disposable_mysql,
):
    from backend.services.planning_generation import (
        GeneratePlanningDraft,
        PlanningGenerationConflict,
        PlanningGenerationService,
    )

    planning = await _prepare_generation_basis(disposable_mysql)
    draft = await planning.create_draft(
        CreatePlanningDraft(PROJECT, "create-different-key-deadlock-draft")
    )
    gateway = _BlockingPlanningGateway(
        {
            "activeStoryBlockRef": None,
            "volumes": [],
            "plots": [],
            "storyBlocks": [],
        }
    )
    transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )
    identifiers = iter(
        f"99100000-0000-0000-0000-{number:012d}"
        for number in range(1, 20)
    )
    service = PlanningGenerationService(
        PlanningRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=identifiers.__next__,
        clock=lambda: NOW + 300,
    )
    original_command = GeneratePlanningDraft(
        project_id=PROJECT,
        draft_id=draft.draft_id,
        draft_revision=draft.draft_revision,
        draft_hash=draft.content_hash,
        idempotency_key="different-key-original",
        author_instructions="",
    )
    competing_command = GeneratePlanningDraft(
        project_id=PROJECT,
        draft_id=draft.draft_id,
        draft_revision=draft.draft_revision,
        draft_hash=draft.content_hash,
        idempotency_key="different-key-competing",
        author_instructions="",
    )
    original = asyncio.create_task(service.generate(original_command))
    await gateway.entered.wait()
    persisted = await disposable_mysql.session.fetchone(
        """SELECT * FROM planning_generation_attempts
            WHERE project_id=%s AND idempotency_key=%s""",
        (PROJECT, original_command.idempotency_key),
    )
    operation_id = persisted["operation_id"]
    attempt_locked = asyncio.Event()
    replay_repository = _ReplayBarrierPlanningRepository()
    competing_service = PlanningGenerationService(
        replay_repository,
        provider_gateway=gateway,
        transaction_factory=transaction,
        id_factory=lambda: "must-not-allocate-while-active",
        clock=lambda: NOW + 300,
    )

    async def terminalize_attempt():
        async with transaction() as session:
            attempt = await PlanningRepository().lock_generation_attempt(
                session, PROJECT, operation_id
            )
            attempt_locked.set()
            await replay_repository.project_locked.wait()
            project = await PlanningRepository().lock_active_project(
                session, PROJECT
            )
            assert project is not None
            assert await PlanningRepository().fail_generation_attempt(
                session,
                project_id=PROJECT,
                operation_id=operation_id,
                fencing_token=int(attempt["fencing_token"]),
                failure_code="PlanningProviderFailed",
                updated_at=NOW + 301,
            )

    terminalizer = asyncio.create_task(terminalize_attempt())
    await attempt_locked.wait()
    competing = asyncio.create_task(
        competing_service.generate(competing_command)
    )
    await replay_repository.project_locked.wait()
    await asyncio.sleep(0)
    replay_repository.allow_lookup.set()
    try:
        with pytest.raises(PlanningGenerationConflict):
            await asyncio.wait_for(competing, timeout=5)
        await asyncio.wait_for(terminalizer, timeout=5)
    finally:
        gateway.release.set()
    original_result = await asyncio.wait_for(original, timeout=5)

    assert original_result.operation_id == operation_id
    assert original_result.status == "failed"
    assert len(gateway.calls) == 1
    remaining = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count
             FROM planning_generation_attempts
            WHERE project_id=%s AND status='pending' AND active_slot=1""",
        (PROJECT,),
    )
    assert remaining["count"] == 0


@pytest.mark.asyncio
async def test_real_mysql_planning_binding_lock_returns_exact_task_and_runtime(
    disposable_mysql,
):
    await _prepare(disposable_mysql)
    head = await disposable_mysql.session.fetchone(
        """SELECT binding_revision_id,revision,content_hash
             FROM project_model_binding_heads WHERE project_id=%s""",
        (PROJECT,),
    )
    planning_item = await disposable_mysql.session.fetchone(
        """SELECT * FROM project_model_binding_items
            WHERE binding_revision_id=%s AND task_key='planning'""",
        (head["binding_revision_id"],),
    )
    provider = await disposable_mysql.session.fetchone(
        """SELECT * FROM provider_profiles
            WHERE id=(SELECT provider_id FROM project_model_binding_items
                       WHERE binding_revision_id=%s AND task_key='planning')""",
        (head["binding_revision_id"],),
    )

    row = await PlanningRepository().lock_planning_binding(
        disposable_mysql.session,
        PROJECT,
    )

    assert row["binding_revision_id"] == head["binding_revision_id"]
    assert row["binding_revision"] == head["revision"]
    assert row["binding_hash"] == head["content_hash"]
    assert row["binding_task_key"] == planning_item["task_key"] == "planning"
    assert row["resolution_status"] == planning_item["resolution_status"]
    assert row["model_name_snapshot"] == planning_item["model_name_snapshot"]
    for field in (
        "id",
        "provider_type",
        "model_name",
        "base_url",
        "api_key",
        "enabled",
        "lifecycle_status",
        "revision",
        "temperature",
        "max_context_tokens",
        "max_output_tokens",
    ):
        assert row[field] == provider[field]
    assert row["provider_id"] == provider["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ("item", "head"))
async def test_real_mysql_planning_binding_lock_returns_none_without_exact_join(
    disposable_mysql,
    missing,
):
    await _prepare(disposable_mysql)
    head = await disposable_mysql.session.fetchone(
        """SELECT binding_revision_id FROM project_model_binding_heads
            WHERE project_id=%s""",
        (PROJECT,),
    )
    if missing == "item":
        await disposable_mysql.session.execute(
            """DELETE FROM project_model_binding_items
                WHERE binding_revision_id=%s AND task_key='planning'""",
            (head["binding_revision_id"],),
        )
    else:
        await disposable_mysql.session.execute(
            "DELETE FROM project_model_binding_heads WHERE project_id=%s",
            (PROJECT,),
        )

    assert await PlanningRepository().lock_planning_binding(
        disposable_mysql.session,
        PROJECT,
    ) is None
