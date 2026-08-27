from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from backend.domain.manuscripts import (
    FinalChapterMissing,
    FinalChapterRecord,
    FinalOutlineProjection,
    ManuscriptChapterLookup,
    ManuscriptChapterMeta,
    ManuscriptCorrupt,
    ManuscriptDirectoryRecord,
    ManuscriptUnavailable,
    ManuscriptVolume,
    canonicalize_manuscript_volumes,
)
from backend.database import DatabaseUnavailable
from backend.services.manuscripts import (
    FinalChapterNotFound,
    ManuscriptIntegrityFailure,
    ManuscriptProjectNotFound,
    ManuscriptReadingService,
    ManuscriptTemporarilyUnavailable,
)


def _outline() -> FinalOutlineProjection:
    return FinalOutlineProjection(
        chapter_goal="Resolve the clue", expected_characters=("A",),
        continuation=("Continue",), planned_tasks=("Task",), scenes=("Scene",),
        forbidden_early_events=("Do not reveal",),
    )


def _directory(*, lifecycle="active") -> ManuscriptDirectoryRecord:
    return ManuscriptDirectoryRecord(
        project_id="project-1", title="Book", lifecycle=lifecycle,
        total_scalar_count=7,
        volumes=(
            ManuscriptVolume(id="volume-1", order=1, title="One", chapters=(
                ManuscriptChapterMeta(number=2, title="Two", scalar_count=3, finalized_at_ms=0),
            )),
            ManuscriptVolume(id="volume-2", order=2, title="Two", chapters=(
                ManuscriptChapterMeta(number=9, title="Nine", scalar_count=4, finalized_at_ms=1_000),
            )),
        ),
    )


def _chapter(*, finalized_at_ms=1_000) -> FinalChapterRecord:
    return FinalChapterRecord(
        project_id="project-1", book_title="Book", lifecycle="archived",
        number=9, title="Nine", content="正文", scalar_count=2,
        finalized_at_ms=finalized_at_ms, volume_id="volume-2", volume_order=2,
        volume_title="Two", previous_number=2, next_number=None, outline=_outline(),
    )


class TransactionProbe:
    def __init__(self):
        self.session = object()
        self.entered = self.exited = 0

    @asynccontextmanager
    async def transaction(self):
        self.entered += 1
        try:
            yield self.session
        finally:
            self.exited += 1


class Repository:
    def __init__(self, directory=_directory(), lookup=None):
        self.directory = directory
        self.lookup = lookup or ManuscriptChapterLookup(project_exists=True, chapter=_chapter())
        self.calls = []

    async def load_directory(self, session, project_id):
        self.calls.append(("directory", session, project_id))
        if isinstance(self.directory, Exception):
            raise self.directory
        return self.directory

    async def load_chapter(self, session, project_id, number):
        self.calls.append(("chapter", session, project_id, number))
        if isinstance(self.lookup, Exception):
            raise self.lookup
        return self.lookup


def _service(repository=None):
    transactions = TransactionProbe()
    repository = repository or Repository()
    return ManuscriptReadingService(transactions.transaction, repository), transactions, repository


@pytest.mark.asyncio
async def test_directory_is_metadata_only_canonical_and_uses_one_read_transaction():
    service, transactions, repository = _service()

    result = await service.directory("project-1")

    assert result.model_dump(by_alias=True, mode="json") == {
        "projectId": "project-1", "title": "Book", "lifecycle": "active",
        "summary": {"finalChapterCount": 2, "totalScalarCount": 7},
        "volumes": [
            {"id": "volume-1", "order": 1, "title": "One", "chapters": [
                {"number": 2, "title": "Two", "scalarCount": 3, "finalizedAt": "1970-01-01T00:00:00Z"},
            ]},
            {"id": "volume-2", "order": 2, "title": "Two", "chapters": [
                {"number": 9, "title": "Nine", "scalarCount": 4, "finalizedAt": "1970-01-01T00:00:01Z"},
            ]},
        ],
    }
    assert transactions.entered == transactions.exited == 1
    assert repository.calls == [("directory", transactions.session, "project-1")]


