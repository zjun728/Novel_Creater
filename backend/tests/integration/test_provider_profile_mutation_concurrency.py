from __future__ import annotations

import asyncio

import pytest

from backend.services.provider_profiles import (
    ProviderProfileConflict,
    ProviderProfileService,
    ProviderUpdateCommand,
    SqlProviderProfileRepository,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql

PROVIDER_REPLAY = "71000000-0000-0000-0000-000000000001"
PROVIDER_CONFLICT = "71000000-0000-0000-0000-000000000002"


async def _insert_provider(session, provider_id: str, name: str) -> None:
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,
            sort_order,stream,max_context_tokens,max_output_tokens,
            temperature,top_p,supports_json,supports_streaming,notes,
            thinking,lifecycle_status,revision,deleted_at,created_at,
            updated_at)
           VALUES
           (%s,%s,'openai-compatible','model-one',
            'https://provider.example/v1','integration-key',1,
            0,1,200000,4096,0.800,0.900,1,1,'',NULL,
            'active',4,NULL,100,100)""",
        (provider_id, name),
    )


def _service(disposable_mysql) -> ProviderProfileService:
    return ProviderProfileService(
        SqlProviderProfileRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=None,
        connection_gateway=None,
    )


@pytest.mark.asyncio
async def test_real_provider_mutation_lock_order_serializes_replay_and_conflict(
    disposable_mysql,
):
    await _insert_provider(
        disposable_mysql.session, PROVIDER_REPLAY, "Concurrent Replay"
    )
    await _insert_provider(
        disposable_mysql.session, PROVIDER_CONFLICT, "Concurrent Conflict"
    )
    service = _service(disposable_mysql)

    replay_command = ProviderUpdateCommand(
        provider_id=PROVIDER_REPLAY,
        expected_revision=4,
        idempotency_key="provider-replay-concurrent-0001",
        changes={"model": "model-replayed"},
    )
    replay_outcomes = await asyncio.wait_for(
        asyncio.gather(
            service.update(replay_command),
            service.update(replay_command),
            return_exceptions=True,
        ),
        timeout=10,
    )

    assert all(not isinstance(item, BaseException) for item in replay_outcomes)
    assert [item.revision for item in replay_outcomes] == [5, 5]
    replay_row = await disposable_mysql.session.fetchone(
        "SELECT revision,model_name FROM provider_profiles WHERE id=%s",
        (PROVIDER_REPLAY,),
    )
    replay_requests = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS total
           FROM provider_profile_mutation_requests WHERE provider_id=%s""",
        (PROVIDER_REPLAY,),
    )
    assert replay_row == {"revision": 5, "model_name": "model-replayed"}
    assert replay_requests["total"] == 1

    conflict_commands = (
        ProviderUpdateCommand(
            provider_id=PROVIDER_CONFLICT,
            expected_revision=4,
            idempotency_key="provider-conflict-concurrent-a",
            changes={"model": "model-winner-a"},
        ),
        ProviderUpdateCommand(
            provider_id=PROVIDER_CONFLICT,
            expected_revision=4,
            idempotency_key="provider-conflict-concurrent-b",
            changes={"model": "model-winner-b"},
        ),
    )
    conflict_outcomes = await asyncio.wait_for(
        asyncio.gather(
            *(service.update(command) for command in conflict_commands),
            return_exceptions=True,
        ),
        timeout=10,
    )

    assert sum(
        getattr(item, "revision", None) == 5 for item in conflict_outcomes
    ) == 1
    assert sum(
        isinstance(item, ProviderProfileConflict)
        for item in conflict_outcomes
    ) == 1
    conflict_row = await disposable_mysql.session.fetchone(
        "SELECT revision,model_name FROM provider_profiles WHERE id=%s",
        (PROVIDER_CONFLICT,),
    )
    conflict_requests = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS total
           FROM provider_profile_mutation_requests WHERE provider_id=%s""",
        (PROVIDER_CONFLICT,),
    )
    assert conflict_row["revision"] == 5
    assert conflict_row["model_name"] in {
        "model-winner-a",
        "model-winner-b",
    }
    assert conflict_requests["total"] == 1
