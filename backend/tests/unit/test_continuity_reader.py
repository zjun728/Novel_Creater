from contextlib import asynccontextmanager
import hashlib

import pytest

from backend.services.continuity import ContinuityReader, ContinuityReadError, evidence_excerpt


class Repository:
    def __init__(self):
        self.head_value = {"canon_revision_number": 3, "projection_revision_number": 3}
        self.rows = []
        self.calls = []

    async def head(self, session, project_id):
        return self.head_value

    async def entities(self, session, project_id, revision, **filters):
        self.calls.append((project_id, revision, filters))
        return self.rows


@asynccontextmanager
async def connection():
    yield object()


@pytest.mark.asyncio
async def test_page_uses_one_synced_revision_and_returns_bounded_continuation():
    repo = Repository()
    repo.rows = [{"id": str(i), "canonical_name": "人物", "entity_type": "person"} for i in range(3)]
    page = await ContinuityReader(repo, connection).entities("p", limit=2)
    assert len(page["items"]) == 2
    assert page["nextOffset"] == 2
    assert page["revision"] == 3
    assert repo.calls == [("p", 3, {"offset": 0, "limit": 3, "query": "", "entity_type": None})]


@pytest.mark.asyncio
async def test_out_of_sync_and_stale_page_do_not_read_rows():
    repo = Repository()
    reader = ContinuityReader(repo, connection)
    with pytest.raises(ContinuityReadError, match="snapshot_changed"):
        await reader.entities("p", revision=2)
    repo.head_value["projection_revision_number"] = 2
    with pytest.raises(ContinuityReadError, match="projection_out_of_sync"):
        await reader.entities("p")
    assert repo.calls == []


@pytest.mark.asyncio
async def test_missing_project_does_not_look_like_empty_book():
    repo = Repository()
    repo.head_value = None
    with pytest.raises(ContinuityReadError, match="project_missing"):
        await ContinuityReader(repo, connection).entities("missing")


def test_evidence_requires_exact_unicode_range_and_hash():
    prose = "甲😀乙\n丙"
    evidence = {"startScalar": 1, "endScalar": 3, "excerptHash": hashlib.sha256("😀乙".encode()).hexdigest()}
    assert evidence_excerpt(prose, evidence) == "😀乙"
    assert evidence_excerpt(prose, {**evidence, "endScalar": 4}) is None
    assert evidence_excerpt(prose, {**evidence, "startScalar": True}) is None
    assert evidence_excerpt(prose, {**evidence, "endScalar": 999}) is None
