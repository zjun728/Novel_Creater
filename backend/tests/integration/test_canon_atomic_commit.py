import json

import pytest

from backend.domain.canon import (
    AssertionOperator,
    CanonEventInput,
    ConfirmationStatus,
    FactKind,
    ValueCardinality,
)
from backend.repositories.canon import CanonRepository
from backend.services.canon import (
    AliasCreate,
    CanonEntityCreate,
    CanonEventCreate,
    CanonHeadMismatch,
    CanonService,
    CommitCanonRevision,
)
from backend.tests.support.disposable_mysql import (
    bootstrap_canon_project,
    transaction_factory_for,
)


PROJECT_ID = "11111111-1111-1111-1111-111111111111"
ENTITY_ID = "22222222-2222-2222-2222-222222222222"


def event(event_id, fact_kind, field_path, value):
    return CanonEventCreate(
        event_id,
        CanonEventInput(
            entity_id=ENTITY_ID,
            fact_kind=fact_kind,
            field_path=field_path,
            value=value,
            evidence={"source": "integration"},
            effective_start_chapter=1,
            effective_end_chapter=None,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            assertion_operator=AssertionOperator.EQUALS,
            value_cardinality=ValueCardinality.SINGLE,
        ),
    )


def commit_request(*, key="a" * 64, expected_head=0, events=None):
    return CommitCanonRevision(
        project_id=PROJECT_ID,
        expected_head=expected_head,
        idempotency_key=key,
        source_type="manual_test",
        source_id=None,
        entities=(CanonEntityCreate(ENTITY_ID, "person", "沈砚"),),
        aliases=(AliasCreate("33333333-3333-3333-3333-333333333333", ENTITY_ID, "沈先生"),),
        events=events or (
            event("44444444-4444-4444-4444-444444444444", FactKind.STABLE_DEFINITION, "state.life", "alive"),
            event("55555555-5555-5555-5555-555555555555", FactKind.DYNAMIC_EVENT, "arc.growth", "awakened"),
        ),
    )


async def table_counts(session):
    tables = (
        "canon_revisions", "canon_entities", "entity_aliases", "canon_events",
        "current_state_projections", "memory_views", "arc_projections",
        "plot_thread_projections",
    )
    return {
        table: (await session.fetchone(f"SELECT COUNT(*) AS count FROM {table}"))["count"]
        for table in tables
    }


@pytest.mark.mysql
async def test_real_commit_is_one_revision_and_advances_matching_projections(disposable_mysql):
    empty_hash = await bootstrap_canon_project(disposable_mysql.session, PROJECT_ID)
    repository = CanonRepository()
    service = CanonService(
        repository,
        transaction_factory=transaction_factory_for(disposable_mysql.connection_config),
        id_factory=lambda: "66666666-6666-6666-6666-666666666666",
        clock=lambda: 1_720_000_000_000,
    )

    result = await service.commit(commit_request())

    revisions = await disposable_mysql.session.fetchall(
        "SELECT id, revision_number, parent_revision_number, content_hash FROM canon_revisions ORDER BY revision_number"
    )
    events = await disposable_mysql.session.fetchall(
        "SELECT id, revision_number FROM canon_events ORDER BY event_order"
    )
    current = await disposable_mysql.session.fetchall(
        "SELECT field_path, payload_json FROM current_state_projections ORDER BY field_path"
    )
    memory = await disposable_mysql.session.fetchone(
        "SELECT payload_json FROM memory_views WHERE subject_key=%s", (ENTITY_ID,)
    )
    head = await disposable_mysql.session.fetchone(
        "SELECT canon_revision_number, projection_revision_number, content_hash FROM projection_heads WHERE project_id=%s",
        (PROJECT_ID,),
    )

    assert empty_hash == revisions[0]["content_hash"]
    assert [row["revision_number"] for row in revisions] == [0, 1]
    assert revisions[1]["id"] == result.revision_id
    assert revisions[1]["parent_revision_number"] == 0
    assert revisions[1]["content_hash"] == result.projection_hash
    assert {row["revision_number"] for row in events} == {1}
    assert len(events) == 2
    assert {row["field_path"]: json.loads(row["payload_json"]) for row in current} == {
        "arc.growth": "awakened",
        "state.life": "alive",
    }
    assert {item["eventId"] for item in json.loads(memory["payload_json"])} == {
        row["id"] for row in events
    }
    assert head == {
        "canon_revision_number": 1,
        "projection_revision_number": 1,
        "content_hash": result.projection_hash,
    }


@pytest.mark.mysql
async def test_real_head_mismatch_writes_nothing(disposable_mysql):
    await bootstrap_canon_project(disposable_mysql.session, PROJECT_ID)
    before = await table_counts(disposable_mysql.session)
    service = CanonService(
        CanonRepository(),
        transaction_factory=transaction_factory_for(disposable_mysql.connection_config),
    )

    with pytest.raises(CanonHeadMismatch):
        await service.commit(commit_request(expected_head=1))

    assert await table_counts(disposable_mysql.session) == before
