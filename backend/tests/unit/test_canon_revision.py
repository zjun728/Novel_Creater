from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.domain.canon import (
    AssertionOperator, CanonEventInput, CanonValidationError,
    ConfirmationStatus, FactKind, ValueCardinality,
)
from backend.services.canon import (
    AliasCreate, CanonEntityCreate, CanonEventCreate, CanonHardConflictError,
    CanonHeadMismatch, CanonService, CommitCanonResult, CommitCanonRevision,
)
from backend.tests.support.canon_fakes import (
    FakeCanonRepository, FakeCanonTransactionFactory,
)


KEY = "a" * 64


def stable_event(entity_id="entity-1", value="alive", field_path="state.life"):
    return CanonEventInput(
        entity_id=entity_id,
        fact_kind=FactKind.STABLE_DEFINITION,
        field_path=field_path,
        value=value,
        evidence={"source": "test"},
        effective_start_chapter=1,
        effective_end_chapter=None,
        confirmation_status=ConfirmationStatus.CONFIRMED,
        assertion_operator=AssertionOperator.EQUALS,
        value_cardinality=ValueCardinality.SINGLE,
    )


def request(**changes):
    values = {
        "project_id": "project-1",
        "expected_head": 0,
        "idempotency_key": KEY,
        "source_type": "manual_test",
        "source_id": None,
        "entities": (CanonEntityCreate("entity-1", "person", "  Hero  "),),
        "aliases": (AliasCreate("alias-1", "entity-1", "  The Hero  "),),
        "events": (CanonEventCreate("event-1", stable_event()),),
    }
    values.update(changes)
    return CommitCanonRevision(**values)


def service(repo):
    transaction_factory = FakeCanonTransactionFactory(repo)
    ids = iter(("revision-1",))
    instance = CanonService(
        repo,
        transaction_factory=transaction_factory,
        id_factory=lambda: next(ids),
        clock=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
    )
    return instance, transaction_factory


@pytest.mark.parametrize("value", ["", " project-1", "project-1 ", 1])
def test_ids_must_be_non_empty_trimmed_strings(value):
    with pytest.raises(CanonValidationError, match="project_id"):
        request(project_id=value)


def test_commit_dtos_are_frozen_strict_and_reject_duplicate_ids():
    command = request()
    with pytest.raises(AttributeError):
        command.expected_head = 3
    with pytest.raises(CanonValidationError, match="entities must be a tuple"):
        request(entities=[])
    with pytest.raises(CanonValidationError, match="duplicate entity id"):
        request(entities=(command.entities[0], command.entities[0]))
    with pytest.raises(CanonValidationError, match="duplicate alias id"):
        request(aliases=(command.aliases[0], command.aliases[0]))
    with pytest.raises(CanonValidationError, match="duplicate event id"):
        request(events=(command.events[0], command.events[0]))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"revision_id": " revision-1"}, "revision_id"),
        ({"revision_number": -1}, "revision_number"),
        ({"projection_hash": "A" * 64}, "projection_hash"),
        ({"idempotent": 1}, "idempotent"),
    ],
)
def test_commit_result_is_frozen_and_strict(changes, message):
    values = {
        "revision_id": "revision-1",
        "revision_number": 1,
        "projection_hash": "a" * 64,
        "idempotent": False,
    }
    values.update(changes)
    with pytest.raises(CanonValidationError, match=message):
        CommitCanonResult(**values)


@pytest.mark.parametrize("source_type", ["bootstrap", "other", ""])
def test_ordinary_commit_rejects_non_runtime_source_types(source_type):
    with pytest.raises(CanonValidationError, match="source_type"):
        request(source_type=source_type)


@pytest.mark.asyncio
async def test_expected_head_mismatch_writes_nothing():
    repo = FakeCanonRepository()
    repo.head = repo.projection_head = 3
    instance, transaction = service(repo)
    with pytest.raises(CanonHeadMismatch) as caught:
        await instance.commit(request(expected_head=2))
    assert (caught.value.expected, caught.value.actual) == (2, 3)
    assert repo.write_calls == []
    assert transaction.rollback_count == 1
    assert transaction.commit_count == 0


@pytest.mark.asyncio
async def test_commit_locks_project_before_reading_canon_head():
    repo = FakeCanonRepository()
    instance, _ = service(repo)

    await instance.commit(request())

    assert [call[0] for call in repo.calls[:2]] == [
        "lock_project",
        "lock_head",
    ]


