import pytest

from backend.tests.support.canon_fakes import FakeCanonRepository
from backend.tests.unit.test_canon_revision import request, service


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    "insert_revision", "insert_entities", "insert_aliases", "insert_events",
    "replace_projections", "set_revision_content_hash", "advance_heads",
])
async def test_any_write_failure_rolls_back_all_staged_state(failure):
    repo = FakeCanonRepository()
    repo.state["revisions"].append({"id": "preexisting"})
    before = {name: len(rows) for name, rows in repo.state.items()}
    instance, transaction = service(repo)
    repo.fail_on = failure
    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        await instance.commit(request())
    assert {name: len(rows) for name, rows in repo.state.items()} == before
    assert transaction.rollback_count == 1
    assert transaction.commit_count == 0


@pytest.mark.asyncio
async def test_rollback_failure_preserves_body_and_rollback_errors():
    repo = FakeCanonRepository()
    repo.fail_on = "replace_projections"
    instance, transaction = service(repo)
    transaction.rollback_error = RuntimeError("rollback failed")
    with pytest.raises(BaseExceptionGroup) as caught:
        await instance.commit(request())
    assert [str(error) for error in caught.value.exceptions] == [
        "replace_projections failed", "rollback failed",
    ]
    assert transaction.commit_count == 0
