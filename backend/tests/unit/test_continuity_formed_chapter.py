from contextlib import asynccontextmanager

import pytest

from backend.repositories.continuity import ContinuityRepository
from backend.services.continuity import ContinuityReader


@asynccontextmanager
async def connection():
    yield object()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["state", "arcs", "clues", "progress", "facts", "memory"])
async def test_record_keeps_distinct_formation_and_latest_source(kind):
    class Repository:
        async def head(self, session, project_id):
            return {"canon_revision_number": 8, "projection_revision_number": 8}

        async def records(self, session, project_id, revision, **kwargs):
            return [{"id": "record", "entity_id": "entity", "canonical_name": "主角",
                     "field_path": "arc.trust", "payload_json": '"坚定"',
                     "source_event_id": "latest", "source_chapter": 7,
                     "formed_chapter": 7 if kind in {"facts", "memory"} else 3,
                     "fact_kind": "dynamic_event"}]

    result = await ContinuityReader(Repository(), connection).records("project", kind=kind)
    assert result["items"][0]["sourceChapter"] == 7
    assert result["items"][0]["formedChapter"] == (7 if kind in {"facts", "memory"} else 3)
    assert result["items"][0]["sourceEventId"] == "latest"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,field", [("state", "field_path"), ("arcs", "arc_key"),
                                       ("clues", "field_path"), ("progress", "field_path")])
async def test_formation_query_uses_first_confirmed_non_claim_event_not_chapter_min(kind, field):
    class Session:
        async def fetchall(self, sql, params):
            formed_sql = sql.split("LEFT JOIN canon_events formed ON formed.id=(", 1)[1].split(")\n", 1)[0]
            assert "event.project_id=projection.project_id" in formed_sql
            assert "event.entity_id <=> projection.entity_id" in formed_sql
            assert f"CAST(event.field_path AS BINARY)=CAST(projection.{field} AS BINARY)" in formed_sql
            assert sql.count(f"CAST(event.field_path AS BINARY)=CAST(projection.{field} AS BINARY)") == 2
            assert "event.revision_number<=projection.revision_number" in formed_sql
            assert "event.confirmation_status='confirmed'" in formed_sql
            assert "event.fact_kind<>'claim'" in formed_sql
            assert "ORDER BY event.revision_number ASC, event.event_order ASC LIMIT 1" in formed_sql
            assert "MIN(" not in sql
            assert "formed_final.canon_revision=formed.revision_number" in sql
            assert "formed_final.project_id=formed.project_id" in sql
            assert "ORDER BY event.revision_number DESC, event.event_order DESC LIMIT 1" in sql
            return []

    assert await ContinuityRepository().records(Session(), "project", 8, kind=kind,
                                                entity_id=None, offset=0, limit=10) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["facts", "memory"])
async def test_event_history_formation_is_its_own_source(kind):
    class Session:
        async def fetchall(self, sql, params):
            assert "final.chapter_num AS source_chapter" in sql
            assert "final.chapter_num AS formed_chapter" in sql
            assert "LEFT JOIN canon_events formed" not in sql
            return []

    assert await ContinuityRepository().records(Session(), "project", 8, kind=kind,
                                                entity_id=None, offset=0, limit=10) == []
