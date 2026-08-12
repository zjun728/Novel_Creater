from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from types import TracebackType

import pytest
from pymysql.err import OperationalError

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import (
    DraftPlanningAggregate,
    normalize_planning_aggregate,
)
from backend.gateways.chapter_outline_provider import (
    ChapterOutlineProviderError,
)
from backend.http_errors import ProjectArchived
from backend.services.chapter_outline_generation import (
    ChapterOutlineGenerationConflict,
)


NOW = 2_100_000_000_000
HASH = "a" * 64
OPERATION_1 = "11111111-1111-4111-8111-111111111111"
OPERATION_2 = "22222222-2222-4222-8222-222222222222"
SETTLEMENT_RETRY_LIMIT = 3
ASYNC_TIMEOUT = 1


def _assert_no_sensitive_error_graph(
    error: BaseException,
    sentinels: tuple[str, ...],
) -> None:
    pending: list[tuple[object, int]] = [(error, 0)]
    seen: set[int] = set()
    evidence: list[str] = []
    while pending:
        value, depth = pending.pop()
        if value is None or depth > 24 or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, str):
            evidence.append(value)
            continue
        if isinstance(value, bytes):
            evidence.append(value.decode("utf-8", errors="replace"))
            continue
        if isinstance(value, BaseException):
            evidence.extend((type(value).__name__, str(value)))
            pending.extend(
                (
                    (value.args, depth + 1),
                    (value.__cause__, depth + 1),
                    (value.__context__, depth + 1),
                    (value.__traceback__, depth + 1),
                    (vars(value), depth + 1),
                )
            )
            continue
        if isinstance(value, TracebackType):
            filename = value.tb_frame.f_code.co_filename.replace("\\", "/")
            if "/backend/tests/" not in filename:
                pending.append((value.tb_frame.f_locals, depth + 1))
            pending.append((value.tb_next, depth + 1))
            continue
        if isinstance(value, Mapping):
            pending.extend((item, depth + 1) for item in value.items())
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            pending.extend((item, depth + 1) for item in value)
            continue
        if type(value).__module__.startswith("backend."):
            try:
                pending.append((vars(value), depth + 1))
            except TypeError:
                pass

    joined = "\n".join(evidence)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert all(sentinel not in joined for sentinel in sentinels)


