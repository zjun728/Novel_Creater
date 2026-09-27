from contextlib import asynccontextmanager

import pytest

from backend.repositories.continuity import ContinuityRepository
from backend.services.continuity import ContinuityReader, ContinuityReadError


@asynccontextmanager
async def connection():
    yield object()


class Repository:
    def __init__(self):
        self.calls = []

    async def head(self, session, project_id):
        return {"canon_revision_number": 3, "projection_revision_number": 3}

    async def entity(self, session, project_id, entity_id, revision):
        return {"id": entity_id, "canonical_name": "主角", "entity_type": "person"}

    async def records(self, session, project_id, revision, **filters):
        self.calls.append((project_id, revision, filters))
        return [{"id": str(i), "entity_id": filters["entity_id"], "canonical_name": None,
                 "field_path": "arc.trust", "payload_json": '"相信"', "source_event_id": str(i),
                 "source_chapter": 3, "fact_kind": "claim"} for i in range(3)]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [{"entity_id": "hero"}, {"global_only": True}])
async def test_history_is_scoped_versioned_paginated_and_preserves_claim(scope):
    repo = Repository()
    result = await ContinuityReader(repo, connection).records(
        "p", kind="facts", field_path="arc.trust", revision=3, offset=2, limit=2, **scope)
    assert result["nextOffset"] == 4
    assert len(result["items"]) == 2 and result["items"][0]["isClaim"] is True
    assert repo.calls == [("p", 3, {"kind": "facts", "entity_id": scope.get("entity_id"),
                                  "offset": 2, "limit": 3, "field_path": "arc.trust",
                                  **({"global_only": True} if scope.get("global_only") else {})})]


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", [
    {"field_path": "arc.trust"},
    {"field_path": "", "entity_id": "hero"},
    {"field_path": " " * 2, "entity_id": "hero"},
    {"field_path": "x" * 201, "entity_id": "hero"},
    {"global_only": True, "entity_id": "hero"},
    {"global_only": 1},
] + [{"kind": kind, "field_path": "arc.trust", "entity_id": "hero"}
     for kind in ["state", "memory", "arcs", "clues", "progress"]]
  + [{"kind": kind, "global_only": True}
     for kind in ["state", "memory", "arcs", "clues", "progress"]])
async def test_invalid_history_scope_rejected(filters):
    repo = Repository()
    with pytest.raises(ContinuityReadError, match="invalid_request"):
        await ContinuityReader(repo, connection).records("p", **{"kind": "facts", **filters})
    assert not repo.calls


@pytest.mark.asyncio
async def test_history_stale_revision_does_not_read_events():
    repo = Repository()
    with pytest.raises(ContinuityReadError, match="snapshot_changed"):
        await ContinuityReader(repo, connection).records("p", kind="facts", global_only=True,
                                                       field_path="plot.mystery", revision=2)
    assert not repo.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("global_only", [False, True])
async def test_sql_uses_binary_exact_parameterized_field_and_explicit_global_scope(global_only):
    field = "arc.Trust' OR 1=1 --"
    class Session:
        async def fetchall(self, sql, params):
            assert field not in sql
            assert "CAST(event.field_path AS BINARY)=CAST(%s AS BINARY)" in sql
            assert ("event.entity_id IS NULL" in sql) is global_only
            assert ("event.entity_id=%s" in sql) is (not global_only)
            assert "event.confirmation_status='confirmed'" in sql
            assert "event.fact_kind<>'claim'" not in sql
            assert "event.revision_number<=%s" in sql
            assert "ORDER BY event.revision_number DESC, event.event_order DESC" in sql
            assert params == (("p", 3, field, 11, 0) if global_only else ("p", 3, "hero", field, 11, 0))
            return []
    await ContinuityRepository().records(Session(), "p", 3, kind="facts", entity_id=None if global_only else "hero",
                                         offset=0, limit=11, field_path=field, global_only=global_only)
