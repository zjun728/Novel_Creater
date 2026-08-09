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
        assert not await repository.mark_terminal(
            session,
            project_id="00000000-0000-4000-8000-000000000001",
            session_id="00000000-0000-4000-8000-000000000002",
            change_set_id="00000000-0000-4000-8000-000000000003",
            status="failed",
            report_id=None,
            updated_at=1,
        )