def _planning():
    draft = DraftPlanningAggregate.model_validate(
        {
            "activeStoryBlockRef": "block",
            "volumes": [
                {
                    "clientNodeKey": "volume",
                    "order": 1,
                    "title": "第一卷",
                    "coreChange": "主角从逃亡转为立足。",
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
        },
        strict=True,
    )
    identifiers = iter(("volume-1", "plot-1", "block-1", "stage-1", "task-1"))
    return normalize_planning_aggregate(
        draft,
        previous_confirmed=None,
        previous_draft=None,
        id_factory=identifiers.__next__,
    )


def _ref(node):
    return {
        "id": node.id,
        "revision": node.revision,
        "contentHash": node.content_hash,
    }


def _generated(planning=None):
    planning = planning or _planning()
    block = planning.story_blocks[0]
    stage = block.stages[0]
    return EditableChapterOutlineContent.model_validate(
        {
            "schemaVersion": "chapter-outline-draft-v1",
            "volumeRef": _ref(planning.volumes[0]),
            "storyBlockRef": _ref(block),
            "stageRefs": [_ref(stage)],
            "sceneTaskRefs": [_ref(stage.scene_tasks[0])],
            "chapterGoal": "找到封锁线缺口。",
            "expectedCharacters": ["主角", "同伴"],
            "continuation": ["承接被困局面"],
            "plannedTasks": ["观察换岗"],
            "scenes": ["废弃驿站侦察"],
            "forbiddenEarlyEvents": ["不可提前揭示内应"],
        },
        strict=True,
    )


class TransactionTracker:
    def __init__(self):
        self.active = 0
        self.entries = 0

    def factory(self):
        tracker = self

        class Transaction:
            async def __aenter__(self):
                tracker.active += 1
                tracker.entries += 1
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                tracker.active -= 1
                return False

        return Transaction()


class RollbackCommitTracker:
    def __init__(
        self,
        repository,
        *,
        settlement_commit_failures,
        block_first_failure=False,
    ):
        self.repository = repository
        self.settlement_commit_failures = settlement_commit_failures
        self.block_first_failure = block_first_failure
        self.active = 0
        self.entries = 0
        self.commit_failures = 0
        self.first_failure_entered = asyncio.Event()
        self.release_first_failure = asyncio.Event()

    def factory(self):
        tracker = self

        class Transaction:
            async def __aenter__(self):
                tracker.active += 1
                tracker.entries += 1
                self.entry = tracker.entries
                self.attempts = deepcopy(tracker.repository.attempts)
                self.draft = deepcopy(tracker.repository.draft)
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                fail_commit = (
                    exc_type is None
                    and self.entry >= 2
                    and tracker.commit_failures
                    < tracker.settlement_commit_failures
                )
                if exc_type is not None or fail_commit:
                    tracker.repository.attempts = self.attempts
                    tracker.repository.draft = self.draft
                if fail_commit:
                    tracker.commit_failures += 1
                    if tracker.commit_failures == 1:
                        tracker.first_failure_entered.set()
                        if tracker.block_first_failure:
                            await tracker.release_first_failure.wait()
                    tracker.active -= 1
                    raise OperationalError(
                        1213,
                        "SETTLEMENT_COMMIT_SECRET_SENTINEL",
                    )
                tracker.active -= 1
                return False

        return Transaction()


class FakeChapterRepository:
    def __init__(self):
        self.active_session = None
        self.max_final = None

    async def read_active_session(self, _session, project_id):
        return self.active_session if project_id == "p1" else None

    async def read_max_final_chapter_number(self, _session, project_id):
        return self.max_final if project_id == "p1" else None


class FakePlanningRepository:
    def __init__(self, planning):
        self.basis = {
            "selection_revision": 1,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1",
            "seed_hash": "1" * 64,
            "contract_revision": 1,
            "creation_contract_id": "contract-1",
            "creation_hash": "2" * 64,
            "style_contract_id": "style-1",
            "style_hash": "3" * 64,
            "bible_revision": 1,
            "bible_revision_id": "bible-1",
            "bible_hash": "4" * 64,
            "chapter_capacity_policy": {
                "targetMin": 2_000,
                "targetMax": 3_000,
                "softCeiling": 3_000,
            },
        }
        self.head = {
            "revision": 1,
            "planning_revision_id": "planning-1",
            "content_hash": planning.content_hash,
            **{
                key: value
                for key, value in self.basis.items()
                if key != "chapter_capacity_policy"
            },
        }
        self.binding = {
            "binding_revision_id": "binding-1",
            "binding_revision": 1,
            "binding_hash": "5" * 64,
            "binding_task_key": "planning",
            "resolution_status": "bound",
            "provider_id": "provider-1",
            "model_name_snapshot": "test-model",
            "id": "provider-1",
            "provider_type": "openai-compatible",
            "model_name": "test-model",
            "base_url": "https://provider.invalid/v1",
            "api_key": "TEST_ONLY_PRIVATE_KEY",
            "enabled": 1,
            "lifecycle_status": "active",
            "revision": 1,
            "temperature": 0.4,
            "max_context_tokens": 100_000,
            "max_output_tokens": 8_000,
        }

    async def read_current_basis(self, _session, project_id):
        return self.basis if project_id == "p1" else None

    async def lock_planning_head(self, _session, project_id):
        return self.head if project_id == "p1" else None

    async def lock_planning_binding(self, _session, project_id):
        return self.binding if project_id == "p1" else None


class FakeOutlineRepository:
    def __init__(self, planning):
        content = EditableChapterOutlineContent()
        payload = content.model_dump(mode="json", by_alias=True)
        self.project = {"id": "p1", "archived_at": None}
        self.authorities = {
            "planning_revision_id": "planning-1",
            "planning_revision": 1,
            "planning_hash": planning.content_hash,
            "planning_content": planning.model_dump(mode="json", by_alias=True),
            "chapter_capacity_policy": {
                "targetMin": 2_000,
                "targetMax": 3_000,
                "softCeiling": 3_000,
            },
            "canon_revision": 0,
            "projection_revision": 0,
            "projection_hash": "6" * 64,
        }
        self.head = None
        self.draft = {
            "id": "draft-1",
            "project_id": "p1",
            "chapter_num": 1,
            "active_slot": 1,
            "base_head_revision": 0,
            "draft_revision": 1,
            "planning_revision_id": "planning-1",
            "planning_revision": 1,
            "planning_hash": planning.content_hash,
            "canon_revision": 0,
            "projection_revision": 0,
            "projection_hash": "6" * 64,
            "content": payload,
            "content_hash": canonical_hash(payload),
            "source_attempt_id": None,
            "status": "active",
        }
        self.attempts = {}
        self.lock_order = []
        self.load_calls = 0
        self.plain_operation_reads = 0
        self.plain_key_reads = 0

    async def lock_project(self, _session, project_id):
        self.lock_order.append("project")
        if self.project["archived_at"] is not None:
            raise ProjectArchived()
        return self.project if project_id == "p1" else None

    async def read_project_any(self, _session, project_id):
        return self.project if project_id == "p1" else None

    async def read_current_authorities(self, _session, project_id):
        self.lock_order.append("canon-projection")
        return self.authorities if project_id == "p1" else None

    async def lock_outline_head(self, _session, project_id, chapter_number):
        self.lock_order.append("outline-head")
        return self.head

    async def read_draft(
        self, _session, project_id, chapter_number, draft_id
    ):
        self.lock_order.append("outline-draft")
        if (
            project_id == "p1"
            and chapter_number == 1
            and draft_id == self.draft["id"]
        ):
            return self.draft
        return None

    async def lock_attempt_by_key(
        self, _session, project_id, idempotency_key
    ):
        self.lock_order.append("idempotency")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["project_id"] == project_id
                and row["idempotency_key"] == idempotency_key
            ),
            None,
        )

    async def read_attempt_by_key(
        self, _session, project_id, idempotency_key
    ):
        self.plain_key_reads += 1
        return next(
            (
                row
                for row in self.attempts.values()
                if row["project_id"] == project_id
                and row["idempotency_key"] == idempotency_key
            ),
            None,
        )

    async def lock_attempt(self, _session, project_id, operation_id):
        self.lock_order.append("attempt")
        row = self.attempts.get(operation_id)
        return row if row and row["project_id"] == project_id else None

    async def read_attempt(self, _session, project_id, operation_id):
        self.plain_operation_reads += 1
        row = self.attempts.get(operation_id)
        return row if row and row["project_id"] == project_id else None

    async def lock_active_attempt(self, _session, draft_id):
        self.lock_order.append("active-attempt")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["outline_draft_id"] == draft_id
                and row["status"] == "pending"
                and row["active_slot"] == 1
            ),
            None,
        )

    async def next_fencing_token(self, _session, draft_id):
        self.lock_order.append("fencing-token")
        return (
            max(
                (
                    row["fencing_token"]
                    for row in self.attempts.values()
                    if row["outline_draft_id"] == draft_id
                ),
                default=0,
            )
            + 1
        )

    async def insert_attempt(self, _session, row):
        self.attempts[row["operation_id"]] = {
            **deepcopy(row),
            "active_slot": 1,
            "status": "pending",
            "failure_code": None,
            "result_content": None,
            "result_content_hash": None,
            "loaded_outline_draft_revision": None,
            "loaded_at": None,
        }
        return True

    async def supersede_attempt(
        self, _session, project_id, operation_id, fencing_token
    ):
        row = self.attempts.get(operation_id)
        if not self._owns(row, project_id, fencing_token):
            return False
        row.update(status="superseded", active_slot=None)
        return True

    async def fail_attempt(
        self, _session, project_id, operation_id, fencing_token, failure_code
    ):
        row = self.attempts.get(operation_id)
        if not self._owns(row, project_id, fencing_token):
            return False
        row.update(
            status="failed",
            active_slot=None,
            failure_code=failure_code,
        )
        return True

    async def load_result_into_draft(
        self,
        _session,
        draft_id,
        expected_revision,
        expected_hash,
        operation_id,
        fencing_token,
        content,
        content_hash,
        loaded_at,
    ):
        self.load_calls += 1
        row = self.attempts.get(operation_id)
        if (
            not self._owns(row, "p1", fencing_token)
            or self.draft["id"] != draft_id
            or self.draft["draft_revision"] != expected_revision
            or self.draft["content_hash"] != expected_hash
        ):
            return False
        loaded_revision = expected_revision + 1
        self.draft.update(
            draft_revision=loaded_revision,
            content=content,
            content_hash=content_hash,
            source_attempt_id=row["id"],
        )
        row.update(
            status="succeeded",
            active_slot=None,
            result_content=content,
            result_content_hash=content_hash,
            loaded_outline_draft_revision=loaded_revision,
            loaded_at=loaded_at,
        )
        return True

    @staticmethod
    def _owns(row, project_id, fencing_token):
        return (
            row is not None
            and row["project_id"] == project_id
            and row["status"] == "pending"
            and row["active_slot"] == 1
            and row["fencing_token"] == fencing_token
        )


