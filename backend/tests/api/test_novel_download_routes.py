from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.novel_downloads import (
    DownloadFormat,
    NovelDownloadIntegrityError,
    NovelDownloadScopeNotFoundError,
    SafeAttachmentNames,
)
from backend.domain.routers import novel_downloads
from backend.security.redaction import install_error_handlers
from backend.services.novel_downloads import (
    NovelDownloadOptions,
    NovelDownloadChapter,
    NovelDownloadProjectNotFound,
    NovelDownloadResult,
    NovelDownloadUnavailable,
    NovelDownloadVolume,
)


class FakeNovelDownloadService:
    def __init__(self):
        self.error = None
        self.options_calls = []
        self.download_calls = []
        self.options_value = NovelDownloadOptions(
            available=True,
            reason=None,
            formats=(DownloadFormat.TXT, DownloadFormat.MARKDOWN),
            volumes=(),
            chapters=(),
        )

    async def options(self, project_id):
        self.options_calls.append(project_id)
        if self.error:
            raise self.error
        return self.options_value

    async def download(self, project_id, selector):
        self.download_calls.append((project_id, selector))
        if self.error:
            raise self.error
        return NovelDownloadResult(
            content=b"finalized bytes\n",
            media_type=(
                "text/plain; charset=utf-8"
                if selector.format is DownloadFormat.TXT
                else "text/markdown; charset=utf-8"
            ),
            attachment_names=SafeAttachmentNames(
                ascii_filename="novel-download.txt" if selector.format is DownloadFormat.TXT else "novel-download.md",
                unicode_filename="终稿下载.txt" if selector.format is DownloadFormat.TXT else "终稿下载.md",
            ),
        )


def _client():
    service = FakeNovelDownloadService()
    app = FastAPI()
    app.include_router(novel_downloads.router, prefix="/api")
    app.dependency_overrides[novel_downloads.get_novel_download_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_options_is_a_narrow_safe_projection():
    client, service = _client()
    service.options_value = NovelDownloadOptions(
        available=True,
        reason=None,
        formats=(DownloadFormat.TXT, DownloadFormat.MARKDOWN),
        volumes=(NovelDownloadVolume(id="active-or-archived", order=1, title="卷名"),),
        chapters=(NovelDownloadChapter(number=1, title="章名", volumeId="active-or-archived"),),
    )

    response = client.get("/api/projects/project-1/novel-download/options")

    assert response.status_code == 200
    assert response.json() == {
        "available": True, "reason": None, "formats": ["txt", "markdown"],
        "volumes": [{"id": "active-or-archived", "order": 1, "title": "卷名"}],
        "chapters": [{"number": 1, "title": "章名", "volumeId": "active-or-archived"}],
    }
    assert service.options_calls == ["project-1"]


def test_download_returns_exact_bytes_and_safe_attachment_headers_for_txt_and_markdown():
    client, service = _client()

    txt = client.get("/api/projects/project-1/novel-download?scope=book&format=txt")
    markdown = client.get("/api/projects/project-1/novel-download?scope=chapter&format=markdown&chapterNumber=1")

    assert txt.status_code == markdown.status_code == 200
    assert txt.content == markdown.content == b"finalized bytes\n"
    assert txt.headers["content-type"] == "text/plain; charset=utf-8"
    assert markdown.headers["content-type"] == "text/markdown; charset=utf-8"
    assert txt.headers["content-disposition"] == "attachment; filename=\"novel-download.txt\"; filename*=UTF-8''%E7%BB%88%E7%A8%BF%E4%B8%8B%E8%BD%BD.txt"
    assert markdown.headers["content-disposition"] == "attachment; filename=\"novel-download.md\"; filename*=UTF-8''%E7%BB%88%E7%A8%BF%E4%B8%8B%E8%BD%BD.md"
    assert txt.headers["cache-control"] == markdown.headers["cache-control"] == "private, no-store"
    assert txt.headers["x-content-type-options"] == markdown.headers["x-content-type-options"] == "nosniff"
    assert service.download_calls[0][1].scope.value == "book"
    assert service.download_calls[1][1].chapter_number == 1


def test_download_accepts_volume_and_active_or_archived_project_ids_without_lifecycle_filtering():
    client, service = _client()

    active = client.get("/api/projects/active-project/novel-download?scope=volume&format=txt&volumeId=archived-volume")
    archived = client.get("/api/projects/archived-project/novel-download?scope=book&format=txt")

    assert active.status_code == archived.status_code == 200
    assert [item[0] for item in service.download_calls] == ["active-project", "archived-project"]
    assert service.download_calls[0][1].volume_id == "archived-volume"


def test_safe_public_errors_do_not_expose_internal_sentinels_in_body_or_headers():
    client, service = _client()
    cases = [
        (NovelDownloadProjectNotFound("RAW_PROSE_SENTINEL HASH_SENTINEL"), 404),
        (NovelDownloadScopeNotFoundError("RAW_PROSE_SENTINEL HASH_SENTINEL"), 404),
        (NovelDownloadUnavailable("RAW_PROSE_SENTINEL HASH_SENTINEL"), 409),
        (NovelDownloadIntegrityError("RAW_PROSE_SENTINEL HASH_SENTINEL"), 500),
    ]
    for error, status in cases:
        service.error = error
        response = client.get("/api/projects/project-1/novel-download?scope=book&format=txt")
        assert response.status_code == status
        assert "RAW_PROSE_SENTINEL" not in response.text
        assert "HASH_SENTINEL" not in response.text
        assert all("RAW_PROSE_SENTINEL" not in value for value in response.headers.values())
        assert set(response.json()) == {"code", "message", "correlationId"}


def test_query_model_rejects_missing_unknown_and_contradictory_selectors():
    client, service = _client()
    urls = [
        "/api/projects/project-1/novel-download",
        "/api/projects/project-1/novel-download?scope=unknown&format=txt",
        "/api/projects/project-1/novel-download?scope=book&format=txt&volumeId=v1",
        "/api/projects/project-1/novel-download?scope=volume&format=txt",
        "/api/projects/project-1/novel-download?scope=chapter&format=txt",
        "/api/projects/project-1/novel-download?scope=chapter&format=txt&chapterNumber=0",
        "/api/projects/project-1/novel-download?scope=chapter&format=txt&chapterNumber=1&volumeId=v1",
        "/api/projects/project-1/novel-download?scope=book&format=txt&unexpected=RAW_PROSE_SENTINEL",
    ]

    responses = [client.get(url) for url in urls]

    assert [response.status_code for response in responses] == [422] * len(urls)
    assert service.download_calls == []
    assert all("RAW_PROSE_SENTINEL" not in response.text for response in responses)
