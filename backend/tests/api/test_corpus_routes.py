from __future__ import annotations

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import transaction
from backend.domain.corpus import (
    FRAGMENT_PAGE_DEFAULT,
    FRAGMENT_PAGE_MAX,
    FRAGMENT_PREVIEW_CHARS,
    PREVIEW_DEFAULT_CHARS,
    PREVIEW_MAX_CHARS,
)
from backend.http_errors import (
    CorpusImportConflict,
    CorpusImportFailed,
    CorpusRequestInvalid,
    CorpusResourceNotFound,
)
from backend.routers import corpus
from backend.security.redaction import install_error_handlers
from backend.services.corpus_import import CorpusImportService


SOURCE_ID = "11111111-1111-1111-1111-111111111111"
CHAPTER_ID = "22222222-2222-2222-2222-222222222222"
IMPORT_ID = "33333333-3333-3333-3333-333333333333"


class FakeCorpusService:
    def __init__(self):
        self.calls = []
        self.failure = None

    def _raise(self):
        if self.failure:
            raise self.failure

    async def discovery(self, cursor=None, limit=50):
        self.calls.append(("discovery", cursor, limit))
        self._raise()
        return {
            "items": [{
                "relativePath": "safe/book.txt", "byteSize": 321,
                "preflightStatus": "eligible",
            }],
            "nextCursor": None,
            "reasonCounts": {
                "nonTxt": 1,
                "C:/private/ROOT_SENTINEL": 999,
            },
            "scanStrategy": "recursive",
            "root": "C:/private/ROOT_SENTINEL",
        }

    async def import_source(self, relative_path, idempotency_key):
        self.calls.append(("import", relative_path, idempotency_key))
        self._raise()
        return {
            "id": IMPORT_ID, "status": "succeeded", "source_id": SOURCE_ID,
            "relative_path": relative_path, "source_hash": "a" * 64,
            "public_error_code": None, "absolute_path": "C:/private/SECRET",
        }

    async def get_import(self, import_id):
        self.calls.append(("get-import", import_id))
        self._raise()
        return {
            "id": import_id, "status": "succeeded", "source_id": SOURCE_ID,
            "relative_path": "safe/book.txt", "source_hash": "a" * 64,
            "public_error_code": None,
        }

    async def list_sources(self):
        self.calls.append(("list-sources",))
        self._raise()
        return ({
            "id": SOURCE_ID, "title": "book", "relative_path": "safe/book.txt",
            "source_hash": "a" * 64, "encoding": "utf-8", "status": "analyzed",
            "chapter_count": 2, "fragment_count": 4,
            "normalized_text": "FULL_BOOK_SENTINEL",
        },)

    async def get_source(self, source_id, preview_chars):
        self.calls.append(("get-source", source_id, preview_chars))
        self._raise()
        return {
            "id": source_id, "title": "book", "relative_path": "safe/book.txt",
            "source_hash": "a" * 64, "encoding": "utf-8", "status": "analyzed",
            "chapter_count": 2, "fragment_count": 4,
            "preview": "预" * preview_chars,
            "normalized_text": "FULL_BOOK_SENTINEL",
        }

    async def list_chapters(self, source_id):
        self.calls.append(("chapters", source_id))
        self._raise()
        return ({
            "id": CHAPTER_ID, "chapter_order": 1, "title": "第一章",
            "raw_byte_start": 0, "raw_byte_end": 50,
            "normalized_char_start": 0, "normalized_char_end": 20,
            "content_hash": "b" * 64, "normalized_text": "CHAPTER_SENTINEL",
        },)

    async def list_fragments(self, chapter_id, cursor, limit):
        self.calls.append(("fragments", chapter_id, cursor, limit))
        self._raise()
        items = tuple({
            "id": f"fragment-{index}", "fragment_order": index,
            "chapter_char_start": (index - 1) * 300,
            "chapter_char_end": index * 300,
            "content_hash": "c" * 64,
            "normalized_text": "片" * 500,
            "index_payload": {"secret": "SECRET_INDEX_SENTINEL"},
        } for index in range(1, limit + 1))
        return {"items": items, "nextCursor": None}