class FakeGateway:
    def __init__(self, output=None, *, hook=None, error=None):
        self.output = output
        self.hook = hook
        self.error = error
        self.calls = []

    async def generate(self, *, provider, model_name, manifest):
        self.calls.append(
            {
                "provider": provider,
                "model_name": model_name,
                "manifest": manifest,
            }
        )
        if self.hook is not None:
            self.hook()
        if self.error is not None:
            raise self.error
        return self.output


class BlockingGateway(FakeGateway):
    def __init__(self, output):
        super().__init__(output)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        self.entered.set()
        await self.release.wait()
        return self.output


def _service(*, gateway=None, clock=lambda: NOW):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationService,
    )

    planning = _planning()
    outline = FakeOutlineRepository(planning)
    chapter = FakeChapterRepository()
    planning_repository = FakePlanningRepository(planning)
    tracker = TransactionTracker()
    gateway = gateway or FakeGateway(_generated(planning))
    identifiers = iter(("attempt-1", OPERATION_1, "attempt-2", OPERATION_2))
    service = ChapterOutlineGenerationService(
        outline,
        chapter,
        planning_repository=planning_repository,
        provider_gateway=gateway,
        transaction_factory=tracker.factory,
        id_factory=identifiers.__next__,
        clock=clock,
    )
    return service, outline, chapter, planning_repository, gateway, tracker


