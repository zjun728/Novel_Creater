from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256

import pytest

from backend.domain.novel_downloads import (
    DownloadFormat,
    DownloadScope,
    FinalizedChapterSnapshot,
    NovelDownloadIntegrityError,
    NovelDownloadScopeNotFoundError,
    NovelDownloadSelector,
    NovelDownloadSnapshot,
)
from backend.services.novel_downloads import (
    NovelDownloadProjectNotFound,
    NovelDownloadUnavailable,
    NovelDownloadService,
)


def _chapter(number: int, *, volume_id: str, order: int, title: str):
    prose = f"终稿正文 {number}"
    return FinalizedChapterSnapshot(
        chapter_number=number,
        chapter_title=f"章节 {number}",
        volume_id=volume_id,
        volume_order=order,
        volume_title=title,
        content=prose,
        content_hash=sha256(prose.encode()).hexdigest(),
    )


def _snapshot(*chapters):
    return NovelDownloadSnapshot(book_title="下载书名", chapters=tuple(chapters))


class FakeRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    async def load_finalized_snapshot(self, session, project_id):
        self.calls.append((session, project_id))
        return self.snapshot


class TransactionRecorder:
    def __init__(self):
        self.session = object()
        self.entered = 0
        self.exited = 0

    @asynccontextmanager
    async def transaction(self):
        self.entered += 1
        try:
            yield self.session
        finally:
            self.exited += 1


def _service(snapshot):
    transactions = TransactionRecorder()
    repository = FakeRepository(snapshot)
    return NovelDownloadService(transactions.transaction, repository), transactions, repository


@pytest.mark.asyncio
async def test_options_returns_only_sorted_safe_projection():
    service, transactions, repository = _service(_snapshot(
        _chapter(9, volume_id="v-late", order=2, title="后卷"),
        _chapter(2, volume_id="v-first", order=1, title="首卷"),
        _chapter(1, volume_id="v-first", order=1, title="首卷"),
    ))

    options = await service.options("project-1")

    assert options.model_dump(by_alias=True, mode="json") == {
        "available": True,
        "reason": None,
        "formats": ["txt", "markdown"],
        "volumes": [
            {"id": "v-first", "order": 1, "title": "首卷"},
            {"id": "v-late", "order": 2, "title": "后卷"},
        ],
        "chapters": [
            {"number": 1, "title": "章节 1", "volumeId": "v-first"},
            {"number": 2, "title": "章节 2", "volumeId": "v-first"},
            {"number": 9, "title": "章节 9", "volumeId": "v-late"},
        ],
    }
    assert transactions.entered == transactions.exited == 1
    assert repository.calls == [(transactions.session, "project-1")]


@pytest.mark.asyncio
async def test_options_distinguishes_missing_and_empty_finalized_project():
    missing, _, _ = _service(None)
    with pytest.raises(NovelDownloadProjectNotFound):
        await missing.options("missing-project")

    empty, transactions, _ = _service(_snapshot())
    options = await empty.options("existing-project")
    assert options.model_dump(by_alias=True, mode="json") == {
        "available": False,
        "reason": "no_finalized_chapters",
        "formats": ["txt", "markdown"],
        "volumes": [],
        "chapters": [],
    }
    assert transactions.entered == transactions.exited == 1


@pytest.mark.asyncio
async def test_download_renders_domain_result_with_safe_attachment_names():
    service, _, _ = _service(_snapshot(_chapter(1, volume_id="v1", order=1, title="卷一")))

    result = await service.download("project-1", NovelDownloadSelector(
        scope=DownloadScope.BOOK, format=DownloadFormat.MARKDOWN,
    ))

    assert result.content == "# 下载书名\n\n## 第 1 卷 · 卷一\n\n### 第 1 章 · 章节 1\n\n终稿正文 1\n".encode()
    assert result.media_type == "text/markdown; charset=utf-8"
    assert result.attachment_names.ascii_filename.endswith(".md")
    assert result.attachment_names.unicode_filename == "下载书名.md"


@pytest.mark.asyncio
async def test_download_maps_missing_and_empty_projects_to_narrow_errors():
    missing, _, _ = _service(None)
    empty, transactions, _ = _service(_snapshot())
    selector = NovelDownloadSelector(scope=DownloadScope.BOOK, format=DownloadFormat.TXT)

    with pytest.raises(NovelDownloadProjectNotFound):
        await missing.download("missing-project", selector)
    with pytest.raises(NovelDownloadUnavailable):
        await empty.download("existing-project", selector)
    assert transactions.entered == transactions.exited == 1


@pytest.mark.asyncio
async def test_download_preserves_scope_and_integrity_errors_and_closes_transaction():
    service, transactions, _ = _service(_snapshot(_chapter(1, volume_id="v1", order=1, title="卷一")))
    missing_scope = NovelDownloadSelector(scope=DownloadScope.CHAPTER, format=DownloadFormat.TXT, chapter_number=2)
    with pytest.raises(NovelDownloadScopeNotFoundError):
        await service.download("project-1", missing_scope)

    tampered = _chapter(1, volume_id="v1", order=1, title="卷一").model_copy(update={"content_hash": "0" * 64})
    integrity, integrity_transactions, _ = _service(_snapshot(tampered))
    with pytest.raises(NovelDownloadIntegrityError):
        await integrity.download("project-1", NovelDownloadSelector(scope=DownloadScope.BOOK, format=DownloadFormat.TXT))
    assert transactions.entered == transactions.exited == 1
    assert integrity_transactions.entered == integrity_transactions.exited == 1
