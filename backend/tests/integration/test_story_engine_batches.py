from __future__ import annotations

import asyncio

import aiomysql
import pytest

from backend.repositories.story_engines import StoryEngineRepository
from backend.services.story_engines import (
    RESERVED_TIMEOUT_MS,
    RUNNING_LEASE_MS,
    CreateManualStoryEngineBatch,
    ReserveStoryEngineBatch,
    StoryEngineService,
)
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.support.story_engine_fakes import (
    CountingGateway,
    FakeClock,
    three_options,
)


pytestmark = pytest.mark.mysql


async def _bootstrap_facts(session, project_id: str = "project-1") -> None:
    now = 1_700_000_000_000
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'Test','history','test only',100000,100,'drafting',0,%s,%s)""",
        (project_id, now, now),
    )
    await session.execute(
        """INSERT INTO creative_seeds
           (id,project_id,status,created_at,updated_at)
           VALUES ('seed-1',%s,'candidate',%s,%s)""",
        (project_id, now, now),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES ('seed-revision-1',%s,'seed-1',1,'{}',%s,%s)""",
        (project_id, "a" * 64, now),
    )
    await session.execute(
        """INSERT INTO creative_seed_heads
           (seed_id,revision_id,revision,content_hash,updated_at)
           VALUES ('seed-1','seed-revision-1',1,%s,%s)""",
        ("a" * 64, now),
    )
    await session.execute(
        """INSERT INTO project_selected_seeds
           (project_id,seed_id,seed_revision_id,seed_hash,
            selection_revision,selected_at,updated_at)
           VALUES (%s,'seed-1','seed-revision-1',%s,1,%s,%s)""",
        (project_id, "a" * 64, now, now),
    )
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES ('provider-1','Test Provider','openai','safe-model',
                   'https://test.invalid','test-only-key',1,0,0,10000,1000,
                   0.2,1.0,1,0,'test only',NULL,'active',NULL,%s,%s)""",
        (now, now),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES ('binding-revision-1',%s,1,%s,NULL,%s)""",
        (project_id, "b" * 64, now),
    )
    await session.execute(
        """INSERT INTO project_model_binding_items
           (binding_revision_id,task_key,resolution_status,provider_id,
            provider_name_snapshot,model_name_snapshot,item_hash)
           VALUES ('binding-revision-1','planning','bound','provider-1',
                   'Test Provider','safe-model',%s)""",
        ("c" * 64,),
    )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,'binding-revision-1',%s,%s)""",
        (project_id, "b" * 64, now),
    )


def _service(database, *, repository=None, clock=None, gateway=None):
    return StoryEngineService(
        repository or StoryEngineRepository(),
        transaction_factory=transaction_factory_for(database.connection_config),
        connection_factory=transaction_factory_for(database.connection_config),
        clock=clock,
        provider_gateway=gateway,
    )


@pytest.mark.asyncio
async def test_m2a_schema_enforces_unique_key_fk_and_exact_three_manual_options(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)
    service = _service(disposable_mysql)
    result = await service.create_manual(
        CreateManualStoryEngineBatch("project-1", "unique-key", three_options())
    )
    assert result.status == "succeeded"
    assert len(result.options) == 3

    with pytest.raises(aiomysql.IntegrityError):
        await disposable_mysql.session.execute(
            """INSERT INTO story_engine_batches
               (id,project_id,source_type,seed_id,seed_revision_id,seed_hash,
                binding_revision_id,binding_hash,provider_id,model_name_snapshot,
                idempotency_key,request_json,request_hash,status,attempt_id,
                attempt_started_at,lease_expires_at,raw_response_text,
                raw_response_hash,public_error_code,created_at,finished_at)
               SELECT 'duplicate-batch',project_id,source_type,seed_id,
                      seed_revision_id,seed_hash,binding_revision_id,binding_hash,
                      provider_id,model_name_snapshot,idempotency_key,request_json,
                      request_hash,status,attempt_id,attempt_started_at,
                      lease_expires_at,raw_response_text,raw_response_hash,
                      public_error_code,created_at,finished_at
               FROM story_engine_batches WHERE id=%s""",
            (result.id,),
        )
    with pytest.raises(aiomysql.IntegrityError):
        await disposable_mysql.session.execute(
            """INSERT INTO story_engine_options
               (id,project_id,batch_id,option_order,payload_json,content_hash,created_at)
               VALUES ('bad-fk','wrong-project',%s,1,'{}',%s,1)""",
            (result.id, "d" * 64),
        )


@pytest.mark.asyncio
async def test_manual_batch_and_options_roll_back_together_on_partial_insert(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)

    class FailingRepository(StoryEngineRepository):
        async def insert_options(self, session, rows):
            await super().insert_options(session, rows[:1])
            raise RuntimeError("synthetic partial insert")

    service = _service(disposable_mysql, repository=FailingRepository())
    with pytest.raises(RuntimeError, match="synthetic partial insert"):
        await service.create_manual(
            CreateManualStoryEngineBatch("project-1", "rollback-key", three_options())
        )
    batch_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM story_engine_batches"
    )
    option_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM story_engine_options"
    )
    assert batch_count["count"] == 0
    assert option_count["count"] == 0


@pytest.mark.asyncio
async def test_concurrent_same_idempotency_key_commits_one_atomic_batch(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)
    first_service = _service(disposable_mysql)
    second_service = _service(disposable_mysql)
    first, second = await asyncio.gather(
        first_service.create_manual(
            CreateManualStoryEngineBatch("project-1", "concurrent", three_options())
        ),
        second_service.create_manual(
            CreateManualStoryEngineBatch("project-1", "concurrent", three_options())
        ),
    )
    assert first.id == second.id
    counts = await disposable_mysql.session.fetchone(
        """SELECT
             (SELECT COUNT(*) FROM story_engine_batches) AS batches,
             (SELECT COUNT(*) FROM story_engine_options) AS options_count"""
    )
    assert counts == {"batches": 1, "options_count": 3}


@pytest.mark.asyncio
async def test_real_transition_cas_and_terminal_rows_are_immutable(disposable_mysql):
    await _bootstrap_facts(disposable_mysql.session)
    repository = StoryEngineRepository()
    service = _service(disposable_mysql, repository=repository)
    reserved = await service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "transition")
    )
    running = await service.start_attempt("project-1", reserved.id)
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction() as session:
        assert not await repository.cas_start_attempt(
            session,
            "project-1",
            reserved.id,
            {
                "attempt_id": "losing-attempt",
                "attempt_started_at": 2,
                "lease_expires_at": 3,
            },
        )
    succeeded = await service.succeed_attempt(
        "project-1", reserved.id, running.attempt_id, "raw", three_options()
    )
    assert succeeded.status == "succeeded"
    async with transaction() as session:
        assert not await repository.cas_fail_attempt(
            session,
            "project-1",
            reserved.id,
            running.attempt_id,
            {"public_error_code": "provider_failed", "finished_at": 4},
        )


@pytest.mark.asyncio
async def test_real_reconcile_uses_cas_for_stale_reserved_and_expired_running(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)
    clock = FakeClock(1_800_000_000_000)
    gateway = CountingGateway()
    service = _service(disposable_mysql, clock=clock, gateway=gateway)
    stale = await service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "stale")
    )
    clock.advance(RESERVED_TIMEOUT_MS)
    failed = await service.reconcile("project-1", stale.id)
    assert (failed.status, failed.public_error_code) == ("failed", "not_started")

    live = await service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "running")
    )
    running = await service.start_attempt("project-1", live.id)
    clock.advance(RUNNING_LEASE_MS)
    unknown = await service.reconcile("project-1", running.id)
    assert (unknown.status, unknown.public_error_code) == (
        "outcome_unknown", "outcome_unknown"
    )
    assert gateway.calls == 0