def _command(key="outline-generate-1", **overrides):
    from backend.services.chapter_outline_generation import (
        GenerateChapterOutline,
    )

    payload = EditableChapterOutlineContent().model_dump(
        mode="json", by_alias=True
    )
    values = {
        "project_id": "p1",
        "chapter_number": 1,
        "draft_id": "draft-1",
        "draft_revision": 1,
        "draft_hash": canonical_hash(payload),
        "idempotency_key": key,
        "author_instructions": "强化人物选择。",
    }
    values.update(overrides)
    return GenerateChapterOutline(**values)


@pytest.mark.asyncio
async def test_success_reserves_calls_outside_transaction_and_join_loads_exact_draft():
    service, repository, _chapter, _planning, gateway, tracker = _service()

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is True
    assert result.loaded_draft_revision == 2
    assert result.model.provider_id == "provider-1"
    assert result.model.model_name == "test-model"
    assert tracker.entries == 2
    assert tracker.active == 0
    assert repository.load_calls == 1
    assert len(gateway.calls) == 1
    assert repository.lock_order[:12] == [
        "project",
        "canon-projection",
        "outline-head",
        "outline-draft",
        "idempotency",
        "active-attempt",
        "fencing-token",
        "project",
        "canon-projection",
        "outline-head",
        "outline-draft",
        "attempt",
    ]


@pytest.mark.asyncio
async def test_generation_allows_a_drafting_session_on_its_authoritative_chapter():
    service, _repository, chapter, _planning, gateway, _tracker = _service()
    chapter.active_session = {"chapter_num": 1, "status": "drafting"}

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is True
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active_session",
    (
        {"chapter_num": 1, "status": "final"},
        {"chapter_num": 2, "status": "drafting"},
    ),
)
async def test_generation_rejects_finalized_or_wrong_chapter_sessions(active_session):
    service, _repository, chapter, _planning, gateway, _tracker = _service()
    chapter.active_session = active_session

    with pytest.raises(ChapterOutlineGenerationConflict):
        await service.generate(_command())
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_same_key_replays_and_different_request_conflicts_without_second_call():
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationIdempotencyConflict,
    )

    service, _repo, _chapter, _planning, gateway, _tracker = _service()
    first = await service.generate(_command("same-key"))
    replay = await service.generate(_command("same-key"))

    assert replay == first
    with pytest.raises(ChapterOutlineGenerationIdempotencyConflict):
        await service.generate(
            _command("same-key", author_instructions="不同要求")
        )
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_one_live_pending_attempt_rejects_different_key():
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationConflict,
    )

    service, _repo, _chapter, _planning, gateway, _tracker = _service()
    blocking = BlockingGateway(gateway.output)
    service._gateway = blocking
    pending = asyncio.create_task(service.generate(_command("first-key")))
    await blocking.entered.wait()
    try:
        with pytest.raises(ChapterOutlineGenerationConflict):
            await service.generate(_command("second-key"))
    finally:
        blocking.release.set()
        await pending


