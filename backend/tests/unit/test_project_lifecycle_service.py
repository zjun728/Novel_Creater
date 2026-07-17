from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from copy import deepcopy

import pytest

from backend import http_errors
from backend.services.project_lifecycle import ProjectLifecycleService


def project_row(
    *,
    project_id: str = "p1",
    title: str = "Project",
    status: str = "drafting",
    archived_at=None,
    lifecycle_revision: int = 0,
):
    return {
        "id": project_id,
        "title": title,
        "genre": "",
        "description": "",
        "target_words": 100_000,
        "target_chapters": 100,
        "current_chapter": 3,
        "status": status,
        "archived_at": archived_at,
        "lifecycle_revision": lifecycle_revision,
    }


class FakeContext(AbstractAsyncContextManager):
    def __init__(self, factory):
        self.factory = factory
        self.session = object()

    async def __aenter__(self):
        self.factory.enter_count += 1
        self.factory.sessions.append(self.session)
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.factory.commit_count += 1
        else:
            self.factory.rollback_count += 1


class FakeContextFactory:
    def __init__(self):
        self.enter_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.sessions = []

    def __call__(self):
        return FakeContext(self)


class MemoryLifecycleRepository:
    def __init__(self, *rows, unfinished=False):
        self.rows = {row["id"]: deepcopy(row) for row in rows}
        self.unfinished = unfinished
        self.calls = []
        self.force_cas_failure = False

    def _record(self, name, session, *args):
        self.calls.append((name, session, *args))

    async def list_active(self, session):
        self._record("list_active", session)
        return [
            deepcopy(row)
            for row in self.rows.values()
            if row["archived_at"] is None
        ]

    async def list_archived(self, session):
        self._record("list_archived", session)
        return [
            deepcopy(row)
            for row in self.rows.values()
            if row["archived_at"] is not None
        ]

    async def get_any(self, session, project_id):
        self._record("get_any", session, project_id)
        row = self.rows.get(project_id)
        return deepcopy(row) if row else None

    async def lock_any(self, session, project_id):
        self._record("lock_any", session, project_id)
        row = self.rows.get(project_id)
        return deepcopy(row) if row else None

    async def lock_active_project(self, session, project_id):
        self._record("lock_active_project", session, project_id)
        row = self.rows.get(project_id)
        if row is None or row["archived_at"] is not None:
            return None
        return deepcopy(row)

    async def has_unfinished_operation(self, session, project_id):
        self._record("has_unfinished_operation", session, project_id)
        return self.unfinished

    async def rename(self, session, project_id, title):
        self._record("rename", session, project_id, title)
        row = self.rows.get(project_id)
        if self.force_cas_failure or row is None or row["archived_at"] is not None:
            return False
        row["title"] = title
        return True

    async def archive(self, session, project_id, expected_revision):
        self._record("archive", session, project_id, expected_revision)
        row = self.rows.get(project_id)
        if (
            self.force_cas_failure
            or row is None
            or row["archived_at"] is not None
            or row["lifecycle_revision"] != expected_revision
        ):
            return False
        row["archived_at"] = 1_234
        row["lifecycle_revision"] += 1
        return True

    async def restore(self, session, project_id, expected_revision):
        self._record("restore", session, project_id, expected_revision)
        row = self.rows.get(project_id)
        if (
            self.force_cas_failure
            or row is None
            or row["archived_at"] is None
            or row["lifecycle_revision"] != expected_revision
        ):
            return False
        row["archived_at"] = None
        row["lifecycle_revision"] += 1
        return True

    async def permanently_delete(self, session, project_id, expected_revision):
        self._record(
            "permanently_delete", session, project_id, expected_revision
        )
        row = self.rows.get(project_id)
        if (
            self.force_cas_failure
            or row is None
            or row["archived_at"] is None
            or row["lifecycle_revision"] != expected_revision
        ):
            return False
        del self.rows[project_id]
        return True


