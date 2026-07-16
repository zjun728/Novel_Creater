from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256

import aiomysql
import pytest

from backend.domain.json_contracts import canonical_json
from backend.http_errors import StoryEngineBatchConflict
from backend.repositories.story_engines import StoryEngineRepository
from backend.services.story_engines import (
    RESERVED_TIMEOUT_MS,
    RUNNING_LEASE_MS,
    CreateManualStoryEngineBatch,
    ReserveStoryEngineBatch,
    StoryEngineBatchResult,
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
           VALUES ('seed-revision-1',%s,'seed-1',1,%s,%s,%s)""",
        (
            project_id,
            canonical_json(
                {
                    "title": "Integration seed",
                    "genre": "history",
                    "logline": "A tested protagonist faces a lasting conflict",
                    "protagonist": "The tested protagonist",
                    "desire": "Protect the project",
                    "coreConflict": "Every success creates a cost",
                    "worldPressure": "The surrounding order keeps changing",
                    "openingHook": "The first invariant breaks",
                    "differentiation": "Choices alter later constraints",
                }
            ),
            "a" * 64,
            now,
        ),
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
           VALUES ('provider-seed','Seed Provider','openai','seed-model',
                   'https://test.invalid','test-only-key',1,0,0,10000,1000,
                   0.2,1.0,1,0,'test only',NULL,'active',NULL,%s,%s)""",
        (now, now),
    )
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES ('provider-planning','Planning Provider','openai','planning-model',
                   'https://planning.test.invalid','planning-test-only-key',1,1,0,
                   10000,1000,0.2,1.0,1,0,'test only',NULL,'active',NULL,%s,%s)""",
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
           VALUES ('binding-revision-1','seed','bound','provider-seed',
                   'Seed Provider','seed-model',%s)""",
        ("c" * 64,),
    )
    await session.execute(
        """INSERT INTO project_model_binding_items
           (binding_revision_id,task_key,resolution_status,provider_id,
            provider_name_snapshot,model_name_snapshot,item_hash)
           VALUES ('binding-revision-1','planning','bound','provider-planning',
                   'Planning Provider','planning-model',%s)""",
        ("d" * 64,),
    )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,'binding-revision-1',%s,%s)""",
        (project_id, "b" * 64, now),
    )


def _service(
    database,
    *,
    repository=None,
    clock=None,
    gateway=None,
    transaction_factory=None,
):
    default_transaction_factory = transaction_factory_for(
        database.connection_config
    )
    return StoryEngineService(
        repository or StoryEngineRepository(),
        transaction_factory=transaction_factory or default_transaction_factory,
        connection_factory=default_transaction_factory,
        clock=clock,
        provider_gateway=gateway,
    )


def _two_connection_barrier_transaction_factory(database):
    base_factory = transaction_factory_for(database.connection_config)
    barrier = asyncio.Barrier(2)
    connections = []

    @asynccontextmanager
    async def transaction_factory():
        async with base_factory() as session:
            connections.append(session.raw)
            await asyncio.wait_for(barrier.wait(), timeout=10)
            yield session

    return transaction_factory, connections


async def _insert_recovery_batch(
    session,
    *,
    batch_id: str,
    project_id: str = "project-1",
    source_type: str = "provider",
    seed_id: str = "seed-1",
    seed_revision_id: str = "seed-revision-1",
    seed_hash: str = "a" * 64,
    binding_revision_id: str | None = "binding-revision-1",
    binding_hash: str | None = "b" * 64,
    status: str = "reserved",
    created_at: int = 100,
):
    attempt_id = None
    attempt_started_at = None
    lease_expires_at = None
    raw_response_hash = None
    public_error_code = None
    finished_at = None
    if status in {"running", "succeeded", "outcome_unknown"}:
        attempt_id = f"attempt-{batch_id}"[-36:]
        attempt_started_at = created_at
        lease_expires_at = created_at + RUNNING_LEASE_MS
    if status == "succeeded":
        raw_response_hash = "9" * 64
        finished_at = created_at + 1
    if status == "outcome_unknown":
        public_error_code = "outcome_unknown"
        finished_at = created_at + 1
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   NULL,%s,%s,%s,%s)""",
        (
            batch_id,
            project_id,
            source_type,
            seed_id,
            seed_revision_id,
            seed_hash,
            binding_revision_id,
            binding_hash,
            "provider-seed" if source_type == "provider" else None,
            "seed-model" if source_type == "provider" else None,
            f"key-{batch_id}",
            canonical_json({"batch": batch_id}),
            "8" * 64,
            status,
            attempt_id,
            attempt_started_at,
            lease_expires_at,
            raw_response_hash,
            public_error_code,
            created_at,
            finished_at,
        ),
    )


