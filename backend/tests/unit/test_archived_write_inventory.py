from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Awaitable, Callable

import pytest

from backend import http_errors
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.repositories import project_lifecycle
from backend.services.canon import CanonService, CommitCanonRevision
from backend.services.chapter_draft_generation import (
    ChapterDraftGenerationService,
    GenerateWorkingDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionService,
    CreateChapterSession,
    SaveDraftCandidate,
    SaveWorkingDraft,
)
from backend.services.chapter_outlines import (
    ChapterOutlineArchived,
    ChapterOutlineService,
    ConfirmChapterOutlineDraft,
    CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.services.contracts import (
    ConfirmContracts,
    ContractDraftInput,
    ContractService,
    SaveContractDraft,
)
from backend.services.model_bindings import ModelBindingService
from backend.services.planning import (
    ConfirmPlanningDraft,
    CreatePlanningDraft,
    PlanningArchived,
    PlanningService,
    SavePlanningDraft,
)
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.seeds import (
    CreateSeed,
    DeleteSeed,
    EditSeed,
    SeedService,
    SelectSeed,
)
from backend.services.story_engines import (
    CreateManualStoryEngineBatch,
    ReserveStoryEngineBatch,
    StoryEngineService,
)
from backend.tests.support.story_engine_fakes import three_options


@asynccontextmanager
async def _transaction():
    yield object()


class _GuardProbeRepository:
    def __init__(self, guard_name: str):
        self.guard_name = guard_name
        self.actions: list[str] = []

    async def lock_project(self, _session, _project_id):
        self.actions.append("lock_project")
        raise http_errors.ProjectArchived()

    async def lock_active_project(self, _session, _project_id):
        self.actions.append("lock_active_project")
        raise http_errors.ProjectArchived()

    async def read_project_any(self, _session, _project_id):
        self.actions.append("read_project_any")
        return {"id": "p1", "archived_at": 1}

    def __getattr__(self, name):
        async def downstream(*_args, **_kwargs):
            self.actions.append(name)
            return None

        return downstream


class _ProviderProbe:
    def __init__(self):
        self.calls = 0

    async def generate(self, **_kwargs):
        self.calls += 1
        raise AssertionError("archived write reached provider")


def _seed_payload() -> SeedPayload:
    return SeedPayload(
        title="围栏清单",
        genre="玄幻",
        logline="归档项目不能继续写入",
        protagonist="测试者",
        desire="验证唯一写入边界",
        coreConflict="旧标签页仍试图写入",
        worldPressure="所有入口必须先检查项目",
        openingHook="项目刚刚被归档",
        differentiation="通过服务真实调用验证首个仓储动作",
    )


def _contract_draft() -> ContractDraftInput:
    return ContractDraftInput(
        schemaVersion="contract-draft-v2",
        draftStage="engine",
        engineOptionId="engine-1",
        engineHash="a" * 64,
        channelProfileKey="male-longform",
        genreProfileKey="fantasy",
        qualityCharterVersion="quality-v1",
        targetTotalWords=150_000,
        expectedVolumeCount=3,
        expectedChapterCount=60,
        chapterWordRangePreference=(2_000, 3_000),
        prohibitedDirections=("不写无代价升级",),
        authorNotes="每章推进一个明确变化。",
    )


def _canon_request() -> CommitCanonRevision:
    return CommitCanonRevision(
        project_id="p1",
        expected_head=0,
        idempotency_key="a" * 64,
        source_type="manual_test",
        source_id=None,
        entities=(),
        aliases=(),
        events=(),
    )


def _project_service(repository, _provider):
    return ProjectLifecycleService(repository, _transaction)


def _seed_service(repository, _provider):
    return SeedService(repository, transaction_factory=_transaction)


def _binding_service(repository, _provider):
    return ModelBindingService(repository, transaction_factory=_transaction)


def _contract_service(repository, _provider):
    return ContractService(
        repository,
        transaction_factory=_transaction,
        connection_factory=_transaction,
    )


def _planning_service(repository, _provider):
    return PlanningService(repository, transaction_factory=_transaction)


def _story_service(repository, provider):
    return StoryEngineService(
        repository,
        transaction_factory=_transaction,
        connection_factory=_transaction,
        provider_gateway=provider,
    )


def _chapter_service(repository, _provider):
    return ChapterSessionService(repository, transaction_factory=_transaction)


def _outline_service(repository, _provider):
    return ChapterOutlineService(
        repository,
        repository,
        transaction_factory=_transaction,
    )


def _generation_service(repository, provider):
    return ChapterDraftGenerationService(
        repository,
        transaction_factory=_transaction,
        provider_gateway=provider,
    )


def _canon_service(repository, _provider):
    return CanonService(repository, transaction_factory=_transaction)


ServiceFactory = Callable[[object, _ProviderProbe], object]
Invocation = Callable[[object], Awaitable[object]]


@dataclass(frozen=True)
class _WriteEntrypoint:
    name: str
    guard_name: str
    service_factory: ServiceFactory
    invoke: Invocation


# Existing-project content writes only. Project creation and archive/restore/
# permanent-delete use their separate lifecycle protocol; assets and corpus are
# global resources rather than project-owned writes.
WRITE_ENTRYPOINTS = (
    _WriteEntrypoint(
        "project.rename",
        "lock_active_project",
        _project_service,
        lambda service: service.rename("p1", "新标题"),
    ),
    _WriteEntrypoint(
        "seed.create",
        "lock_project",
        _seed_service,
        lambda service: service.create(
            CreateSeed(project_id="p1", payload=_seed_payload())
        ),
    ),
    _WriteEntrypoint(
        "seed.edit",
        "lock_project",
        _seed_service,
        lambda service: service.edit(EditSeed(
            project_id="p1",
            seed_id="seed-1",
            payload=_seed_payload(),
            expected_seed_revision=1,
            expected_selection_revision=0,
        )),
    ),
    _WriteEntrypoint(
        "seed.select",
        "lock_project",
        _seed_service,
        lambda service: service.select(SelectSeed(
            project_id="p1",
            seed_id="seed-1",
            expected_seed_revision=1,
            expected_selection_revision=0,
        )),
    ),
    _WriteEntrypoint(
        "seed.delete",
        "lock_project",
        _seed_service,
        lambda service: service.delete(DeleteSeed(
            project_id="p1",
            seed_id="seed-1",
            expected_seed_revision=1,
            expected_selection_revision=0,
        )),
    ),
    _WriteEntrypoint(
        "binding.replace_all",
        "lock_project",
        _binding_service,
        lambda service: service.replace_all(
            "p1",
            1,
            {task_key: None for task_key in TASK_KEYS},
        ),
    ),
    _WriteEntrypoint(
        "contract.save_draft",
        "lock_project",
        _contract_service,
        lambda service: service.save_draft(
            SaveContractDraft("p1", 0, _contract_draft())
        ),
    ),
    _WriteEntrypoint(
        "contract.confirm",
        "lock_project",
        _contract_service,
        lambda service: service.confirm(
            ConfirmContracts("p1", "confirm-1", 1, "a" * 64)
        ),
    ),
    _WriteEntrypoint(
        "contract.clone_revision",
        "lock_project",
        _contract_service,
        lambda service: service.clone_revision("p1", 1),
    ),
    _WriteEntrypoint(
        "planning.create_draft",
        "read_project_any",
        _planning_service,
        lambda service: service.create_draft(
            CreatePlanningDraft("p1", "planning-draft-1")
        ),
    ),
    _WriteEntrypoint(
        "planning.save_draft",
        "read_project_any",
        _planning_service,
        lambda service: service.save_draft(
            SavePlanningDraft(
                "p1",
                "planning-draft-1",
                1,
                "a" * 64,
                {},
                "planning-save-1",
            )
        ),
    ),
    _WriteEntrypoint(
        "planning.confirm_draft",
        "read_project_any",
        _planning_service,
        lambda service: service.confirm_draft(
            ConfirmPlanningDraft(
                "p1",
                "planning-draft-1",
                1,
                "a" * 64,
                "planning-confirm-1",
            )
        ),
    ),
    _WriteEntrypoint(
        "story.create_manual",
        "lock_project",
        _story_service,
        lambda service: service.create_manual(
            CreateManualStoryEngineBatch("p1", "manual-1", three_options())
        ),
    ),
    _WriteEntrypoint(
        "story.reserve_provider",
        "lock_project",
        _story_service,
        lambda service: service.reserve_provider(
            ReserveStoryEngineBatch("p1", "reserve-1")
        ),
    ),
    _WriteEntrypoint(
        "story.generate_provider",
        "lock_project",
        _story_service,
        lambda service: service.generate_provider(
            ReserveStoryEngineBatch("p1", "generate-1")
        ),
    ),
    _WriteEntrypoint(
        "story.mark_outcome_unknown",
        "lock_project",
        _story_service,
        lambda service: service.mark_outcome_unknown(
            "p1", "batch-1", "attempt-1"
        ),
    ),
    _WriteEntrypoint(
        "story.start_attempt",
        "lock_project",
        _story_service,
        lambda service: service.start_attempt("p1", "batch-1"),
    ),
    _WriteEntrypoint(
        "story.succeed_attempt",
        "lock_project",
        _story_service,
        lambda service: service.succeed_attempt(
            "p1", "batch-1", "attempt-1", "response", three_options()
        ),
    ),
    _WriteEntrypoint(
        "story.fail_attempt",
        "lock_project",
        _story_service,
        lambda service: service.fail_attempt(
            "p1", "batch-1", "attempt-1", "provider_failed"
        ),
    ),
    _WriteEntrypoint(
        "story.reconcile",
        "lock_project",
        _story_service,
        lambda service: service.reconcile("p1", "batch-1"),
    ),
    _WriteEntrypoint(
        "chapter.create_session",
        "lock_project",
        _chapter_service,
        lambda service: service.create_session(
            CreateChapterSession(
                "p1",
                1,
                1,
                "a" * 64,
                1,
                "b" * 64,
                0,
            )
        ),
    ),
    _WriteEntrypoint(
        "outline.create_draft",
        "lock_project",
        _outline_service,
        lambda service: service.create_draft(
            CreateChapterOutlineDraft("p1", 1)
        ),
    ),
    _WriteEntrypoint(
        "outline.save_draft",
        "lock_project",
        _outline_service,
        lambda service: service.save_draft(
            SaveChapterOutlineDraft(
                "p1",
                1,
                "outline-draft-1",
                1,
                "a" * 64,
                EditableChapterOutlineContent(),
            )
        ),
    ),
    _WriteEntrypoint(
        "outline.confirm_draft",
        "lock_project",
        _outline_service,
        lambda service: service.confirm_draft(
            ConfirmChapterOutlineDraft(
                "p1",
                1,
                "outline-draft-1",
                1,
                "a" * 64,
                0,
                "outline-confirm-1",
            )
        ),
    ),
    _WriteEntrypoint(
        "chapter.save_working_draft",
        "lock_project",
        _chapter_service,
        lambda service: service.save_working_draft(
            SaveWorkingDraft("p1", "session-1", 1, "正文")
        ),
    ),
    _WriteEntrypoint(
        "chapter.save_candidate",
        "lock_project",
        _chapter_service,
        lambda service: service.save_candidate(
            SaveDraftCandidate("p1", "session-1", 1)
        ),
    ),
    _WriteEntrypoint(
        "chapter.generate_working_draft",
        "lock_project",
        _generation_service,
        lambda service: service.generate_working_draft(
            GenerateWorkingDraft("p1", "session-1", 1)
        ),
    ),
    _WriteEntrypoint(
        "canon.commit",
        "lock_project",
        _canon_service,
        lambda service: service.commit(_canon_request()),
    ),
)


def test_planning_archived_inventory_covers_every_mutating_entrypoint():
    names = {entrypoint.name for entrypoint in WRITE_ENTRYPOINTS}
    assert {
        "planning.create_draft",
        "planning.save_draft",
        "planning.confirm_draft",
    } <= names
    assert {
        "outline.create_draft",
        "outline.save_draft",
        "outline.confirm_draft",
    } <= names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entrypoint",
    WRITE_ENTRYPOINTS,
    ids=lambda entrypoint: entrypoint.name,
)
async def test_every_active_project_write_stops_at_archived_guard(entrypoint):
    repository = _GuardProbeRepository(entrypoint.guard_name)
    provider = _ProviderProbe()
    service = entrypoint.service_factory(repository, provider)

    expected_error = (
        PlanningArchived
        if entrypoint.name.startswith("planning.")
        else (
            ChapterOutlineArchived
            if entrypoint.name.startswith("outline.")
            else http_errors.ProjectArchived
        )
    )
    with pytest.raises(expected_error):
        await entrypoint.invoke(service)

    assert repository.actions == [entrypoint.guard_name]
    assert provider.calls == 0


class _ProjectSession:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def fetchone(self, sql, args):
        self.calls.append((" ".join(sql.split()), args))
        return self.row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "expected"),
    (
        (None, None),
        ({"id": "p1", "archived_at": None}, "active"),
    ),
)
async def test_shared_active_lock_returns_none_only_for_missing_project(
    row,
    expected,
):
    session = _ProjectSession(row)

    result = await project_lifecycle.lock_active_project(session, "p1")

    assert result == (row if expected == "active" else None)
    assert session.calls == [
        ("SELECT * FROM projects WHERE id=%s FOR UPDATE", ("p1",)),
    ]


@pytest.mark.asyncio
async def test_shared_active_lock_raises_for_archived_project():
    session = _ProjectSession({"id": "p1", "archived_at": 123})

    with pytest.raises(http_errors.ProjectArchived):
        await project_lifecycle.lock_active_project(session, "p1")