@pytest.mark.asyncio
async def test_chapter_exposes_only_target_content_outline_and_actual_navigation():
    service, transactions, repository = _service()

    result = await service.chapter("project-1", 9)

    assert result.model_dump(by_alias=True, mode="json") == {
        "projectId": "project-1", "projectTitle": "Book", "lifecycle": "archived",
        "volume": {"id": "volume-2", "order": 2, "title": "Two"},
        "chapter": {"number": 9, "title": "Nine", "content": "正文", "scalarCount": 2, "finalizedAt": "1970-01-01T00:00:01Z"},
        "outline": {"chapterGoal": "Resolve the clue", "expectedCharacters": ["A"], "continuation": ["Continue"], "plannedTasks": ["Task"], "scenes": ["Scene"], "forbiddenEarlyEvents": ["Do not reveal"]},
        "navigation": {"previousChapterNumber": 2, "nextChapterNumber": None},
    }
    assert transactions.entered == transactions.exited == 1
    assert repository.calls == [("chapter", transactions.session, "project-1", 9)]


@pytest.mark.asyncio
async def test_service_maps_missing_corrupt_unavailable_and_invalid_timestamp_to_narrow_errors():
    cases = [
        (Repository(directory=None), "directory", ManuscriptProjectNotFound),
        (Repository(lookup=ManuscriptChapterLookup(project_exists=False, chapter=None)), "chapter", ManuscriptProjectNotFound),
        (Repository(lookup=ManuscriptChapterLookup(project_exists=True, chapter=None)), "chapter", FinalChapterNotFound),
        (Repository(directory=ManuscriptCorrupt()), "directory", ManuscriptIntegrityFailure),
        (Repository(directory=ManuscriptUnavailable()), "directory", ManuscriptTemporarilyUnavailable),
        (Repository(lookup=ManuscriptChapterLookup(project_exists=True, chapter=_chapter(finalized_at_ms=253_402_300_800_000))), "chapter", ManuscriptIntegrityFailure),
    ]
    for repository, operation, expected in cases:
        service, transactions, _ = _service(repository)
        with pytest.raises(expected):
            await getattr(service, operation)("project-1", 9) if operation == "chapter" else await service.directory("project-1")
        assert transactions.entered == transactions.exited == 1


@pytest.mark.asyncio
async def test_service_maps_repository_missing_final_chapter_to_not_found_not_integrity():
    service, transactions, _ = _service(Repository(lookup=FinalChapterMissing()))

    with pytest.raises(FinalChapterNotFound):
        await service.chapter("project-1", 9)

    assert transactions.entered == transactions.exited == 1


class FailingTransaction:
    def __init__(self, error, *, exit_error=False):
        self.error = error
        self.exit_error = exit_error

    def __call__(self):
        return self

    async def __aenter__(self):
        if not self.exit_error:
            raise self.error
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        if self.exit_error:
            raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_error", [False, True])
async def test_service_maps_database_read_only_boundary_availability_to_temporary_unavailable(exit_error):
    service = ManuscriptReadingService(
        FailingTransaction(DatabaseUnavailable(), exit_error=exit_error), Repository(),
    )

    with pytest.raises(ManuscriptTemporarilyUnavailable):
        await service.directory("project-1")


@pytest.mark.asyncio
async def test_service_preserves_task3_canonicalized_order_gaps_and_total_without_reconstruction():
    unordered = (
        ManuscriptVolume(id="later", order=2, title="Later", chapters=(
            ManuscriptChapterMeta(number=9, title="Nine", scalar_count=4, finalized_at_ms=1_000),
        )),
        ManuscriptVolume(id="first", order=1, title="First", chapters=(
            ManuscriptChapterMeta(number=2, title="Two", scalar_count=3, finalized_at_ms=0),
        )),
    )
    canonical = canonicalize_manuscript_volumes(unordered)
    record = ManuscriptDirectoryRecord(
        project_id="project-1", title="Book", lifecycle="archived",
        volumes=canonical, total_scalar_count=7,
    )
    service, _, _ = _service(Repository(directory=record))

    result = await service.directory("project-1")

    assert [volume.id for volume in result.volumes] == ["first", "later"]
    assert [chapter.number for volume in result.volumes for chapter in volume.chapters] == [2, 9]
    assert result.summary.total_scalar_count == 7


def test_public_dtos_forbid_unknown_fields_and_content_exists_only_on_target_chapter():
    from pydantic import ValidationError
    from backend.services.manuscripts import (
        ManuscriptChapterResponse,
        ManuscriptDirectoryResponse,
        ManuscriptSummaryResponse,
    )

    with pytest.raises(ValidationError):
        ManuscriptDirectoryResponse(projectId="project-1", title="Book", lifecycle="active", summary=ManuscriptSummaryResponse(finalChapterCount=0, totalScalarCount=0), volumes=(), internal="hash")
    with pytest.raises(ValidationError):
        ManuscriptChapterResponse(number=1, title="One", content="prose", scalarCount=1, finalizedAt="1970-01-01T00:00:00Z", revision="raw")
