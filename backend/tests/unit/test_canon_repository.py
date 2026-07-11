from __future__ import annotations

import json

import pytest

from backend.repositories.canon import CanonDataCorruption, CanonRepository
from backend.services.projections import GLOBAL_PROJECTION_KEY, build_projection_bundle


class RecordingSession:
    def __init__(self, *, one=None, all_rows=()):
        self.one = one
        self.all_rows = all_rows
        self.calls = []

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return 1

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return self.one

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        return self.all_rows


@pytest.mark.asyncio
async def test_lock_head_uses_given_session_and_requires_equal_heads_and_hash():
    repo = CanonRepository()
    session = RecordingSession(one={
        "canon_revision_number": 2,
        "projection_revision_number": 2,
        "content_hash": "a" * 64,
    })
    assert await repo.lock_head(session, "project-1") == 2
    assert "FOR UPDATE" in session.calls[0][1]
    assert session.calls[0][2] == ("project-1",)
    with pytest.raises(CanonDataCorruption):
        await repo.lock_head(RecordingSession(one=None), "project-1")
    with pytest.raises(CanonDataCorruption):
        await repo.lock_head(RecordingSession(one={
            "canon_revision_number": 2,
            "projection_revision_number": 1,
            "content_hash": "a" * 64,
        }), "project-1")


@pytest.mark.asyncio
async def test_runtime_reads_use_only_supplied_session_and_schema_fields():
    repo = CanonRepository()
    session = RecordingSession(all_rows=[])
    await repo.find_idempotent(session, "project-1", "a" * 64)
    await repo.list_existing_entity_ids(session, "project-1", ("e1", "e2"))
    await repo.list_alias_matches(session, "project-1", "hero")
    await repo.list_active_stable_events(session, "project-1", (("e1", "life"),))
    await repo.list_confirmed_events(session, "project-1")
    sql = " ".join(call[1] for call in session.calls)
    assert all(table in sql for table in (
        "canon_revisions", "canon_entities", "entity_aliases", "canon_events",
    ))
    assert all(call[2][0] == "project-1" for call in session.calls)


@pytest.mark.asyncio
async def test_insert_methods_use_supplied_session_and_strict_json_rows():
    repo = CanonRepository()
    session = RecordingSession()
    await repo.insert_revision(session, {
        "id": "r1", "project_id": "project-1", "revision_number": 1,
        "parent_revision_number": 0, "idempotency_key": "a" * 64,
        "source_type": "manual_test", "source_id": None,
        "content_hash": "0" * 64, "created_at": 123,
    })
    await repo.insert_entities(session, ({
        "id": "e1", "project_id": "project-1", "entity_type": "person",
        "canonical_name": "Hero", "normalized_name": "hero",
        "created_revision": 1, "created_at": 123,
    },))
    await repo.insert_aliases(session, ({
        "id": "a1", "project_id": "project-1", "entity_id": "e1",
        "alias": "Hero", "normalized_alias": "hero",
        "created_revision": 1, "created_at": 123,
    },))
    await repo.insert_events(session, ({
        "id": "ev1", "project_id": "project-1", "revision_id": "r1",
        "revision_number": 1, "event_order": 1, "entity_id": "e1",
        "fact_kind": "dynamic_event", "field_path": "state.value",
        "value": {"z": [1, True], "a": "汉字"},
        "evidence": {"source": "test"},
        "effective_start_chapter": None, "effective_end_chapter": None,
        "assertion_operator": "equals", "value_cardinality": "single",
        "confirmation_status": "confirmed", "created_at": 123,
    },))
    assert len(session.calls) == 4
    assert all(call[0] == "execute" for call in session.calls)
    event_args = session.calls[-1][2]
    assert event_args[8] == '{"a":"汉字","z":[1,true]}'
    assert event_args[9] == '{"source":"test"}'


@pytest.mark.asyncio
async def test_projection_replacement_serializes_global_and_entity_subjects():
    ids = iter(f"row-{index}" for index in range(20))
    repo = CanonRepository(id_factory=lambda: next(ids), clock=lambda: 123)
    session = RecordingSession()
    bundle = build_projection_bundle(1, (
        {
            "id": "global-event", "revision_number": 1, "event_order": 1,
            "entity_id": None, "fact_kind": "dynamic_event",
            "field_path": "plot.global", "value": {"open": True},
            "confirmation_status": "confirmed", "evidence": {"source": "test"},
        },
        {
            "id": "entity-event", "revision_number": 1, "event_order": 2,
            "entity_id": "entity-1", "fact_kind": "dynamic_event",
            "field_path": "plot.personal", "value": ["thread"],
            "confirmation_status": "confirmed", "evidence": {"source": "test"},
        },
    ))
    await repo.replace_projections(session, "project-1", bundle)
    calls = [call for call in session.calls if call[0] == "execute"]
    assert [call[1].split()[0:3] for call in calls[:4]] == [
        ["DELETE", "FROM", table] for table in (
            "current_state_projections", "memory_views",
            "arc_projections", "plot_thread_projections",
        )
    ]
    memory_args = [call[2] for call in calls if "INSERT INTO memory_views" in call[1]]
    assert {args[3] for args in memory_args} == {GLOBAL_PROJECTION_KEY, "entity-1"}
    global_memory = next(args for args in memory_args if args[3] == GLOBAL_PROJECTION_KEY)
    assert global_memory[2] is None
    assert json.loads(global_memory[4])[0]["eventId"] == "global-event"
    plot_args = [call[2] for call in calls if "INSERT INTO plot_thread_projections" in call[1]]
    assert {(args[3], args[4]) for args in plot_args} == {
        (GLOBAL_PROJECTION_KEY, "plot.global"), ("entity-1", "plot.personal"),
    }
    assert next(args for args in plot_args if args[3] == GLOBAL_PROJECTION_KEY)[2] is None


@pytest.mark.asyncio
async def test_revision_hash_and_heads_are_updated_with_same_hash():
    repo = CanonRepository(clock=lambda: 2)
    session = RecordingSession()
    await repo.set_revision_content_hash(session, "revision-1", "b" * 64)
    await repo.advance_heads(session, "project-1", 2, "b" * 64)
    revision_call, head_call = session.calls
    assert "UPDATE canon_revisions SET content_hash=%s" in revision_call[1]
    assert revision_call[2] == ("b" * 64, "revision-1")
    assert "content_hash=%s" in head_call[1]
    assert head_call[2] == (2, 2, "b" * 64, 2, "project-1")