def make_service(repository):
    transactions = FakeContextFactory()
    connections = FakeContextFactory()
    service = ProjectLifecycleService(
        repository,
        transactions,
        connections,
    )
    return service, transactions, connections


@pytest.mark.parametrize(
    ("error_type_name", "status_code", "code", "message"),
    [
        ("ProjectArchived", 409, "ProjectArchived", "Project is archived"),
        (
            "ProjectLifecycleConflict",
            409,
            "ProjectLifecycleConflict",
            "Project lifecycle changed; refresh and retry",
        ),
        (
            "ProjectBusy",
            409,
            "ProjectBusy",
            "Project has an unfinished operation",
        ),
    ],
)
def test_project_lifecycle_errors_have_stable_public_contract(
    error_type_name, status_code, code, message
):
    error_type = getattr(http_errors, error_type_name)
    error = error_type()

    assert error.status_code == status_code
    assert error.code == code
    assert error.message == message
    assert str(error) == message


@pytest.mark.asyncio
async def test_active_and_archived_service_lists_are_disjoint():
    repository = MemoryLifecycleRepository(
        project_row(project_id="active"),
        project_row(project_id="archived", archived_at=500, lifecycle_revision=2),
    )
    service, _, connections = make_service(repository)

    active = await service.list_active()
    archived = await service.list_archived()

    assert [row.id for row in active] == ["active"]
    assert [row.id for row in archived] == ["archived"]
    assert active[0].archived_at is None
    assert archived[0].archived_at == 500
    assert connections.enter_count == 2


@pytest.mark.asyncio
async def test_get_distinguishes_missing_archived_and_included_archived():
    repository = MemoryLifecycleRepository(
        project_row(archived_at=500, lifecycle_revision=2)
    )
    service, _, _ = make_service(repository)

    with pytest.raises(http_errors.ProjectNotFound):
        await service.get("missing")
    with pytest.raises(http_errors.ProjectArchived):
        await service.get("p1")

    result = await service.get("p1", include_archived=True)
    assert result.archived_at == 500
    assert result.lifecycle_revision == 2


@pytest.mark.asyncio
async def test_rename_locks_active_project_and_changes_only_title():
    original = project_row(status="planning", lifecycle_revision=4)
    repository = MemoryLifecycleRepository(original)
    service, transactions, _ = make_service(repository)

    result = await service.rename("p1", "Changed")

    assert result.title == "Changed"
    assert result.status == "planning"
    assert result.current_chapter == original["current_chapter"]
    assert result.lifecycle_revision == 4
    assert [call[0] for call in repository.calls] == [
        "lock_active_project",
        "rename",
        "get_any",
    ]
    assert len({id(call[1]) for call in repository.calls}) == 1
    assert transactions.commit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "error_type"),
    [
        (None, http_errors.ProjectNotFound),
        (project_row(archived_at=123), http_errors.ProjectArchived),
    ],
)
async def test_rename_rejects_missing_or_archived_project(row, error_type):
    repository = MemoryLifecycleRepository(*(() if row is None else (row,)))
    service, transactions, _ = make_service(repository)

    with pytest.raises(error_type):
        await service.rename("p1", "Changed")

    assert [call[0] for call in repository.calls] == [
        "lock_active_project",
        "lock_any",
    ]
    assert transactions.rollback_count == 1


@pytest.mark.asyncio
async def test_archive_preserves_workflow_status_and_returns_next_revision():
    repository = MemoryLifecycleRepository(
        project_row(status="planning", lifecycle_revision=6)
    )
    service, transactions, _ = make_service(repository)

    result = await service.archive("p1", 6)

    assert result.status == "planning"
    assert result.archived_at == 1_234
    assert result.lifecycle_revision == 7
    assert [call[0] for call in repository.calls] == [
        "lock_any",
        "has_unfinished_operation",
        "archive",
        "get_any",
    ]
    assert len({id(call[1]) for call in repository.calls}) == 1
    assert transactions.commit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["archive", "restore", "permanently_delete"])
