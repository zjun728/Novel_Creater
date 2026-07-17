from __future__ import annotations

from contextlib import AbstractAsyncContextManager

import pytest
from pydantic import ValidationError

from backend import http_errors
from backend.repositories.projects import ProjectRepository
from backend.services.projections import build_projection_bundle
from backend.services.projects import CreateProject, ProjectService, UpdateProject


class FakeTransaction(AbstractAsyncContextManager):
    def __init__(self, factory):
        self.factory = factory
        self.session = object()

    async def __aenter__(self):
        self.factory.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.factory.commit_count += 1
        else:
            self.factory.rollback_count += 1


class FakeTransactionFactory:
    def __init__(self):
        self.enter_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def __call__(self):
        return FakeTransaction(self)


class FakeProjectRepository:
    STEPS = ("guard", "project", "revision", "projection", "contract", "binding")

    def __init__(self):
        self.calls = []
        self.sessions = []
        self.fail_at = None
        self.revision = None
        self.projection = None
        self.contract = None

    def _record(self, step, session, value=None):
        self.calls.append(step)
        self.sessions.append(session)
        if self.fail_at == step:
            raise RuntimeError(f"{step} failed")
        return value

    async def insert_project(self, session, command):
        self._record("project", session)

    async def insert_bootstrap_revision(
        self, session, project_id, *, content_hash, idempotency_key
    ):
        self.revision = {"content_hash": content_hash, "key": idempotency_key}
        self._record("revision", session)

    async def insert_projection_head(self, session, project_id, *, content_hash):
        self.projection = {"content_hash": content_hash}
        self._record("projection", session)

    async def insert_contract_head0(self, session, project_id):
        self.contract = {"project_id": project_id, "revision": 0}
        self._record("contract", session)


class FakeBindingService:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.fail_at = None

    async def lock_project_creation(self, session):
        self.events.append("guard")
        self.calls.append(("guard", session, None))
        if self.fail_at == "guard":
            raise RuntimeError("guard failed")

    async def initialize_project(self, session, project_id):
        self.events.append("binding")
        self.calls.append(("binding", session, project_id))
        if self.fail_at == "binding":
            raise RuntimeError("binding failed")


def command(**overrides):
    values = {
        "id": "p1",
        "title": "新项目",
        "genre": "穿越",
        "description": "",
        "target_words": 100_000,
        "target_chapters": 100,
    }
    values.update(overrides)
    return CreateProject(**values)


@pytest.mark.asyncio
async def test_create_builds_all_foundations_and_delegates_binding_on_one_session():
    repository = FakeProjectRepository()
    bindings = FakeBindingService(repository.calls)
    transactions = FakeTransactionFactory()

    result = await ProjectService(
        repository,
        transactions,
        model_binding_service=bindings,
    ).create(command())

    empty_hash = build_projection_bundle(0, ()).content_hash
    assert result.id == "p1"
    assert repository.calls == list(FakeProjectRepository.STEPS)
    assert repository.revision["content_hash"] == empty_hash
    assert repository.projection["content_hash"] == empty_hash
    assert repository.contract == {"project_id": "p1", "revision": 0}
    assert repository.revision["key"] == ProjectService.bootstrap_idempotency_key("p1")
    assert bindings.calls == [
        ("guard", repository.sessions[0], None),
        ("binding", repository.sessions[0], "p1"),
    ]
    all_sessions = repository.sessions + [call[1] for call in bindings.calls]
    assert len({id(session) for session in all_sessions}) == 1
    assert transactions.commit_count == 1
    assert transactions.rollback_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_step", FakeProjectRepository.STEPS)
async def test_create_rolls_back_when_any_foundation_step_fails(failed_step):
    repository = FakeProjectRepository()
    bindings = FakeBindingService(repository.calls)
    transactions = FakeTransactionFactory()
    if failed_step in {"guard", "binding"}:
        bindings.fail_at = failed_step
    else:
        repository.fail_at = failed_step

    with pytest.raises(RuntimeError, match=f"{failed_step} failed"):
        await ProjectService(
            repository,
            transactions,
            model_binding_service=bindings,
        ).create(command())

    assert transactions.commit_count == 0
    assert transactions.rollback_count == 1


def test_create_project_is_strict_frozen_and_rejects_extra_fields():
    with pytest.raises(ValidationError):
        command(target_words="100000")
    with pytest.raises(ValidationError):
        CreateProject(**command().model_dump(), unexpected=True)
    value = command()
    with pytest.raises(ValidationError):
        value.title = "changed"


class RecordingSession:
    def __init__(self, *, execute_result=1):
        self.calls = []
        self.fetchone_result = None
        self.fetchall_result = []
        self.execute_result = execute_result

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return self.execute_result

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return self.fetchone_result

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        return self.fetchall_result


