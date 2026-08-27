"""Safe public projections for finalized manuscript reading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
)
from backend.repositories.manuscripts import ManuscriptRepository


class ManuscriptProjectNotFound(LookupError):
    """The requested project does not exist."""


class FinalChapterNotFound(LookupError):
    """The requested finalized chapter does not exist."""


class ManuscriptIntegrityFailure(RuntimeError):
    """Stored finalized manuscript data failed validation."""


class ManuscriptTemporarilyUnavailable(RuntimeError):
    """The finalized manuscript store is temporarily unavailable."""


class _PublicManuscriptValue(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", populate_by_name=True,
    )


class ManuscriptSummaryResponse(_PublicManuscriptValue):
    final_chapter_count: int = Field(alias="finalChapterCount", ge=0)
    total_scalar_count: int = Field(alias="totalScalarCount", ge=0)


class ManuscriptChapterMetaResponse(_PublicManuscriptValue):
    number: int = Field(ge=1)
    title: str
    scalar_count: int = Field(alias="scalarCount", ge=0)
    finalized_at: str = Field(alias="finalizedAt")


class ManuscriptVolumeResponse(_PublicManuscriptValue):
    id: str
    order: int = Field(ge=1)
    title: str
    chapters: tuple[ManuscriptChapterMetaResponse, ...]


class ManuscriptDirectoryResponse(_PublicManuscriptValue):
    project_id: str = Field(alias="projectId")
    title: str
    lifecycle: Literal["active", "archived"]
    summary: ManuscriptSummaryResponse
    volumes: tuple[ManuscriptVolumeResponse, ...]


class ManuscriptVolumeDetailResponse(_PublicManuscriptValue):
    id: str
    order: int = Field(ge=1)
    title: str


class ManuscriptChapterResponse(_PublicManuscriptValue):
    number: int = Field(ge=1)
    title: str
    content: str
    scalar_count: int = Field(alias="scalarCount", ge=0)
    finalized_at: str = Field(alias="finalizedAt")


class ManuscriptOutlineResponse(_PublicManuscriptValue):
    chapter_goal: str = Field(alias="chapterGoal")
    expected_characters: tuple[str, ...] = Field(alias="expectedCharacters")
    continuation: tuple[str, ...]
    planned_tasks: tuple[str, ...] = Field(alias="plannedTasks")
    scenes: tuple[str, ...]
    forbidden_early_events: tuple[str, ...] = Field(alias="forbiddenEarlyEvents")


class ManuscriptNavigationResponse(_PublicManuscriptValue):
    previous_chapter_number: int | None = Field(alias="previousChapterNumber")
    next_chapter_number: int | None = Field(alias="nextChapterNumber")


class ManuscriptChapterDetailResponse(_PublicManuscriptValue):
    project_id: str = Field(alias="projectId")
    project_title: str = Field(alias="projectTitle")
    lifecycle: Literal["active", "archived"]
    volume: ManuscriptVolumeDetailResponse
    chapter: ManuscriptChapterResponse
    outline: ManuscriptOutlineResponse
    navigation: ManuscriptNavigationResponse


def _utc_timestamp(milliseconds: object) -> str:
    if type(milliseconds) is not int or milliseconds < 0:
        raise ManuscriptIntegrityFailure() from None
    try:
        instant = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=milliseconds)
    except (OverflowError, ValueError):
        raise ManuscriptIntegrityFailure() from None
    rendered = instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return rendered.replace(".000Z", "Z")


def _chapter_meta(value: ManuscriptChapterMeta) -> ManuscriptChapterMetaResponse:
    return ManuscriptChapterMetaResponse(
        number=value.number, title=value.title, scalarCount=value.scalar_count,
        finalizedAt=_utc_timestamp(value.finalized_at_ms),
    )


def _outline(value: FinalOutlineProjection) -> ManuscriptOutlineResponse:
    return ManuscriptOutlineResponse(
        chapterGoal=value.chapter_goal, expectedCharacters=value.expected_characters,
        continuation=value.continuation, plannedTasks=value.planned_tasks,
        scenes=value.scenes, forbiddenEarlyEvents=value.forbidden_early_events,
    )


class ManuscriptReadingService:
    """Read one pre-validated finalized-manuscript record per request."""

    def __init__(self, transaction_factory, repository: ManuscriptRepository | None = None):
        self._transaction_factory = transaction_factory
        self._repository = repository or ManuscriptRepository()

    async def directory(self, project_id: str) -> ManuscriptDirectoryResponse:
        try:
            async with self._transaction_factory() as session:
                record = await self._repository.load_directory(session, project_id)
        except ManuscriptUnavailable:
            raise ManuscriptTemporarilyUnavailable() from None
        except ManuscriptCorrupt:
            raise ManuscriptIntegrityFailure() from None
        if record is None:
            raise ManuscriptProjectNotFound()
        return self._directory_response(record)

    async def chapter(
        self, project_id: str, chapter_number: int,
    ) -> ManuscriptChapterDetailResponse:
        try:
            async with self._transaction_factory() as session:
                lookup = await self._repository.load_chapter(session, project_id, chapter_number)
        except ManuscriptUnavailable:
            raise ManuscriptTemporarilyUnavailable() from None
        except (ManuscriptCorrupt, FinalChapterMissing):
            raise ManuscriptIntegrityFailure() from None
        if not lookup.project_exists:
            raise ManuscriptProjectNotFound()
        if lookup.chapter is None:
            raise FinalChapterNotFound()
        return self._chapter_response(lookup.chapter)

    @staticmethod
    def _directory_response(record: ManuscriptDirectoryRecord) -> ManuscriptDirectoryResponse:
        volumes = tuple(
            ManuscriptVolumeResponse(
                id=volume.id, order=volume.order, title=volume.title,
                chapters=tuple(_chapter_meta(chapter) for chapter in volume.chapters),
            )
            for volume in record.volumes
        )
        return ManuscriptDirectoryResponse(
            projectId=record.project_id, title=record.title, lifecycle=record.lifecycle,
            summary=ManuscriptSummaryResponse(
                finalChapterCount=sum(len(volume.chapters) for volume in record.volumes),
                totalScalarCount=record.total_scalar_count,
            ), volumes=volumes,
        )

    @staticmethod
    def _chapter_response(record: FinalChapterRecord) -> ManuscriptChapterDetailResponse:
        return ManuscriptChapterDetailResponse(
            projectId=record.project_id, projectTitle=record.book_title,
            lifecycle=record.lifecycle,
            volume=ManuscriptVolumeDetailResponse(
                id=record.volume_id, order=record.volume_order, title=record.volume_title,
            ), chapter=ManuscriptChapterResponse(
                number=record.number, title=record.title, content=record.content,
                scalarCount=record.scalar_count,
                finalizedAt=_utc_timestamp(record.finalized_at_ms),
            ), outline=_outline(record.outline), navigation=ManuscriptNavigationResponse(
                previousChapterNumber=record.previous_number,
                nextChapterNumber=record.next_number,
            ),
        )


__all__ = (
    "FinalChapterNotFound", "ManuscriptChapterDetailResponse",
    "ManuscriptDirectoryResponse", "ManuscriptIntegrityFailure",
    "ManuscriptProjectNotFound", "ManuscriptReadingService",
    "ManuscriptTemporarilyUnavailable",
)