def make_client():
    service = FakeCorpusService()
    app = FastAPI()
    app.include_router(corpus.router, prefix="/api")
    app.dependency_overrides[corpus.get_corpus_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def _assert_safe(body):
    rendered = json.dumps(body, ensure_ascii=False)
    for sentinel in (
        "C:/private", "FULL_BOOK_SENTINEL", "CHAPTER_SENTINEL",
        "SECRET_INDEX_SENTINEL", "password", "baseUrl", "dsn",
    ):
        assert sentinel not in rendered


def test_corpus_routes_are_exact_and_all_dtos_are_allowlisted():
    client, _ = make_client()
    responses = (
        client.get("/api/corpus/discovery"),
        client.post("/api/corpus/imports", json={
            "idempotencyKey": "k" * 32, "relativePath": "safe/book.txt",
        }),
        client.get(f"/api/corpus/imports/{IMPORT_ID}"),
        client.get("/api/corpus/sources"),
        client.get(f"/api/corpus/sources/{SOURCE_ID}"),
        client.get(f"/api/corpus/sources/{SOURCE_ID}/chapters"),
        client.get(f"/api/corpus/chapters/{CHAPTER_ID}/fragments"),
    )
    assert [response.status_code for response in responses] == [200] * 7
    bodies = [response.json() for response in responses]
    assert set(bodies[0]) == {"items", "nextCursor", "reasonCounts", "scanStrategy"}
    assert set(bodies[1]) == {
        "importId", "status", "sourceId", "relativePath", "shortHash", "errorCode"
    }
    assert set(bodies[3]) == {"items"}
    assert set(bodies[4]) == {
        "id", "name", "relativePath", "shortHash", "encoding", "state",
        "chapterCount", "fragmentCount", "preview",
    }
    assert set(bodies[5]["items"][0]) == {
        "id", "order", "title", "byteStart", "byteEnd", "charStart",
        "charEnd", "shortHash",
    }
    assert all(set(item) == {
        "id", "order", "charStart", "charEnd", "shortHash", "preview",
    } for item in bodies[6]["items"])
    for body in bodies:
        _assert_safe(body)
    methods = {route.path: route.methods for route in corpus.router.routes}
    assert methods == {
        "/corpus/discovery": {"GET"},
        "/corpus/imports": {"POST"},
        "/corpus/imports/{import_id}": {"GET"},
        "/corpus/sources": {"GET"},
        "/corpus/sources/{source_id}": {"GET"},
        "/corpus/sources/{source_id}/chapters": {"GET"},
        "/corpus/chapters/{chapter_id}/fragments": {"GET"},
    }


def test_preview_and_fragment_limits_are_server_bounded():
    client, service = make_client()

    default_source = client.get(f"/api/corpus/sources/{SOURCE_ID}")
    max_source = client.get(
        f"/api/corpus/sources/{SOURCE_ID}?previewChars={PREVIEW_MAX_CHARS}"
    )
    too_large = client.get(
        f"/api/corpus/sources/{SOURCE_ID}?previewChars={PREVIEW_MAX_CHARS + 1}"
    )
    default_fragments = client.get(
        f"/api/corpus/chapters/{CHAPTER_ID}/fragments"
    )
    max_fragments = client.get(
        f"/api/corpus/chapters/{CHAPTER_ID}/fragments?limit={FRAGMENT_PAGE_MAX}"
    )
    too_many = client.get(
        f"/api/corpus/chapters/{CHAPTER_ID}/fragments?limit={FRAGMENT_PAGE_MAX + 1}"
    )

    assert len(default_source.json()["preview"]) == PREVIEW_DEFAULT_CHARS
    assert len(max_source.json()["preview"]) == PREVIEW_MAX_CHARS
    assert too_large.status_code == 422
    assert len(default_fragments.json()["items"]) == FRAGMENT_PAGE_DEFAULT
    assert len(max_fragments.json()["items"]) == FRAGMENT_PAGE_MAX
    assert too_many.status_code == 422
    assert all(
        len(item["preview"]) <= FRAGMENT_PREVIEW_CHARS
        for item in max_fragments.json()["items"]
    )
    assert sum(
        len(item["preview"]) for item in max_fragments.json()["items"]
    ) <= 4800
    assert ("get-source", SOURCE_ID, PREVIEW_DEFAULT_CHARS) in service.calls


@pytest.mark.parametrize(
    "body",
    (
        {"idempotencyKey": "k" * 32, "relativePath": "safe/book.txt", "root": "C:/"},
        {"idempotencyKey": "k" * 32, "relativePath": "safe/book.txt", "parserVersion": "evil"},
        {"idempotencyKey": "k" * 32, "relativePath": "safe/book.txt", "previewChars": 99999},
    ),
)
def test_import_request_forbids_root_versions_and_client_limits(body):
    client, _ = make_client()
    assert client.post("/api/corpus/imports", json=body).status_code == 422


@pytest.mark.parametrize(
    "idempotency_key",
    (
        "A" * 32,
        "a" * 31 + " ",
        "密" * 16,
        "a" * 16 + ".unsafe",
    ),
)
def test_import_request_rejects_noncanonical_idempotency_keys(idempotency_key):
    client, _ = make_client()

    response = client.post("/api/corpus/imports", json={
        "idempotencyKey": idempotency_key,
        "relativePath": "safe/book.txt",
    })

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_service_rejects_noncanonical_key_before_database_access(tmp_path):
    (tmp_path / "book.txt").write_text(
        "第一章 风起\n原创正文。", encoding="utf-8"
    )

    def forbidden_boundary():
        raise AssertionError("database boundary must not be reached")

    service = CorpusImportService(
        object(),
        corpus_root=tmp_path,
        transaction_factory=forbidden_boundary,
        connection_factory=forbidden_boundary,
    )

    with pytest.raises(CorpusRequestInvalid):
        await service.import_source("book.txt", "A" * 32)


def test_succeeded_import_replay_returns_the_same_success_response():
    client, service = make_client()
    request = {"idempotencyKey": "s" * 32, "relativePath": "safe/book.txt"}

    first = client.post("/api/corpus/imports", json=request)
    replay = client.post("/api/corpus/imports", json=request)

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert service.calls == [
        ("import", "safe/book.txt", "s" * 32),
        ("import", "safe/book.txt", "s" * 32),
    ]


def test_failed_import_replay_never_degrades_to_200():
    client, service = make_client()
    service.failure = CorpusImportFailed()
    request = {"idempotencyKey": "f" * 32, "relativePath": "safe/book.txt"}

    first = client.post("/api/corpus/imports", json=request)
    replay = client.post("/api/corpus/imports", json=request)

    assert [first.status_code, replay.status_code] == [422, 422]
    assert [first.json()["code"], replay.json()["code"]] == [
        "CorpusImportFailed", "CorpusImportFailed"
    ]
    assert first.json()["message"] == replay.json()["message"]


def test_actual_service_failed_replay_has_same_safe_http_failure(tmp_path):
    class FailedRunRepository:
        def __init__(self):
            self.run = None

        async def lock_schema_guard(self, session):
            return None

        async def find_import_by_key(self, session, key, *, for_update=False):
            return self.run

        async def insert_import(self, session, row):
            self.run = dict(row)

        async def mark_import_failed(self, session, import_id, code, completed_at):
            assert self.run["id"] == import_id
            self.run.update({
                "status": "failed", "corpus_source_id": None,
                "public_error_code": code, "completed_at": completed_at,
            })

    @asynccontextmanager
    async def boundary():
        yield object()

    (tmp_path / "invalid.txt").write_bytes(b"\x00synthetic binary")
    repository = FailedRunRepository()
    service = CorpusImportService(
        repository, corpus_root=tmp_path,
        transaction_factory=boundary, connection_factory=boundary,
    )
    app = FastAPI()
    app.include_router(corpus.router, prefix="/api")
    app.dependency_overrides[corpus.get_corpus_service] = lambda: service
    install_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)
    request = {"idempotencyKey": "x" * 32, "relativePath": "invalid.txt"}

    first = client.post("/api/corpus/imports", json=request)
    replay = client.post("/api/corpus/imports", json=request)

    assert [first.status_code, replay.status_code] == [422, 422]
    assert [first.json()["code"], replay.json()["code"]] == [
        "CorpusImportFailed", "CorpusImportFailed"
    ]
    repository.run["status"] = "unknown-state"
    unknown = client.post("/api/corpus/imports", json=request)
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "CorpusImportFailed"


