from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.domain.model_bindings import TASK_KEYS
from backend.domain.application_settings import UpdateDefaultModel
from backend.http_errors import (
    ApplicationSettingsConflict,
    BindingConflict,
    ProjectArchived,
)
from backend.repositories.application_settings import (
    ApplicationSettingsRepository,
)
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.services.provider_profiles import (
    DeleteProviderCommand,
    ProviderProfileService,
    SqlProviderProfileRepository,
)
from backend.services.model_bindings import ModelBindingService
from backend.services.application_settings import ApplicationSettingsService
from backend.services.project_lifecycle import CreateProject, ProjectLifecycleService
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql


PROVIDER_A = "10000000-0000-0000-0000-000000000001"
PROVIDER_B = "10000000-0000-0000-0000-000000000002"


async def insert_provider(session, provider_id, name, model, sort_order):
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,
            sort_order,stream,max_context_tokens,max_output_tokens,temperature,
            top_p,supports_json,supports_streaming,notes,thinking,
            lifecycle_status,revision,deleted_at,created_at,updated_at)
           VALUES (%s,%s,'openai-compatible',%s,%s,%s,1,%s,1,200000,4096,
                   0.8,0.9,1,1,'',NULL,'active',1,NULL,%s,%s)""",
        (
            provider_id, name, model,
            f"https://{name.casefold()}.test/v1", f"test-key-{name}",
            sort_order, sort_order, sort_order,
        ),
    )


def project(project_id, title):
    return CreateProject(
        id=project_id,
        title=title,
        genre="integration",
        description="test only",
        target_words=1000,
        target_chapters=10,
    )


@pytest.mark.asyncio
async def test_revision_inheritance_cas_soft_delete_and_history_immutability(
    disposable_mysql
):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    repository = ModelBindingRepository(
        id_factory=(
            f"20000000-0000-0000-0000-{number:012d}" for number in range(1, 100)
        ).__next__,
        clock=iter(range(100, 1000)).__next__,
    )
    bindings = ModelBindingService(
        repository,
        transaction_factory=tx,
        connection_factory=read_connection,
    )
    projects_service = ProjectLifecycleService(
        ProjectRepository(
            id_factory=(
                f"30000000-0000-0000-0000-{number:012d}"
                for number in range(1, 100)
            ).__next__,
            clock=iter(range(1000, 2000)).__next__,
        ),
        tx,
        read_connection,
        model_binding_service=bindings,
    )
    await insert_provider(
        disposable_mysql.session,
        PROVIDER_A,
        "Alpha",
        "a-model test-key-Alpha",
        1,
    )
    await insert_provider(disposable_mysql.session, PROVIDER_B, "Beta", "b-model", 2)

    p1 = "40000000-0000-0000-0000-000000000001"
    await projects_service.create(project(p1, "one"))
    first = await bindings.get_current(p1)
    assert first.revision == 1
    assert len(first.items) == len(TASK_KEYS)
    assert all(item.provider_id == PROVIDER_A for item in first.items)
    assert all(item.model_name_snapshot == "a-model [REDACTED]" for item in first.items)
    assert first.binding_complete is True and first.binding_ready is True

    p2 = "40000000-0000-0000-0000-000000000002"
    await projects_service.create(project(p2, "two"))
    inherited = await bindings.get_current(p2)
    assert inherited.source_project_id == p1

    mapping = {key: PROVIDER_A for key in TASK_KEYS}
    mapping["writing"] = PROVIDER_B
    replaced = await bindings.replace_all(p2, 1, mapping)
    original_revision = await disposable_mysql.session.fetchone(
        "SELECT * FROM project_model_binding_revisions WHERE project_id=%s AND revision=2",
        (p2,),
    )
    original_items = await disposable_mysql.session.fetchall(
        "SELECT * FROM project_model_binding_items WHERE binding_revision_id=%s ORDER BY task_key",
        (original_revision["id"],),
    )
    assert {item.task_key: item.provider_id for item in replaced.items}["writing"] == PROVIDER_B

    await disposable_mysql.session.execute(
        "UPDATE provider_profiles SET enabled=0 WHERE id=%s", (PROVIDER_B,)
    )
    p3 = "40000000-0000-0000-0000-000000000003"
    await projects_service.create(project(p3, "three"))
    fallback = await bindings.get_current(p3)
    assert fallback.source_project_id == p1
    assert all(item.provider_id == PROVIDER_A for item in fallback.items)

    contender_mapping = {key: PROVIDER_A for key in TASK_KEYS}
    contender_mapping["market"] = None
    contenders = await asyncio.gather(
        *(
            bindings.replace_all(p1, 1, contender_mapping)
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    assert sum(getattr(item, "revision", None) == 2 for item in contenders) == 1
    assert sum(isinstance(item, BindingConflict) for item in contenders) == 1
    p1_current = await bindings.get_current(p1)
    assert p1_current.items[-1].task_key == "market"
    assert p1_current.items[-1].resolution_status == "unbound"

    provider_profiles = ProviderProfileService(
        SqlProviderProfileRepository(),
        transaction_factory=tx,
        connection_factory=None,
        connection_gateway=None,
    )
    await provider_profiles.delete(
        DeleteProviderCommand(
            provider_id=PROVIDER_B,
            expected_revision=1,
            idempotency_key="delete-beta-0001",
        )
    )
    deleted = await disposable_mysql.session.fetchone(
        "SELECT * FROM provider_profiles WHERE id=%s", (PROVIDER_B,)
    )
    assert deleted["enabled"] == 0
    assert deleted["lifecycle_status"] == "deleted"
    assert deleted["api_key"] == "" and deleted["base_url"] == ""
    assert deleted["deleted_at"] is not None

    historical_revision = await disposable_mysql.session.fetchone(
        "SELECT * FROM project_model_binding_revisions WHERE project_id=%s AND revision=2",
        (p2,),
    )
    historical_items = await disposable_mysql.session.fetchall(
        "SELECT * FROM project_model_binding_items WHERE binding_revision_id=%s ORDER BY task_key",
        (historical_revision["id"],),
    )
    assert historical_revision["content_hash"] == original_revision["content_hash"]
    assert historical_items == original_items
    assert replaced.content_hash != first.content_hash
    status = await bindings.get_status(p2)
    assert status.binding_complete is True
    assert status.binding_ready is False
    assert "provider_unavailable:writing" in status.reasons


@pytest.mark.asyncio
async def test_application_fallback_cas_first_ready_and_unbound_matrix(
    disposable_mysql,
):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    await insert_provider(
        disposable_mysql.session, PROVIDER_A, "Alpha", "a-model", 1
    )
    await insert_provider(
        disposable_mysql.session, PROVIDER_B, "Beta", "b-model", 2
    )
    application = ApplicationSettingsService(
        ApplicationSettingsRepository(),
        transaction_factory=tx,
        connection_factory=read_connection,
        clock=iter(range(10, 100)).__next__,
        corpus_store_ready=lambda: True,
        scheduler_enabled=False,
        scheduler_state="disabled",
        application_version="1.0.0",
    )
    configured = await application.update_default_model(
        UpdateDefaultModel(
            expected_revision=0,
            fallback_provider_id=PROVIDER_B,
        )
    )
    assert configured.revision == 1
    assert configured.fallback_provider.id == PROVIDER_B

    contenders = await asyncio.gather(
        application.update_default_model(
            UpdateDefaultModel(
                expected_revision=1,
                fallback_provider_id=PROVIDER_B,
            )
        ),
        application.update_default_model(
            UpdateDefaultModel(
                expected_revision=1,
                fallback_provider_id=PROVIDER_A,
            )
        ),
        return_exceptions=True,
    )
    assert sum(getattr(item, "revision", None) == 2 for item in contenders) == 1
    assert sum(
        isinstance(item, ApplicationSettingsConflict) for item in contenders
    ) == 1
    current_settings = await application.get()
    selected_fallback = current_settings.fallback_provider.id

    bindings = ModelBindingService(
        ModelBindingRepository(),
        transaction_factory=tx,
        connection_factory=read_connection,
    )
    projects = ProjectLifecycleService(
        ProjectRepository(),
        tx,
        read_connection,
        model_binding_service=bindings,
    )
    first_id = "41000000-0000-0000-0000-000000000001"
    await projects.create(project(first_id, "explicit fallback"))
    first = await bindings.get_current(first_id)
    assert all(
        item.provider_id == selected_fallback for item in first.items
    )

    await disposable_mysql.session.execute(
        "UPDATE provider_profiles SET enabled=0 WHERE id=%s",
        (selected_fallback,),
    )
    other_provider = (
        PROVIDER_A if selected_fallback == PROVIDER_B else PROVIDER_B
    )
    second_id = "41000000-0000-0000-0000-000000000002"
    await projects.create(project(second_id, "first ready"))
    second = await bindings.get_current(second_id)
    assert second.source_project_id is None
    assert all(item.provider_id == other_provider for item in second.items)

    await disposable_mysql.session.execute(
        "UPDATE provider_profiles SET enabled=0 WHERE id=%s",
        (other_provider,),
    )
    third_id = "41000000-0000-0000-0000-000000000003"
    await projects.create(project(third_id, "unbound allowed"))
    third = await bindings.get_current(third_id)
    assert third.binding_complete is True
    assert third.binding_ready is False
    assert len(third.items) == len(TASK_KEYS)
    assert all(item.resolution_status == "unbound" for item in third.items)


@pytest.mark.asyncio
async def test_same_created_time_uses_id_order_and_archived_projects_are_skipped(
    disposable_mysql,
):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    await insert_provider(
        disposable_mysql.session, PROVIDER_A, "Alpha", "a-model", 1
    )
    await insert_provider(
        disposable_mysql.session, PROVIDER_B, "Beta", "b-model", 2
    )
    bindings = ModelBindingService(
        ModelBindingRepository(),
        transaction_factory=tx,
        connection_factory=read_connection,
    )
    projects = ProjectLifecycleService(
        ProjectRepository(),
        tx,
        read_connection,
        model_binding_service=bindings,
    )
    low_id = "42000000-0000-0000-0000-000000000001"
    high_id = "42000000-0000-0000-0000-000000000002"
    await projects.create(project(low_id, "low"))
    await projects.create(project(high_id, "high"))
    await bindings.replace_all(
        high_id,
        1,
        {task_key: PROVIDER_B for task_key in TASK_KEYS},
    )
    await disposable_mysql.session.execute(
        "UPDATE projects SET created_at=777 WHERE id IN (%s,%s)",
        (low_id, high_id),
    )

    tied_id = "42000000-0000-0000-0000-000000000003"
    await projects.create(project(tied_id, "tie result"))
    tied = await bindings.get_current(tied_id)
    assert tied.source_project_id == high_id
    assert all(item.provider_id == PROVIDER_B for item in tied.items)

    await projects.archive(high_id, 0)
    await projects.archive(tied_id, 0)
    archived_read = await bindings.get_current(high_id)
    assert archived_read.project_id == high_id
    with pytest.raises(ProjectArchived):
        await bindings.replace_all(
            high_id,
            archived_read.revision,
            {task_key: PROVIDER_A for task_key in TASK_KEYS},
        )
    after_archive_id = "42000000-0000-0000-0000-000000000004"
    await projects.create(project(after_archive_id, "archive skip"))
    after_archive = await bindings.get_current(after_archive_id)
    assert after_archive.source_project_id == low_id
    assert all(item.provider_id == PROVIDER_A for item in after_archive.items)


@pytest.mark.asyncio
async def test_no_provider_is_complete_unbound_and_binding_failure_rolls_back(
    disposable_mysql
):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    bindings = ModelBindingService(
        ModelBindingRepository(), transaction_factory=tx,
        connection_factory=read_connection,
    )
    service = ProjectLifecycleService(
        ProjectRepository(), tx, read_connection,
        model_binding_service=bindings,
    )
    pid = "50000000-0000-0000-0000-000000000001"
    await service.create(project(pid, "unbound"))
    current = await bindings.get_current(pid)
    assert len(current.items) == len(TASK_KEYS)
    assert current.binding_complete is True
    assert current.binding_ready is False
    assert all(item.resolution_status == "unbound" for item in current.items)
    contract = await disposable_mysql.session.fetchone(
        "SELECT * FROM project_contract_heads WHERE project_id=%s", (pid,)
    )
    assert contract["revision"] == 0

    class FailingBindings:
        async def lock_project_creation(self, session):
            return None

        async def initialize_project(self, session, project_id):
            raise RuntimeError("binding failed")

    failed_id = "50000000-0000-0000-0000-000000000002"
    failing = ProjectLifecycleService(
        ProjectRepository(), tx, read_connection,
        model_binding_service=FailingBindings(),
    )
    with pytest.raises(RuntimeError, match="binding failed"):
        await failing.create(project(failed_id, "rollback"))
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM projects WHERE id=%s", (failed_id,)
    ) is None


@pytest.mark.asyncio
async def test_provider_delete_waits_until_initialize_writes_and_commits(
    disposable_mysql
):
    tx = transaction_factory_for(disposable_mysql.connection_config)
    providers_locked = asyncio.Event()
    allow_binding_write = asyncio.Event()
    delete_transaction_entered = asyncio.Event()

    class BlockingRepository(ModelBindingRepository):
        async def lock_providers(self, session, provider_ids):
            rows = await super().lock_providers(session, provider_ids)
            providers_locked.set()
            await allow_binding_write.wait()
            return rows

    repository = BlockingRepository()
    bindings = ModelBindingService(repository, transaction_factory=tx)
    service = ProjectLifecycleService(
        ProjectRepository(), tx, model_binding_service=bindings
    )
    await insert_provider(
        disposable_mysql.session, PROVIDER_A, "Alpha", "a-model", 1
    )
    project_id = "60000000-0000-0000-0000-000000000001"
    create_task = asyncio.create_task(service.create(project(project_id, "locked")))
    await providers_locked.wait()

    @asynccontextmanager
    async def observed_delete_transaction():
        async with tx() as session:
            delete_transaction_entered.set()
            yield session

    provider_profiles = ProviderProfileService(
        SqlProviderProfileRepository(),
        transaction_factory=observed_delete_transaction,
        connection_factory=None,
        connection_gateway=None,
    )
    delete_task = asyncio.create_task(
        provider_profiles.delete(
            DeleteProviderCommand(
                provider_id=PROVIDER_A,
                expected_revision=1,
                idempotency_key="delete-alpha-0001",
            )
        )
    )
    await delete_transaction_entered.wait()
    assert delete_task.done() is False

    allow_binding_write.set()
    await create_task
    await delete_task

    revision = await disposable_mysql.session.fetchone(
        "SELECT revision FROM project_model_binding_heads WHERE project_id=%s",
        (project_id,),
    )
    deleted = await disposable_mysql.session.fetchone(
        "SELECT lifecycle_status FROM provider_profiles WHERE id=%s",
        (PROVIDER_A,),
    )
    assert revision["revision"] == 1
    assert deleted["lifecycle_status"] == "deleted"


@pytest.mark.asyncio
async def test_concurrent_project_creation_waits_on_global_guard_before_insert(
    disposable_mysql
):
    tx = transaction_factory_for(disposable_mysql.connection_config)
    first_guard_acquired = asyncio.Event()
    release_first_guard = asyncio.Event()
    second_guard_attempted = asyncio.Event()
    second_guard_acquired = asyncio.Event()
    inserted_projects = []

    class GuardProbeRepository(ModelBindingRepository):
        def __init__(self):
            super().__init__()
            self.guard_calls = 0

        async def lock_project_creation_guard(self, session):
            self.guard_calls += 1
            call_number = self.guard_calls
            if call_number == 2:
                second_guard_attempted.set()
            await super().lock_project_creation_guard(session)
            if call_number == 1:
                first_guard_acquired.set()
                await release_first_guard.wait()
            else:
                second_guard_acquired.set()

    class InsertProbeRepository(ProjectRepository):
        async def insert_project(self, session, command):
            if command.id.endswith("1"):
                assert first_guard_acquired.is_set()
            else:
                assert second_guard_acquired.is_set()
            inserted_projects.append(command.id)
            await super().insert_project(session, command)

    bindings = ModelBindingService(
        GuardProbeRepository(), transaction_factory=tx
    )
    service = ProjectLifecycleService(
        InsertProbeRepository(), tx, model_binding_service=bindings
    )
    first_id = "70000000-0000-0000-0000-000000000001"
    second_id = "70000000-0000-0000-0000-000000000002"
    first_task = asyncio.create_task(service.create(project(first_id, "first")))
    guard_wait = asyncio.create_task(first_guard_acquired.wait())
    done, _ = await asyncio.wait(
        {first_task, guard_wait}, return_when=asyncio.FIRST_COMPLETED
    )
    if first_task in done:
        await first_task
    await guard_wait
    assert inserted_projects == []

    second_task = asyncio.create_task(service.create(project(second_id, "second")))
    await second_guard_attempted.wait()
    assert second_guard_acquired.is_set() is False
    assert inserted_projects == []

    release_first_guard.set()
    await asyncio.gather(first_task, second_task)
    assert inserted_projects == [first_id, second_id]

    expected_counts = {
        "projects": 2,
        "canon_revisions": 2,
        "projection_heads": 2,
        "project_contract_heads": 2,
        "project_model_binding_revisions": 2,
        "project_model_binding_heads": 2,
        "project_model_binding_items": 2 * len(TASK_KEYS),
    }
    for table, expected in expected_counts.items():
        row = await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table}"
        )
        assert int(row["count"]) == expected
