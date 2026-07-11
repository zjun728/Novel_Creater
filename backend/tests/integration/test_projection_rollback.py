import pytest

from backend.repositories.canon import CanonRepository
from backend.services.canon import CanonService
from backend.tests.integration.test_canon_atomic_commit import PROJECT_ID, commit_request, table_counts
from backend.tests.support.disposable_mysql import bootstrap_canon_project, transaction_factory_for


class FaultInjectingCanonRepository(CanonRepository):
    def __init__(self, failure):
        super().__init__()
        self.failure = failure

    def _fail(self, point):
        if self.failure == point:
            raise RuntimeError(f"injected {point}")

    async def replace_projections(self, session, project_id, bundle):
        self._fail("before_replace_projections")
        await super().replace_projections(session, project_id, bundle)
        self._fail("after_replace_projections")

    async def advance_heads(self, session, project_id, revision, content_hash):
        self._fail("before_advance_heads")
        await super().advance_heads(session, project_id, revision, content_hash)
        self._fail("after_advance_heads")


@pytest.mark.mysql
@pytest.mark.parametrize("failure", (
    "before_replace_projections",
    "after_replace_projections",
    "before_advance_heads",
    "after_advance_heads",
))
async def test_real_failure_rolls_back_all_canon_and_projection_writes(disposable_mysql, failure):
    empty_hash = await bootstrap_canon_project(disposable_mysql.session, PROJECT_ID)
    before = await table_counts(disposable_mysql.session)
    service = CanonService(
        FaultInjectingCanonRepository(failure),
        transaction_factory=transaction_factory_for(disposable_mysql.connection_config),
    )

    with pytest.raises(RuntimeError, match=failure):
        await service.commit(commit_request())

    assert await table_counts(disposable_mysql.session) == before
    head = await disposable_mysql.session.fetchone(
        "SELECT canon_revision_number, projection_revision_number, content_hash FROM projection_heads WHERE project_id=%s",
        (PROJECT_ID,),
    )
    assert head == {
        "canon_revision_number": 0,
        "projection_revision_number": 0,
        "content_hash": empty_hash,
    }