def test_main_registers_corpus_metadata_routes_without_full_book_or_download():
    client, _ = make_client()
    for path in (
        "/api/corpus/root", "/api/corpus/full-book", "/api/corpus/download",
        f"/api/corpus/sources/{SOURCE_ID}/download",
    ):
        assert client.get(path).status_code == 404
    from backend import main
    registered = {route.path for route in main.app.routes}
    assert "/api/corpus/discovery" in registered
    assert "/api/corpus/imports" in registered
    assert "/api/corpus/sources" in registered
    assert not {
        "/api/corpus/root",
        "/api/corpus/full-book",
        "/api/corpus/download",
        "/api/corpus/sources/{source_id}/download",
    } & registered


@pytest.mark.parametrize(
    ("failure", "status", "code", "path"),
    (
        (CorpusImportConflict(), 409, "CorpusImportConflict", "/api/corpus/imports"),
        (CorpusResourceNotFound(), 404, "CorpusResourceNotFound", f"/api/corpus/sources/{SOURCE_ID}"),
    ),
)
def test_corpus_public_errors_are_stable_and_safe(failure, status, code, path):
    client, service = make_client()
    service.failure = failure
    response = (
        client.post(path, json={
            "idempotencyKey": "k" * 32, "relativePath": "safe/book.txt",
        }) if path.endswith("imports") else client.get(path)
    )
    assert response.status_code == status
    assert response.json()["code"] == code
    _assert_safe(response.json())


def test_production_service_uses_explicit_transactions():
    service = corpus.get_corpus_service()
    assert service.transaction_factory is transaction
    assert service.connection_factory is transaction
