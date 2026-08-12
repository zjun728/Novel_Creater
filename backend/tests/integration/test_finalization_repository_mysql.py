from __future__ import annotations

import pytest

from backend.repositories.finalization import FinalizationRepository
from backend.tests.support.disposable_mysql import transaction_factory_for


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_finalization_preparation_queries_compile_on_disposable_schema(
    disposable_mysql,
):
    transaction_factory = transaction_factory_for(
        disposable_mysql.connection_config,
    )
    repository = FinalizationRepository()

    async with transaction_factory() as session:
        assert await repository.lock_session(
            session,
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        ) is None
        assert await repository.load_preparation_context(
            session,
            "00000000-0000-4000-8000-000000000001",
            1,
        ) is None
        assert await repository.lock_current_attempt(
            session,
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        ) is None
        assert await repository.lock_latest_attempt(
            session,
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        ) is None
        assert await repository.lock_commit_by_key(
            session,
            "00000000-0000-4000-8000-000000000001",
            "a" * 64,
        ) is None
        assert await repository.lock_commit_by_session(
            session,
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        ) is None
        assert await repository.list_finalized_outline_contents(
            session,
            "00000000-0000-4000-8000-000000000001",
        ) == ()
        assert await repository.lock_change_set_revision(
            session,
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000003",
            1,
            "a" * 64,
        ) is None
        assert not await repository.advance_current_revision(
            session,
            project_id="00000000-0000-4000-8000-000000000001",
            session_id="00000000-0000-4000-8000-000000000002",
            change_set_id="00000000-0000-4000-8000-000000000003",
            expected_revision=1,
            expected_revision_hash="a" * 64,
            next_revision=2,
            next_revision_hash="b" * 64,
            updated_at=1,
        )
        assert not await repository.confirm_current_revision(
            session,
            project_id="00000000-0000-4000-8000-000000000001",
            session_id="00000000-0000-4000-8000-000000000002",
            change_set_id="00000000-0000-4000-8000-000000000003",
            revision=1,
            revision_hash="a" * 64,
            confirmed_at=1,
        )
        assert await repository.read_current_view(
            session,
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        ) is None
        assert not await repository.mark_terminal(
            session,
            project_id="00000000-0000-4000-8000-000000000001",
            session_id="00000000-0000-4000-8000-000000000002",
            change_set_id="00000000-0000-4000-8000-000000000003",
            status="failed",
            report_id=None,
            updated_at=1,
        )
        assert not await repository.mark_committing(
            session,
            project_id="00000000-0000-4000-8000-000000000001",
            session_id="00000000-0000-4000-8000-000000000002",
            change_set_id="00000000-0000-4000-8000-000000000003",
            updated_at=1,
        )
        assert not await repository.finalize_session(
            session,
            project_id="00000000-0000-4000-8000-000000000001",
            session_id="00000000-0000-4000-8000-000000000002",
            finalized_at=1,
        )
        assert not await repository.mark_committed(
            session,
            project_id="00000000-0000-4000-8000-000000000001",
            session_id="00000000-0000-4000-8000-000000000002",
            change_set_id="00000000-0000-4000-8000-000000000003",
            updated_at=1,
        )