@pytest.mark.asyncio
async def test_expired_pending_attempt_is_superseded_before_new_fenced_attempt():
    current = [NOW]
    service, repository, _chapter, _planning, gateway, _tracker = _service(
        clock=lambda: current[0]
    )
    blocking = BlockingGateway(gateway.output)
    service._gateway = blocking
    old = asyncio.create_task(service.generate(_command("old-key")))
    await blocking.entered.wait()
    current[0] += 300_000
    service._gateway = gateway
    fresh = await service.generate(_command("new-key"))
    blocking.release.set()
    old_result = await old

    assert fresh.status == "succeeded"
    assert fresh.operation_id == OPERATION_2
    assert repository.attempts[OPERATION_1]["status"] == "superseded"
    assert old_result.status == "superseded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "failure_code"),
    (
        (
            ChapterOutlineProviderError("SECRET provider raw output"),
            "ChapterOutlineProviderFailed",
        ),
        (RuntimeError("SECRET api key and prompt"), "ChapterOutlineProviderFailed"),
    ),
)
async def test_provider_failure_is_terminal_and_secret_free(error, failure_code):
    service, repository, _chapter, _planning, _gateway, _tracker = _service(
        gateway=FakeGateway(error=error)
    )

    result = await service.generate(_command())

    assert result.status == "failed"
    assert result.failure_code == failure_code
    assert "SECRET" not in repr(result)
    assert repository.attempts[OPERATION_1]["failure_code"] == failure_code


@pytest.mark.asyncio
async def test_parse_or_reference_failure_is_terminal_without_loading():
    service, repository, _chapter, _planning, _gateway, _tracker = _service(
        gateway=FakeGateway(EditableChapterOutlineContent())
    )

    result = await service.generate(_command())

    assert result.status == "failed"
    assert result.failure_code == "ChapterOutlineProviderResultInvalid"
    assert repository.load_calls == 0


@pytest.mark.asyncio
async def test_exact_refs_but_incomplete_outline_is_failed_before_loading():
    planning = _planning()
    incomplete = _generated(planning).model_copy(
        update={"chapter_goal": "", "scenes": ()}
    )
    service, repository, _chapter, _planning_repo, _gateway, _tracker = (
        _service(gateway=FakeGateway(incomplete))
    )

    result = await service.generate(_command())

    assert result.status == "failed"
    assert result.failure_code == "ChapterOutlineProviderResultInvalid"
    assert repository.load_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    (
        "draft",
        "chapter",
        "planning",
        "canon",
        "projection",
        "binding",
        "provider",
        "lifecycle",
        "lease",
    ),
)
async def test_all_authority_drift_terminally_supersedes_without_loading(drift):
    current = [NOW]
    service, repository, chapter, planning, gateway, _tracker = _service(
        clock=lambda: current[0]
    )

    def mutate():
        if drift == "draft":
            repository.draft["draft_revision"] = 2
            repository.draft["content_hash"] = "9" * 64
        elif drift == "chapter":
            chapter.max_final = 1
        elif drift == "planning":
            planning.head["content_hash"] = "8" * 64
        elif drift == "canon":
            repository.authorities["canon_revision"] = 1
        elif drift == "projection":
            repository.authorities["projection_hash"] = "7" * 64
        elif drift == "binding":
            planning.binding["binding_hash"] = "8" * 64
        elif drift == "provider":
            planning.binding["revision"] = 2
        elif drift == "lifecycle":
            repository.project["archived_at"] = NOW
        else:
            current[0] += 300_000

    gateway.hook = mutate
    result = await service.generate(_command())

    assert result.status == "superseded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    assert repository.load_calls == 0


@pytest.mark.asyncio
async def test_stale_fence_cannot_publish_after_terminal_supersession():
    service, repository, _chapter, _planning, gateway, _tracker = _service()
    blocking = BlockingGateway(gateway.output)
    service._gateway = blocking
    pending = asyncio.create_task(service.generate(_command()))
    await blocking.entered.wait()
    repository.attempts[OPERATION_1].update(
        status="superseded",
        active_slot=None,
    )
    blocking.release.set()

    result = await pending

    assert result.status == "superseded"
    assert result.loaded is False
    assert repository.load_calls == 0