async def _bootstrap_secondary_recovery_project(session) -> None:
    now = 1_700_000_000_000
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES ('project-2','Other','history','test only',100000,100,
                   'drafting',0,%s,%s)""",
        (now, now),
    )
    await session.execute(
        """INSERT INTO creative_seeds
           (id,project_id,status,created_at,updated_at)
           VALUES ('seed-2','project-2','candidate',%s,%s)""",
        (now, now),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES ('seed-revision-2','project-2','seed-2',1,%s,%s,%s)""",
        (canonical_json({"test": "other project"}), "2" * 64, now),
    )
    await session.execute(
        """INSERT INTO project_selected_seeds
           (project_id,seed_id,seed_revision_id,seed_hash,
            selection_revision,selected_at,updated_at)
           VALUES ('project-2','seed-2','seed-revision-2',%s,1,%s,%s)""",
        ("2" * 64, now, now),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES ('binding-revision-2','project-2',1,%s,NULL,%s)""",
        ("3" * 64, now),
    )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES ('project-2',1,'binding-revision-2',%s,%s)""",
        ("3" * 64, now),
    )


@pytest.mark.asyncio
async def test_recoverable_discovery_filters_current_facts_orders_and_limits(
    disposable_mysql,
):
    session = disposable_mysql.session
    await _bootstrap_facts(session)
    await _bootstrap_secondary_recovery_project(session)
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES ('seed-revision-stale','project-1','seed-1',2,%s,%s,2)""",
        (canonical_json({"test": "stale seed"}), "4" * 64),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES ('binding-revision-stale','project-1',2,%s,NULL,2)""",
        ("5" * 64,),
    )

    valid_rows = [
        ("batch-current-b", "reserved", 100),
        ("batch-current-a", "running", 100),
        ("batch-current-02", "outcome_unknown", 102),
        *((f"batch-current-{number:02d}", "reserved", 100 + number)
          for number in range(3, 12)),
    ]
    for batch_id, status, created_at in valid_rows:
        await _insert_recovery_batch(
            session, batch_id=batch_id, status=status, created_at=created_at
        )
    await _insert_recovery_batch(
        session,
        batch_id="batch-other-project",
        project_id="project-2",
        seed_id="seed-2",
        seed_revision_id="seed-revision-2",
        seed_hash="2" * 64,
        binding_revision_id="binding-revision-2",
        binding_hash="3" * 64,
        created_at=1,
    )
    await _insert_recovery_batch(
        session,
        batch_id="batch-stale-seed",
        seed_revision_id="seed-revision-stale",
        seed_hash="4" * 64,
        created_at=1,
    )
    await _insert_recovery_batch(
        session,
        batch_id="batch-stale-binding",
        binding_revision_id="binding-revision-stale",
        binding_hash="5" * 64,
        created_at=1,
    )
    await _insert_recovery_batch(
        session, batch_id="batch-succeeded", status="succeeded", created_at=1
    )
    await _service(disposable_mysql).create_manual(
        CreateManualStoryEngineBatch("project-1", "manual-filter", three_options())
    )

    results = await _service(disposable_mysql).list_recoverable("project-1")

    assert [(item.id, item.status) for item in results] == [
        ("batch-current-a", "running"),
        ("batch-current-b", "reserved"),
        ("batch-current-02", "outcome_unknown"),
        *((f"batch-current-{number:02d}", "reserved") for number in range(3, 10)),
    ]
    assert len(results) == 10

    now = 1_700_000_000_000
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES ('project-empty','Empty','history','test only',100000,100,
                   'drafting',0,%s,%s)""",
        (now, now),
    )
    assert await _service(disposable_mysql).list_recoverable("project-empty") == ()


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
    assert succeeded.raw_response_text is None
    assert succeeded.raw_response_hash == sha256(b"raw").hexdigest()
    async with transaction() as session:
        assert not await repository.cas_fail_attempt(
            session,
            "project-1",
            reserved.id,
            running.attempt_id,
            {"public_error_code": "provider_failed", "finished_at": 4},
        )


@pytest.mark.asyncio
async def test_provider_batch_freezes_only_seed_binding_and_hashes_seed_changes(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)
    service = _service(disposable_mysql)
    first = await service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "seed-binding")
    )
    assert first.provider_id == "provider-seed"
    assert first.model_name_snapshot == "seed-model"
    original_hash = first.request_hash

    await disposable_mysql.session.execute(
        """UPDATE project_model_binding_items
           SET provider_id='provider-seed',provider_name_snapshot='Seed Provider',
               model_name_snapshot='seed-model',item_hash=%s
           WHERE binding_revision_id='binding-revision-1' AND task_key='planning'""",
        ("e" * 64,),
    )
    replay = await service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "seed-binding")
    )
    assert replay.request_hash == original_hash

    await disposable_mysql.session.execute(
        """UPDATE project_model_binding_items
           SET provider_id='provider-planning',
               provider_name_snapshot='Planning Provider',
               model_name_snapshot='planning-model',item_hash=%s
           WHERE binding_revision_id='binding-revision-1' AND task_key='planning'""",
        ("d" * 64,),
    )
    await disposable_mysql.session.execute(
        """UPDATE project_model_binding_items
           SET provider_id='provider-planning',
               provider_name_snapshot='Planning Provider',
               model_name_snapshot='planning-model',item_hash=%s
           WHERE binding_revision_id='binding-revision-1' AND task_key='seed'""",
        ("f" * 64,),
    )
    changed = await service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "changed-seed")
    )
    assert changed.request_hash != original_hash
    with pytest.raises(StoryEngineBatchConflict):
        await service.reserve_provider(
            ReserveStoryEngineBatch("project-1", "seed-binding")
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
    assert failed.attempt_id is None
    assert failed.attempt_started_at is None
    assert failed.lease_expires_at is None

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


@pytest.mark.asyncio
async def test_real_two_connection_stale_reserved_start_races_reconcile(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)
    clock = FakeClock(1_800_000_000_000)
    setup_service = _service(disposable_mysql, clock=clock)
    reserved = await setup_service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "stale-race")
    )
    clock.advance(RESERVED_TIMEOUT_MS)
    race_factory, connections = _two_connection_barrier_transaction_factory(
        disposable_mysql
    )
    start_service = _service(
        disposable_mysql, clock=clock, transaction_factory=race_factory
    )
    reconcile_service = _service(
        disposable_mysql, clock=clock, transaction_factory=race_factory
    )

    start_result, reconcile_result = await asyncio.wait_for(
        asyncio.gather(
            start_service.start_attempt("project-1", reserved.id),
            reconcile_service.reconcile("project-1", reserved.id),
            return_exceptions=True,
        ),
        timeout=15,
    )

    assert len(connections) == 2
    assert connections[0] is not connections[1]
    assert isinstance(
        start_result, (StoryEngineBatchResult, StoryEngineBatchConflict)
    )
    assert isinstance(reconcile_result, StoryEngineBatchResult)
    row = await disposable_mysql.session.fetchone(
        """SELECT status,attempt_id,attempt_started_at,lease_expires_at,
                  raw_response_text,raw_response_hash,public_error_code,finished_at
           FROM story_engine_batches WHERE project_id='project-1' AND id=%s""",
        (reserved.id,),
    )
    option_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM story_engine_options WHERE batch_id=%s",
        (reserved.id,),
    )
    assert option_count == {"count": 0}
    if row["status"] == "failed":
        assert isinstance(start_result, StoryEngineBatchConflict)
        assert reconcile_result.status == "failed"
        assert row == {
            "status": "failed",
            "attempt_id": None,
            "attempt_started_at": None,
            "lease_expires_at": None,
            "raw_response_text": None,
            "raw_response_hash": None,
            "public_error_code": "not_started",
            "finished_at": clock.now,
        }
    else:
        assert row["status"] == "running"
        assert isinstance(start_result, StoryEngineBatchResult)
        assert start_result.status == reconcile_result.status == "running"
        assert row["attempt_id"] is not None
        assert row["attempt_started_at"] == clock.now
        assert row["lease_expires_at"] == clock.now + RUNNING_LEASE_MS
        assert row["raw_response_text"] is None
        assert row["raw_response_hash"] is None
        assert row["public_error_code"] is None
        assert row["finished_at"] is None


@pytest.mark.asyncio
async def test_real_two_connection_expired_running_success_races_reconcile(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)
    clock = FakeClock(1_800_000_000_000)
    setup_service = _service(disposable_mysql, clock=clock)
    reserved = await setup_service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "running-race")
    )
    running = await setup_service.start_attempt("project-1", reserved.id)
    clock.advance(RUNNING_LEASE_MS)
    race_factory, connections = _two_connection_barrier_transaction_factory(
        disposable_mysql
    )
    success_service = _service(
        disposable_mysql, clock=clock, transaction_factory=race_factory
    )
    reconcile_service = _service(
        disposable_mysql, clock=clock, transaction_factory=race_factory
    )

    success_result, reconcile_result = await asyncio.wait_for(
        asyncio.gather(
            success_service.succeed_attempt(
                "project-1", running.id, running.attempt_id, "raw", three_options()
            ),
            reconcile_service.reconcile("project-1", running.id),
            return_exceptions=True,
        ),
        timeout=15,
    )

    assert len(connections) == 2
    assert connections[0] is not connections[1]
    assert isinstance(
        success_result, (StoryEngineBatchResult, StoryEngineBatchConflict)
    )
    assert isinstance(reconcile_result, StoryEngineBatchResult)
    row = await disposable_mysql.session.fetchone(
        """SELECT status,attempt_id,attempt_started_at,lease_expires_at,
                  raw_response_text,raw_response_hash,public_error_code,finished_at
           FROM story_engine_batches WHERE project_id='project-1' AND id=%s""",
        (running.id,),
    )
    option_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM story_engine_options WHERE batch_id=%s",
        (running.id,),
    )
    assert row["attempt_id"] == running.attempt_id
    assert row["attempt_started_at"] is not None
    assert row["lease_expires_at"] is not None
    assert row["finished_at"] == clock.now
    if row["status"] == "outcome_unknown":
        assert isinstance(success_result, StoryEngineBatchConflict)
        assert reconcile_result.status == "outcome_unknown"
        assert row["public_error_code"] == "outcome_unknown"
        assert row["raw_response_text"] is None
        assert row["raw_response_hash"] is None
        assert option_count == {"count": 0}
    else:
        assert row["status"] == "succeeded"
        assert isinstance(success_result, StoryEngineBatchResult)
        assert success_result.status == reconcile_result.status == "succeeded"
        assert row["public_error_code"] is None
        assert row["raw_response_text"] is None
        assert row["raw_response_hash"] == sha256(b"raw").hexdigest()
        assert option_count == {"count": 3}


@pytest.mark.asyncio
async def test_real_invalid_response_failure_persists_hash_without_plaintext(
    disposable_mysql,
):
    await _bootstrap_facts(disposable_mysql.session)
    service = _service(disposable_mysql)
    reserved = await service.reserve_provider(
        ReserveStoryEngineBatch("project-1", "invalid-response-hash")
    )
    running = await service.start_attempt("project-1", reserved.id)
    raw = "not-json secret-shaped-but-not-stored"

    failed = await service.fail_attempt(
        "project-1",
        reserved.id,
        running.attempt_id,
        "invalid_response",
        raw_response_hash=sha256(raw.encode("utf-8")).hexdigest(),
    )

    row = await disposable_mysql.session.fetchone(
        """SELECT status,raw_response_text,raw_response_hash,public_error_code
           FROM story_engine_batches WHERE id=%s""",
        (reserved.id,),
    )
    assert failed.raw_response_text is None
    assert failed.raw_response_hash == sha256(raw.encode("utf-8")).hexdigest()
    assert row == {
        "status": "failed",
        "raw_response_text": None,
        "raw_response_hash": failed.raw_response_hash,
        "public_error_code": "invalid_response",
    }
