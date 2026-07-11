import pytest

from backend.repositories.canon import CanonRepository
from backend.services.canon import CanonHardConflictError, CanonService, CommitCanonRevision
from backend.tests.integration.test_canon_atomic_commit import (
    ENTITY_ID,
    PROJECT_ID,
    commit_request,
    event,
    table_counts,
)
from backend.domain.canon import FactKind
from backend.tests.support.disposable_mysql import bootstrap_canon_project, transaction_factory_for


@pytest.mark.mysql
async def test_real_duplicate_commit_is_idempotent_without_any_new_rows(disposable_mysql):
    await bootstrap_canon_project(disposable_mysql.session, PROJECT_ID)
    service = CanonService(
        CanonRepository(),
        transaction_factory=transaction_factory_for(disposable_mysql.connection_config),
    )
    request = commit_request()

    first = await service.commit(request)
    before = await table_counts(disposable_mysql.session)
    second = await service.commit(request)

    assert await table_counts(disposable_mysql.session) == before
    assert second.revision_id == first.revision_id
    assert second.revision_number == first.revision_number
    assert second.projection_hash == first.projection_hash
    assert first.idempotent is False
    assert second.idempotent is True


@pytest.mark.mysql
async def test_real_overlapping_stable_value_conflict_writes_nothing(disposable_mysql):
    await bootstrap_canon_project(disposable_mysql.session, PROJECT_ID)
    service = CanonService(
        CanonRepository(),
        transaction_factory=transaction_factory_for(disposable_mysql.connection_config),
    )
    await service.commit(commit_request(events=(
        event("44444444-4444-4444-4444-444444444444", FactKind.STABLE_DEFINITION, "state.life", "alive"),
    )))
    before = await table_counts(disposable_mysql.session)
    conflicting = CommitCanonRevision(
        project_id=PROJECT_ID,
        expected_head=1,
        idempotency_key="b" * 64,
        source_type="manual_test",
        source_id=None,
        entities=(),
        aliases=(),
        events=(event("77777777-7777-7777-7777-777777777777", FactKind.STABLE_DEFINITION, "state.life", "dead"),),
    )

    with pytest.raises(CanonHardConflictError):
        await service.commit(conflicting)

    assert await table_counts(disposable_mysql.session) == before
    head = await disposable_mysql.session.fetchone(
        "SELECT canon_revision_number, projection_revision_number FROM projection_heads WHERE project_id=%s",
        (PROJECT_ID,),
    )
    assert head == {"canon_revision_number": 1, "projection_revision_number": 1}