@pytest.mark.asyncio
async def test_cancellation_terminalizes_owned_attempt_and_reraises_cleanly():
    service, repository, _chapter, _planning, gateway, tracker = _service()
    blocking = BlockingGateway(gateway.output)
    service._gateway = blocking
    pending = asyncio.create_task(service.generate(_command()))
    await blocking.entered.wait()
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending

    assert repository.attempts[OPERATION_1]["status"] == "failed"
    assert repository.attempts[OPERATION_1]["failure_code"] == (
        "ChapterOutlineGenerationCancelled"
    )
    assert tracker.active == 0


@pytest.mark.asyncio
async def test_operation_lookups_are_read_only_and_never_retry_provider():
    service, repository, _chapter, _planning, gateway, tracker = _service()
    generated = await service.generate(_command("lookup-key"))
    calls = len(gateway.calls)
    transactions = tracker.entries

    by_id = await service.get_operation("p1", generated.operation_id)
    by_key = await service.get_operation_by_key("p1", "lookup-key")

    assert by_id == by_key == generated
    assert len(gateway.calls) == calls
    assert tracker.entries == transactions + 2
    assert repository.plain_operation_reads == 1
    assert repository.plain_key_reads == 1


@pytest.mark.asyncio
async def test_gateway_cancellation_raises_fresh_secret_free_cancellation():
    api_key = "OUTLINE_CANCEL_API_KEY_SENTINEL"
    base_url = "https://OUTLINE_CANCEL_URL_SENTINEL.invalid/v1"
    prompt = "OUTLINE_CANCEL_PROMPT_SENTINEL"
    service, repository, _chapter, planning, _gateway, tracker = _service(
        gateway=FakeGateway(error=asyncio.CancelledError("raw cancellation"))
    )
    planning.binding["api_key"] = api_key
    planning.binding["base_url"] = base_url

    with pytest.raises(asyncio.CancelledError) as caught:
        await service.generate(_command(author_instructions=prompt))

    assert caught.value.args == ()
    _assert_no_sensitive_error_graph(
        caught.value,
        (api_key, base_url, prompt),
    )
    assert repository.attempts[OPERATION_1]["status"] == "failed"
    assert repository.attempts[OPERATION_1]["failure_code"] == (
        "ChapterOutlineGenerationCancelled"
    )
    assert not any(
        row["status"] == "pending" for row in repository.attempts.values()
    )
    assert tracker.active == 0


@pytest.mark.asyncio
async def test_reserve_rejection_raises_fresh_secret_free_public_error():
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationNotReady,
    )

    api_key = "OUTLINE_RESERVE_API_KEY_SENTINEL"
    base_url = "https://OUTLINE_RESERVE_URL_SENTINEL.invalid/v1"
    prompt = "OUTLINE_RESERVE_PROMPT_SENTINEL"
    service, repository, _chapter, planning, _gateway, _tracker = _service()
    planning.binding.update(
        api_key=api_key,
        base_url=base_url,
        resolution_status="unbound",
    )

    with pytest.raises(ChapterOutlineGenerationNotReady) as caught:
        await service.generate(_command(author_instructions=prompt))

    _assert_no_sensitive_error_graph(
        caught.value,
        (api_key, base_url, prompt),
    )
    assert repository.attempts == {}


@pytest.mark.asyncio
async def test_settlement_failure_raises_fixed_secret_free_public_error():
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationConflict,
    )

    api_key = "OUTLINE_SETTLE_API_KEY_SENTINEL"
    base_url = "https://OUTLINE_SETTLE_URL_SENTINEL.invalid/v1"
    prompt = "OUTLINE_SETTLE_PROMPT_SENTINEL"
    raw = "OUTLINE_SETTLE_RAW_SENTINEL"
    service, repository, _chapter, planning, _gateway, _tracker = _service(
        gateway=FakeGateway(error=RuntimeError(raw))
    )
    planning.binding["api_key"] = api_key
    planning.binding["base_url"] = base_url
    original_fail = repository.fail_attempt

    async def terminal_then_fail(*args, **kwargs):
        assert await original_fail(*args, **kwargs)
        raise RuntimeError(raw)

    repository.fail_attempt = terminal_then_fail

    with pytest.raises(ChapterOutlineGenerationConflict) as caught:
        await service.generate(_command(author_instructions=prompt))

    _assert_no_sensitive_error_graph(
        caught.value,
        (api_key, base_url, prompt, raw),
    )
    assert repository.attempts[OPERATION_1]["status"] == "failed"
    assert not any(
        row["status"] == "pending" for row in repository.attempts.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (2, 4))
