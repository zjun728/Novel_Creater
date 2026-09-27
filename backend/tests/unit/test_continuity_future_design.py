from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.routers import continuity
from backend.repositories.continuity import ContinuityRepository
from backend.security.redaction import install_error_handlers
from backend.services.continuity import ContinuityReader, ContinuityReadError


class Repository:
    def __init__(self, row):
        self.row = row
        self.sessions = []

    async def head(self, session, project_id):
        self.sessions.append(session)
        return {"canon_revision_number": 2, "projection_revision_number": 2}

    async def future_design(self, session, project_id):
        self.sessions.append(session)
        return self.row


@asynccontextmanager
async def connection():
    yield object()


def bible_row():
    return {"bible_id": "b1", "bible_revision": 1, "bible_hash": "b" * 64,
            "bible_content": '{"protagonist":"尚未发生的成长方向"}'}


@pytest.mark.asyncio
async def test_confirmed_future_is_separate_and_in_same_snapshot():
    repo = Repository({**bible_row(), "planning_id": "p1", "planning_revision": 3,
                       "planning_hash": "a" * 64, "planning_content": {"plots": []}})
    result = await ContinuityReader(repo, connection).future_design("project", revision=2)
    assert result == {"projectId": "project", "revision": 2, "association": "explicit", "entityId": None, "linkedPlots": [],
                      "bible": {"id": "b1", "revision": 1, "contentHash": "b" * 64,
                                "content": {"protagonist": "尚未发生的成长方向"}},
                      "planning": {"id": "p1", "revision": 3, "contentHash": "a" * 64,
                                   "content": {"plots": []}}}
    assert len(repo.sessions) == 2 and repo.sessions[0] is repo.sessions[1]


@pytest.mark.asyncio
async def test_person_plans_match_only_explicit_identity_not_name_or_retired_plot():
    plots = [
        {"id": "matched", "lifecycle": "active", "characterDesign": {"entityId": "hero", "displayName": "其他称谓"}},
        {"id": "same-name", "lifecycle": "active", "relatedCharacters": ["主角"], "characterDesign": {"entityId": "other", "displayName": "主角"}},
        {"id": "unbound", "lifecycle": "active", "characterDesign": {"entityId": None, "displayName": "主角"}},
        {"id": "retired", "lifecycle": "retired", "characterDesign": {"entityId": "hero"}},
    ]
    class EntityRepository(Repository):
        async def entity(self, session, project_id, entity_id, revision):
            return {"id": "hero", "canonical_name": "主角", "entity_type": "person"} if entity_id == "hero" else None
    repo = EntityRepository({**bible_row(), "planning_id": "p1", "planning_revision": 3,
                             "planning_hash": "a" * 64, "planning_content": {"plots": plots}})
    reader = ContinuityReader(repo, connection)
    result = await reader.future_design("project", revision=2, entity_id="hero")
    assert result["entityId"] == "hero"
    assert [plot["id"] for plot in result["linkedPlots"]] == ["matched"]
    assert result["planning"]["content"]["plots"] == plots
    with pytest.raises(ContinuityReadError, match="entity_missing"):
        await reader.future_design("project", revision=2, entity_id="foreign")


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [None, bible_row()])
async def test_missing_or_stale_design_is_not_replaced_with_a_draft(row):
    result = await ContinuityReader(Repository(row), connection).future_design("project")
    assert result["planning"] is None
    assert (result["bible"] is None) == (row is None)


@pytest.mark.asyncio
async def test_stale_snapshot_rejected_before_reading_design():
    repo = Repository(bible_row())
    with pytest.raises(ContinuityReadError, match="snapshot_changed"):
        await ContinuityReader(repo, connection).future_design("project", revision=1)
    assert len(repo.sessions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["not-json", "[]", "null"])
async def test_corrupt_design_is_not_presented_as_empty(content):
    with pytest.raises(ContinuityReadError, match="invalid_content"):
        await ContinuityReader(Repository({**bible_row(), "bible_content": content}), connection).future_design("project")


@pytest.mark.asyncio
async def test_repository_only_reads_confirmed_heads_and_full_basis():
    class Session:
        async def fetchone(self, sql, params):
            assert params == ("project",)
            assert "FOR UPDATE" not in sql and "draft" not in sql
            for term in ["planning.id=planning_head.planning_revision_id",
                         "planning.content_hash=planning_head.content_hash",
                         "planning.bible_revision_id=bible.id",
                         "planning.bible_hash=bible.content_hash",
                         "bible.seed_revision_id=selected.seed_revision_id",
                         "bible.style_hash=contracts.style_hash"]:
                assert term in sql
            return None
    assert await ContinuityRepository().future_design(Session(), "project") is None


def test_private_read_route_and_revision_validation(monkeypatch):
    monkeypatch.setattr(continuity, "reader", ContinuityReader(Repository(bible_row()), connection))
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(continuity.router, prefix="/api")
    with TestClient(app) as client:
        response = client.get("/api/projects/project/continuity/future-design?revision=2")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["bible"]["id"] == "b1"
        assert client.get("/api/projects/project/continuity/future-design?revision=1").status_code == 409
        assert client.get("/api/projects/project/continuity/future-design?revision=-1").status_code == 422
