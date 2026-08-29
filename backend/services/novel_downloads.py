"""Read-only application service for finalized novel downloads."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.novel_downloads import (
    DownloadFormat,
    NovelDownloadSelector,
    SafeAttachmentNames,
    render_novel_download,
    safe_attachment_names,
)
from backend.repositories.novel_downloads import NovelDownloadRepository


class NovelDownloadProjectNotFound(LookupError):
    """The requested project does not exist."""


class NovelDownloadUnavailable(RuntimeError):
    """The project exists but has no finalized chapters to download."""


class _PublicDownloadValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class NovelDownloadVolume(_PublicDownloadValue):
    id: str
    order: int
    title: str


class NovelDownloadChapter(_PublicDownloadValue):
    number: int
    title: str
    volume_id: str = Field(alias="volumeId")


class NovelDownloadOptions(_PublicDownloadValue):
    available: bool
    reason: str | None
    formats: tuple[DownloadFormat, ...]
    volumes: tuple[NovelDownloadVolume, ...]
    chapters: tuple[NovelDownloadChapter, ...]


@dataclass(frozen=True, slots=True)
class NovelDownloadResult:
    content: bytes
    media_type: str
    attachment_names: SafeAttachmentNames


class NovelDownloadService:
    """Load one verified immutable snapshot per request and expose it safely."""

    def __init__(self, transaction_factory, repository: NovelDownloadRepository):
        self._transaction_factory = transaction_factory
        self._repository = repository

    async def _metadata(self, project_id: str):
        async with self._transaction_factory() as session:
            metadata = await self._repository.load_finalized_metadata(session, project_id)
        if metadata is None:
            raise NovelDownloadProjectNotFound()
        return metadata

    async def _snapshot(
        self,
        project_id: str,
        selector: NovelDownloadSelector,
    ):
        async with self._transaction_factory() as session:
            snapshot = await self._repository.load_finalized_snapshot(
                session,
                project_id,
                selector,
            )
        if snapshot is None:
            raise NovelDownloadProjectNotFound()
        return snapshot

    async def options(self, project_id: str) -> NovelDownloadOptions:
        metadata = await self._metadata(project_id)
        chapters = tuple(sorted(metadata.chapters, key=lambda chapter: chapter.chapter_number))
        volumes_by_id = {
            chapter.volume_id: NovelDownloadVolume(
                id=chapter.volume_id,
                order=chapter.volume_order,
                title=chapter.volume_title,
            )
            for chapter in chapters
        }
        return NovelDownloadOptions(
            available=bool(chapters),
            reason=None if chapters else "no_finalized_chapters",
            formats=(DownloadFormat.TXT, DownloadFormat.MARKDOWN),
            volumes=tuple(sorted(
                volumes_by_id.values(), key=lambda volume: (volume.order, volume.id),
            )),
            chapters=tuple(
                NovelDownloadChapter(
                    number=chapter.chapter_number,
                    title=chapter.chapter_title,
                    volumeId=chapter.volume_id,
                )
                for chapter in chapters
            ),
        )

    async def download(
        self,
        project_id: str,
        selector: NovelDownloadSelector,
    ) -> NovelDownloadResult:
        if not isinstance(selector, NovelDownloadSelector):
            raise TypeError("selector must be a NovelDownloadSelector")
        selector = NovelDownloadSelector.model_validate(
            selector.model_dump(mode="python"),
        )
        snapshot = await self._snapshot(project_id, selector)
        if not snapshot.chapters:
            raise NovelDownloadUnavailable()
        return NovelDownloadResult(
            content=render_novel_download(snapshot, selector),
            media_type=(
                "text/plain; charset=utf-8"
                if selector.format is DownloadFormat.TXT
                else "text/markdown; charset=utf-8"
            ),
            attachment_names=safe_attachment_names(snapshot.book_title, selector.format),
        )


__all__ = (
    "NovelDownloadChapter",
    "NovelDownloadOptions",
    "NovelDownloadProjectNotFound",
    "NovelDownloadResult",
    "NovelDownloadService",
    "NovelDownloadUnavailable",
    "NovelDownloadVolume",
)