@pytest.mark.asyncio
async def test_repository_inserts_contract_head_zero_on_explicit_session():
    session = RecordingSession()

    await ProjectRepository(clock=lambda: 123).insert_contract_head0(session, "p1")

    assert session.calls == [
        (
            "execute",
            "INSERT INTO project_contract_heads (project_id, revision, creation_contract_id, style_contract_id, creation_hash, style_hash, updated_at) VALUES (%s,0,NULL,NULL,NULL,NULL,%s)",
            ("p1", 123),
        )
    ]


@pytest.mark.asyncio
async def test_repository_project_reads_hide_archived_rows():
    session = RecordingSession()
    repository = ProjectRepository()

    await repository.list(session)
    await repository.get(session, "p1")

    assert session.calls == [
        (
            "fetchall",
            "SELECT * FROM projects WHERE archived_at IS NULL ORDER BY updated_at DESC, id DESC",
            None,
        ),
        (
            "fetchone",
            "SELECT * FROM projects WHERE id=%s AND archived_at IS NULL",
            ("p1",),
        ),
    ]


@pytest.mark.asyncio
async def test_repository_locks_only_active_project_on_explicit_session():
    session = RecordingSession()

    await ProjectRepository().lock_active_project(session, "p1")

    assert session.calls == [
        (
            "fetchone",
            "SELECT * FROM projects WHERE id=%s AND archived_at IS NULL FOR UPDATE",
            ("p1",),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("affected, expected", [(1, True), (0, False), (2, False)])
async def test_repository_archive_checks_conditional_update_rowcount(affected, expected):
    session = RecordingSession(execute_result=affected)

    changed = await ProjectRepository(clock=lambda: 123).archive(session, "p1")

    assert changed is expected
    assert session.calls == [
        (
            "execute",
            "UPDATE projects SET archived_at=%s,lifecycle_revision=lifecycle_revision+1,updated_at=%s WHERE id=%s AND archived_at IS NULL",
            (123, 123, "p1"),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("affected, expected", [(1, True), (0, False), (2, False)])
async def test_repository_update_is_conditional_on_active_project(affected, expected):
    session = RecordingSession(execute_result=affected)

    changed = await ProjectRepository(clock=lambda: 456).update(
        session, "p1", {"title": "Changed"}
    )

    assert changed is expected
    assert session.calls == [
        (
            "execute",
            "UPDATE projects SET title=%s, updated_at=%s WHERE id=%s AND archived_at IS NULL",
            ("Changed", 456, "p1"),
        )
    ]


@pytest.mark.asyncio
async def test_repository_update_rejects_status_changes():
    session = RecordingSession()

    with pytest.raises(ValueError, match="unsupported fields"):
        await ProjectRepository().update(session, "p1", {"status": "drafting"})

    assert session.calls == []


class FakeProjectArchiveRepository:
    def __init__(self, *, active_project=None, archive_result=True, archive_error=None):
        self.active_project = active_project
        self.archive_result = archive_result
        self.archive_error = archive_error
        self.calls = []

    async def lock_active_project(self, session, project_id):
        self.calls.append(("lock", session, project_id))
        if self.active_project and self.active_project.get("status") == "archived":
            return None
        return self.active_project

    async def archive(self, session, project_id):
        self.calls.append(("archive", session, project_id))
        if self.archive_error is not None:
            raise self.archive_error
        return self.archive_result


@pytest.mark.asyncio
async def test_delete_locks_and_archives_project_in_one_transaction():
    repository = FakeProjectArchiveRepository(active_project={"id": "p1"})
    transactions = FakeTransactionFactory()

    await ProjectService(repository, transactions).delete("p1")

    assert [call[0] for call in repository.calls] == ["lock", "archive"]
    assert repository.calls[0][1] is repository.calls[1][1]
    assert transactions.enter_count == 1
    assert transactions.commit_count == 1
    assert transactions.rollback_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("active_project", [None, {"id": "p1", "status": "archived"}])
async def test_delete_missing_or_archived_project_raises_stable_not_found(active_project):
    repository = FakeProjectArchiveRepository(active_project=active_project)
    transactions = FakeTransactionFactory()

    with pytest.raises(http_errors.ProjectNotFound):
        await ProjectService(repository, transactions).delete("p1")

    assert [call[0] for call in repository.calls] == ["lock"]
    assert transactions.commit_count == 0
    assert transactions.rollback_count == 1


class FakeProjectLifecycleRepository:
    def __init__(self, *, active_project=None, update_result=True):
        self.active_project = active_project
        self.update_result = update_result
        self.calls = []

    async def lock_active_project(self, session, project_id):
        self.calls.append(("lock", session, project_id))
        return self.active_project

    async def update(self, session, project_id, changes):
        self.calls.append(("update", session, project_id, changes))
        return self.update_result

    async def get(self, session, project_id):
        self.calls.append(("get", session, project_id))
        return self.active_project

    async def content_state(self, session, project_id):
        self.calls.append(("content_state", session, project_id))
        return {
            "seeds_count": 3,
            "canon_head_revision": 2,
            "has_final_chapters": True,
        }


@pytest.mark.asyncio
async def test_update_locks_then_writes_without_status_on_one_transaction():
    repository = FakeProjectLifecycleRepository(
        active_project={"id": "p1", "status": "drafting"}
    )
    transactions = FakeTransactionFactory()

    result = await ProjectService(repository, transactions).update(
        "p1", UpdateProject(title="Changed", status="drafting")
    )

    assert result == {"id": "p1", "status": "drafting"}
    assert [call[0] for call in repository.calls] == ["lock", "update", "get"]
    assert repository.calls[1][3] == {"title": "Changed"}
    assert len({id(call[1]) for call in repository.calls}) == 1
    assert transactions.enter_count == 1
    assert transactions.commit_count == 1
    assert transactions.rollback_count == 0


@pytest.mark.asyncio
async def test_update_after_archive_returns_none_without_writing():
    repository = FakeProjectLifecycleRepository(active_project=None)
    transactions = FakeTransactionFactory()

    result = await ProjectService(repository, transactions).update(
        "p1", UpdateProject(title="Changed", status="drafting")
    )

    assert result is None
    assert [call[0] for call in repository.calls] == ["lock"]
    assert transactions.enter_count == 1


@pytest.mark.asyncio
async def test_update_zero_row_result_returns_none_without_followup_read():
    repository = FakeProjectLifecycleRepository(
        active_project={"id": "p1", "status": "drafting"}, update_result=False
    )

    result = await ProjectService(repository, FakeTransactionFactory()).update(
        "p1", UpdateProject(title="Changed")
    )

    assert result is None
    assert [call[0] for call in repository.calls] == ["lock", "update"]


@pytest.mark.asyncio
async def test_content_state_checks_active_project_on_same_read_session():
    repository = FakeProjectLifecycleRepository(
        active_project={"id": "p1", "status": "drafting"}
    )
    connections = FakeTransactionFactory()

    state = await ProjectService(
        repository, FakeTransactionFactory(), connections
    ).content_state("p1")

    assert state["canon_head_revision"] == 2
    assert [call[0] for call in repository.calls] == ["get", "content_state"]
    assert repository.calls[0][1] is repository.calls[1][1]


@pytest.mark.asyncio
async def test_content_state_archived_project_raises_stable_not_found_without_readiness_query():
    repository = FakeProjectLifecycleRepository(active_project=None)

    with pytest.raises(http_errors.ProjectNotFound):
        await ProjectService(
            repository, FakeTransactionFactory(), FakeTransactionFactory()
        ).content_state("p1")

    assert [call[0] for call in repository.calls] == ["get"]


@pytest.mark.asyncio
async def test_delete_rolls_back_when_archive_fails():
    repository = FakeProjectArchiveRepository(
        active_project={"id": "p1"}, archive_error=RuntimeError("archive failed")
    )
    transactions = FakeTransactionFactory()

    with pytest.raises(RuntimeError, match="archive failed"):
        await ProjectService(repository, transactions).delete("p1")

    assert transactions.commit_count == 0
    assert transactions.rollback_count == 1


@pytest.mark.asyncio
async def test_delete_zero_row_archive_rolls_back_as_stable_not_found():
    repository = FakeProjectArchiveRepository(
        active_project={"id": "p1"}, archive_result=False
    )
    transactions = FakeTransactionFactory()

    with pytest.raises(http_errors.ProjectNotFound):
        await ProjectService(repository, transactions).delete("p1")

    assert transactions.commit_count == 0
    assert transactions.rollback_count == 1


@pytest.mark.asyncio
async def test_content_state_reads_only_new_seed_head_and_final_chapter_tables():
    class ContentStateSession(RecordingSession):
        async def fetchone(self, sql, args=None):
            self.calls.append(("fetchone", " ".join(sql.split()), args))
            return {
                "seeds_count": 3,
                "canon_head_revision": 2,
                "final_chapters_count": 1,
            }

    session = ContentStateSession()
    state = await ProjectRepository().content_state(session, "p1")
    assert state == {
        "seeds_count": 3,
        "canon_head_revision": 2,
        "has_final_chapters": True,
    }