async def test_lifecycle_commands_reject_unfinished_operations(operation):
    row = (
        project_row(lifecycle_revision=3)
        if operation == "archive"
        else project_row(archived_at=500, lifecycle_revision=3)
    )
    repository = MemoryLifecycleRepository(row, unfinished=True)
    service, transactions, _ = make_service(repository)

    with pytest.raises(http_errors.ProjectBusy):
        await getattr(service, operation)("p1", 3)

    assert [call[0] for call in repository.calls] == [
        "lock_any",
        "has_unfinished_operation",
    ]
    assert transactions.rollback_count == 1


@pytest.mark.asyncio
async def test_restore_only_clears_archive_marker_and_increments_revision():
    original = project_row(
        status="planning",
        archived_at=500,
        lifecycle_revision=8,
    )
    repository = MemoryLifecycleRepository(original)
    service, transactions, _ = make_service(repository)

    result = await service.restore("p1", 8)

    assert result.archived_at is None
    assert result.lifecycle_revision == 9
    assert result.status == original["status"]
    assert result.title == original["title"]
    assert result.current_chapter == original["current_chapter"]
    assert [call[0] for call in repository.calls] == [
        "lock_any",
        "has_unfinished_operation",
        "restore",
        "get_any",
    ]
    assert transactions.commit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "row", "expected_revision", "error_type"),
    [
        ("archive", None, 0, http_errors.ProjectNotFound),
        (
            "archive",
            project_row(archived_at=500, lifecycle_revision=2),
            2,
            http_errors.ProjectArchived,
        ),
        (
            "archive",
            project_row(lifecycle_revision=2),
            1,
            http_errors.ProjectLifecycleConflict,
        ),
        ("restore", None, 0, http_errors.ProjectNotFound),
        (
            "restore",
            project_row(lifecycle_revision=2),
            2,
            http_errors.ProjectLifecycleConflict,
        ),
        (
            "restore",
            project_row(archived_at=500, lifecycle_revision=2),
            1,
            http_errors.ProjectLifecycleConflict,
        ),
        ("permanently_delete", None, 0, http_errors.ProjectNotFound),
        (
            "permanently_delete",
            project_row(lifecycle_revision=2),
            2,
            http_errors.ProjectLifecycleConflict,
        ),
        (
            "permanently_delete",
            project_row(archived_at=500, lifecycle_revision=2),
            1,
            http_errors.ProjectLifecycleConflict,
        ),
    ],
)
async def test_lifecycle_commands_return_stable_state_errors(
    operation, row, expected_revision, error_type
):
    repository = MemoryLifecycleRepository(*(() if row is None else (row,)))
    service, transactions, _ = make_service(repository)

    with pytest.raises(error_type):
        await getattr(service, operation)("p1", expected_revision)

    assert transactions.rollback_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["archive", "restore", "permanently_delete"])
async def test_repository_compare_and_swap_failure_is_lifecycle_conflict(operation):
    row = (
        project_row(lifecycle_revision=3)
        if operation == "archive"
        else project_row(archived_at=500, lifecycle_revision=3)
    )
    repository = MemoryLifecycleRepository(row)
    repository.force_cas_failure = True
    service, transactions, _ = make_service(repository)

    with pytest.raises(http_errors.ProjectLifecycleConflict):
        await getattr(service, operation)("p1", 3)

    assert transactions.rollback_count == 1


@pytest.mark.asyncio
async def test_permanent_delete_locks_archived_project_and_deletes_it():
    repository = MemoryLifecycleRepository(
        project_row(archived_at=500, lifecycle_revision=4)
    )
    service, transactions, _ = make_service(repository)

    result = await service.permanently_delete("p1", 4)

    assert result is None
    assert "p1" not in repository.rows
    assert [call[0] for call in repository.calls] == [
        "lock_any",
        "has_unfinished_operation",
        "permanently_delete",
    ]
    assert len({id(call[1]) for call in repository.calls}) == 1
    assert transactions.commit_count == 1