@pytest.mark.asyncio
async def test_revision_rows_share_new_revision_and_one_session():
    repo = FakeCanonRepository()
    instance, transaction = service(repo)
    result = await instance.commit(request())
    assert result.revision_id == "revision-1"
    assert result.revision_number == 1
    assert result.idempotent is False
    assert repo.state["revisions"][0]["revision_number"] == 1
    assert repo.state["revisions"][0]["parent_revision_number"] == 0
    assert repo.state["revisions"][0]["content_hash"] == result.projection_hash
    assert {row["created_revision"] for row in repo.state["entities"]} == {1}
    assert {row["created_revision"] for row in repo.state["aliases"]} == {1}
    assert [(row["revision_number"], row["event_order"]) for row in repo.state["events"]] == [(1, 1)]
    assert repo.state["entities"][0]["normalized_name"] == "hero"
    assert repo.state["aliases"][0]["normalized_alias"] == "the hero"
    assert {id(call[1]) for call in repo.calls} == {id(transaction.session)}
    assert repo.head == repo.projection_head == result.revision_number
    assert repo.head_hash == result.projection_hash
    assert transaction.commit_count == 1
    assert transaction.rollback_count == 0


@pytest.mark.asyncio
async def test_projection_bundle_uses_all_confirmed_events_and_hash_ordering():
    repo = FakeCanonRepository()
    repo.confirmed_events = [{
        "id": "old-event", "revision_number": 0, "event_order": 1,
        "entity_id": "entity-1", "fact_kind": "dynamic_event",
        "field_path": "arc.old", "value": "past",
        "confirmation_status": "confirmed", "evidence": {"source": "bootstrap"},
    }]
    instance, _ = service(repo)
    result = await instance.commit(request())
    bundle = repo.state["projections"][0]
    assert bundle.revision == 1
    assert bundle.arcs["entity-1"]["arc.old"] == "past"
    names = repo.write_calls
    assert names.index("replace_projections") < names.index("set_revision_content_hash") < names.index("advance_heads")
    assert repo.state["revisions"][0]["content_hash"] == bundle.content_hash == result.projection_hash


@pytest.mark.asyncio
async def test_missing_event_and_alias_entity_references_write_nothing():
    repo = FakeCanonRepository()
    instance, _ = service(repo)
    command = request(
        entities=(),
        aliases=(AliasCreate("alias-x", "missing", "Missing"),),
        events=(CanonEventCreate("event-x", stable_event("missing")),),
    )
    with pytest.raises(CanonValidationError, match="unknown entity_id"):
        await instance.commit(command)
    assert repo.write_calls == []


@pytest.mark.asyncio
async def test_existing_entity_reference_is_valid():
    repo = FakeCanonRepository()
    repo.existing_entity_ids.add("entity-1")
    instance, _ = service(repo)
    result = await instance.commit(request(entities=()))
    assert result.revision_number == 1


@pytest.mark.asyncio
async def test_exact_alias_ambiguity_does_not_auto_merge_or_choose_entity():
    repo = FakeCanonRepository()
    repo.existing_entity_ids.update(("entity-1", "entity-2"))
    repo.alias_matches["hero"] = {"entity-1", "entity-2"}
    instance, _ = service(repo)
    command = request(
        entities=(),
        aliases=(AliasCreate("alias-2", "entity-2", "Hero"),),
        events=(CanonEventCreate("event-2", stable_event("entity-2")),),
    )
    await instance.commit(command)
    assert repo.state["aliases"][0]["entity_id"] == "entity-2"
    alias_call = next(call for call in repo.calls if call[0] == "list_alias_matches")
    assert alias_call[2][-1] == "hero"


@pytest.mark.asyncio
async def test_existing_or_incoming_hard_conflict_writes_nothing():
    repo = FakeCanonRepository()
    repo.active_events.append(stable_event(value="dead"))
    instance, _ = service(repo)
    with pytest.raises(CanonHardConflictError) as caught:
        await instance.commit(request())
    assert caught.value.conflicts
    assert repo.write_calls == []

    repo = FakeCanonRepository()
    instance, _ = service(repo)
    incoming = (
        CanonEventCreate("event-1", stable_event(value="alive")),
        CanonEventCreate("event-2", stable_event(value="dead")),
    )
    with pytest.raises(CanonHardConflictError):
        await instance.commit(request(events=incoming))
    assert repo.write_calls == []