async def test_transient_settlement_commit_failure_retries_and_preserves_cancellation(
    cancel_count,
):
    api_key = "SETTLEMENT_RETRY_API_KEY_SENTINEL"
    base_url = "https://SETTLEMENT_RETRY_URL_SENTINEL.invalid/v1"
    prompt = "SETTLEMENT_RETRY_PROMPT_SENTINEL"
    raw = "SETTLEMENT_COMMIT_SECRET_SENTINEL"
    service, repository, _chapter, planning, gateway, _tracker = _service(
        gateway=FakeGateway(
            error=ChapterOutlineProviderError("provider failed")
        )
    )
    planning.binding["api_key"] = api_key
    planning.binding["base_url"] = base_url
    tracker = RollbackCommitTracker(
        repository,
        settlement_commit_failures=1,
        block_first_failure=True,
    )
    service._transaction = tracker.factory
    pending = asyncio.create_task(
        service.generate(_command(author_instructions=prompt))
    )
    primary_error = None
    try:
        try:
            await asyncio.wait_for(
                tracker.first_failure_entered.wait(),
                timeout=ASYNC_TIMEOUT,
            )
            for _ in range(cancel_count):
                pending.cancel()
                await asyncio.sleep(0)
                assert not pending.done()
        finally:
            tracker.release_first_failure.set()

        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(
                asyncio.shield(pending),
                timeout=ASYNC_TIMEOUT,
            )
        await asyncio.sleep(0)

        _assert_no_sensitive_error_graph(
            caught.value,
            (api_key, base_url, prompt, raw),
        )
        assert pending.cancelled() is True
        assert pending.cancelling() == cancel_count
        assert repository.attempts[OPERATION_1]["status"] == "failed"
        assert repository.attempts[OPERATION_1]["active_slot"] is None
        assert repository.attempts[OPERATION_1]["failure_code"] == (
            "ChapterOutlineProviderFailed"
        )
        assert not any(
            row["status"] == "pending"
            for row in repository.attempts.values()
        )
        assert len(gateway.calls) == 1
        assert tracker.entries == 3
        assert tracker.active == 0
        assert not [
            task
            for task in asyncio.all_tasks()
            if not task.done()
            and task.get_name() == "chapter-outline-generation-settlement"
        ]
    except BaseException as error:
        primary_error = error
        raise
    finally:
        tracker.release_first_failure.set()
        if not pending.done():
            pending.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(pending, return_exceptions=True),
                timeout=ASYNC_TIMEOUT,
            )
        except BaseException:
            if primary_error is None:
                raise


@pytest.mark.asyncio
async def test_persistent_settlement_commit_failure_is_bounded_and_recoverable():
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationRetryable,
    )

    api_key = "PERSISTENT_SETTLEMENT_API_KEY_SENTINEL"
    base_url = "https://PERSISTENT_SETTLEMENT_URL_SENTINEL.invalid/v1"
    prompt = "PERSISTENT_SETTLEMENT_PROMPT_SENTINEL"
    raw = "SETTLEMENT_COMMIT_SECRET_SENTINEL"
    service, repository, _chapter, planning, gateway, _tracker = _service(
        gateway=FakeGateway(
            error=ChapterOutlineProviderError("provider failed")
        )
    )
    planning.binding["api_key"] = api_key
    planning.binding["base_url"] = base_url
    tracker = RollbackCommitTracker(
        repository,
        settlement_commit_failures=100,
    )
    service._transaction = tracker.factory

    with pytest.raises(ChapterOutlineGenerationRetryable) as caught:
        await service.generate(_command(author_instructions=prompt))
    await asyncio.sleep(0)

    _assert_no_sensitive_error_graph(
        caught.value,
        (api_key, base_url, prompt, raw),
    )
    attempt = repository.attempts[OPERATION_1]
    assert attempt["status"] == "pending"
    assert attempt["active_slot"] == 1
    assert attempt["failure_code"] is None
    assert len(gateway.calls) == 1
    assert tracker.entries == 1 + SETTLEMENT_RETRY_LIMIT
    assert tracker.commit_failures == SETTLEMENT_RETRY_LIMIT
    assert tracker.active == 0
    assert not [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and task.get_name() == "chapter-outline-generation-settlement"
    ]


