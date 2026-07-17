from __future__ import annotations

import pytest

from backend import http_errors
from backend.repositories import project_lifecycle
from backend.repositories.canon import CanonRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.contracts import ContractRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.planning import PlanningRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.repositories.story_engines import StoryEngineRepository
from backend.services.canon import CanonService
from backend.services.chapter_draft_generation import ChapterDraftGenerationService
from backend.services.chapter_sessions import ChapterSessionService
from backend.services.contracts import ContractService
from backend.services.model_bindings import ModelBindingService
from backend.services.planning import PlanningService
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.seeds import SeedService
from backend.services.story_engines import StoryEngineService


@pytest.mark.parametrize(
    ("service_type", "repository", "guard_name"),
    (
        (ProjectLifecycleService, ProjectRepository(), "lock_active_project"),
        (SeedService, SeedRepository(), "lock_project"),
        (ModelBindingService, ModelBindingRepository(), "lock_project"),
        (ContractService, ContractRepository(), "lock_project"),
        (PlanningService, PlanningRepository(), "lock_project"),
        (StoryEngineService, StoryEngineRepository(), "lock_project"),
        (ChapterSessionService, ChapterSessionRepository(), "lock_project"),
        (
            ChapterDraftGenerationService,
            ChapterSessionRepository(),
            "lock_project",
        ),
        (CanonService, CanonRepository(), "lock_project"),
    ),
)
def test_project_write_service_repository_has_an_active_project_guard(
    service_type,
    repository,
    guard_name,
):
    assert callable(getattr(service_type, "__init__", None))
    assert callable(getattr(repository, guard_name, None)), (
        f"{service_type.__name__} repository lacks {guard_name}"
    )


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
