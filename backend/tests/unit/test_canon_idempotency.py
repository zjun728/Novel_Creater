import pytest

from backend.domain.canon import CanonValidationError
from backend.services.canon import CanonService
from backend.tests.support.canon_fakes import FakeCanonRepository, FakeCanonTransactionFactory
from backend.tests.unit.test_canon_revision import request, service


@pytest.mark.parametrize("key", ["k", "A" * 64, "g" * 64, "a" * 63, "a" * 65, 1])
def test_invalid_idempotency_key_is_rejected(key):
    with pytest.raises(CanonValidationError, match="idempotency_key"):
        request(idempotency_key=key)


@pytest.mark.asyncio
async def test_existing_idempotency_precedes_stale_head_and_writes_nothing():
    repo = FakeCanonRepository()
    repo.head = repo.projection_head = 4
    repo.idempotent[("project-1", "a" * 64)] = {
        "id": "revision-1", "revision_number": 1, "content_hash": "b" * 64,
    }
    instance, transaction = service(repo)
    result = await instance.commit(request(expected_head=0))
    assert (result.revision_id, result.revision_number) == ("revision-1", 1)
    assert result.projection_hash == "b" * 64
    assert result.idempotent is True
    assert repo.write_calls == []
    assert [call[0] for call in repo.calls] == ["lock_head", "find_idempotent"]
    assert transaction.commit_count == 1


@pytest.mark.asyncio
async def test_same_key_sequential_call_models_locked_race_and_writes_once():
    repo = FakeCanonRepository()
    transaction = FakeCanonTransactionFactory(repo)
    ids = iter(("revision-1", "must-not-be-used"))
    instance = CanonService(
        repo, transaction_factory=transaction,
        id_factory=lambda: next(ids), clock=lambda: 123,
    )
    first = await instance.commit(request())
    second = await instance.commit(request())
    assert first.idempotent is False
    assert second.idempotent is True
    assert second.revision_id == first.revision_id
    assert second.projection_hash == first.projection_hash
    assert repo.write_calls.count("insert_revision") == 1
    assert [call[0] for call in repo.calls].count("lock_head") == 2
    assert transaction.commit_count == 2