def _operation_row(**overrides):
    row = {
        "operation_id": OPERATION_1,
        "active_slot": 1,
        "status": "pending",
        "failure_code": None,
        "provider_id": "provider-1",
        "model_name_snapshot": "test-model",
        "result_content": None,
        "result_content_hash": None,
        "loaded_outline_draft_revision": None,
        "loaded_at": None,
    }
    row.update(overrides)
    return row


def test_operation_projector_rejects_nonopaque_identifier_without_echo():
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationConflict,
        ChapterOutlineGenerationService,
    )

    sentinel = "api_key=OPERATION_ID_SENTINEL"
    with pytest.raises(ChapterOutlineGenerationConflict) as caught:
        ChapterOutlineGenerationService._operation_result(
            _operation_row(operation_id=sentinel)
        )

    _assert_no_sensitive_error_graph(caught.value, (sentinel,))


@pytest.mark.parametrize(
    ("status", "active_slot", "overrides"),
    (
        ("pending", None, {}),
        ("pending", "ACTIVE_SLOT_SECRET_SENTINEL", {}),
        ("pending", True, {}),
        ("pending", 2, {}),
        (
            "succeeded",
            1,
            {
                "result_content": {
                    "schemaVersion": "chapter-outline-draft-v1"
                },
                "result_content_hash": HASH,
                "loaded_outline_draft_revision": 2,
                "loaded_at": NOW,
            },
        ),
        (
            "failed",
            1,
            {"failure_code": "ChapterOutlineProviderFailed"},
        ),
        ("superseded", 1, {}),
    ),
)
def test_operation_projector_rejects_corrupt_active_slot_combinations(
    status,
    active_slot,
    overrides,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationConflict,
        ChapterOutlineGenerationService,
    )

    sentinel = "ACTIVE_SLOT_SECRET_SENTINEL"
    with pytest.raises(ChapterOutlineGenerationConflict) as caught:
        ChapterOutlineGenerationService._operation_result(
            _operation_row(
                status=status,
                active_slot=active_slot,
                **overrides,
            )
        )

    _assert_no_sensitive_error_graph(caught.value, (sentinel,))


@pytest.mark.parametrize(
    ("status", "overrides"),
    (
        ("pending", {}),
        (
            "succeeded",
            {
                "active_slot": None,
                "result_content": {
                    "schemaVersion": "chapter-outline-draft-v1"
                },
                "result_content_hash": HASH,
                "loaded_outline_draft_revision": 2,
                "loaded_at": NOW,
            },
        ),
        (
            "failed",
            {
                "active_slot": None,
                "failure_code": "ChapterOutlineProviderFailed",
            },
        ),
        ("superseded", {"active_slot": None}),
    ),
)
def test_operation_projector_preserves_legal_active_slot_states(
    status,
    overrides,
):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationService,
    )

    result = ChapterOutlineGenerationService._operation_result(
        _operation_row(status=status, **overrides)
    )

    assert result.status == status


def test_operation_projector_rejects_malicious_loaded_revision_without_raw_error():
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationConflict,
        ChapterOutlineGenerationService,
    )

    sentinel = "MALICIOUS_PRIVATE_VALUE"
    with pytest.raises(ChapterOutlineGenerationConflict) as caught:
        ChapterOutlineGenerationService._operation_result(
            _operation_row(
                status="succeeded",
                result_content={"schemaVersion": "chapter-outline-draft-v1"},
                result_content_hash=HASH,
                loaded_outline_draft_revision=sentinel,
                loaded_at=NOW,
            )
        )

    assert not isinstance(caught.value, ValueError)
    _assert_no_sensitive_error_graph(caught.value, (sentinel,))


@pytest.mark.parametrize("revision", (-1, 0))
def test_operation_projector_rejects_nonpositive_loaded_revision(revision):
    from backend.services.chapter_outline_generation import (
        ChapterOutlineGenerationConflict,
        ChapterOutlineGenerationService,
    )

    with pytest.raises(ChapterOutlineGenerationConflict):
        ChapterOutlineGenerationService._operation_result(
            _operation_row(
                status="succeeded",
                result_content={"schemaVersion": "chapter-outline-draft-v1"},
                result_content_hash=HASH,
                loaded_outline_draft_revision=revision,
                loaded_at=NOW,
            )
        )
