from __future__ import annotations

from dataclasses import fields
import asyncio
import traceback

import pytest

from backend.repositories.project_imports import (
    MAX_IMPORT_LEASE_MS,
    ProjectImportCommandConflict,
    ProjectImportPersistenceError,
    ProjectImportCommandStateConflict,
    ProjectImportCommandView,
    ProjectImportRepository,
)


COMMAND_ID = "10000000-0000-4000-8000-000000000001"
TARGET_ID = "20000000-0000-4000-8000-000000000001"
FINGERPRINT = "a" * 64


class RecordingSession:
    def __init__(self, row=None, affected=1):
        self.row = row
        self.affected = affected
        self.calls = []

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        return self.affected

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        return self.row


def _row(**changes):
    row = {
        "id": COMMAND_ID,
        "request_fingerprint": FINGERPRINT,
        "status": "running",
        "phase": "staged",
        "owner_token": "30000000-0000-4000-8000-000000000001",
        "lease_expires_at": 200,
        "target_project_id": TARGET_ID,
        "public_error_code": None,
    }
    row.update(changes)
    return row


@pytest.mark.asyncio
async def test_read_command_returns_only_locked_safe_public_fields():
    session = RecordingSession(_row())

    view = await ProjectImportRepository().read_command(
        session, command_id=COMMAND_ID, now_ms=100
    )

    assert view == ProjectImportCommandView(
        command_id=COMMAND_ID,
        status="running",
        phase="staged",
        retry_required=False,
        target_project_id=None,
        public_error_code=None,
    )
    assert tuple(field.name for field in fields(view)) == (
        "command_id", "status", "phase", "retry_required",
        "target_project_id", "public_error_code",
    )
    _, sql, args = session.calls[0]
    compact = " ".join(sql.lower().split())
    assert "select *" not in compact
    assert "normalized_title" not in compact
    assert "package_hash" not in compact
    assert "staging_manifest_json" not in compact
    assert args == (COMMAND_ID,)


@pytest.mark.asyncio
async def test_expired_running_view_requires_retry_without_exposing_target():
    session = RecordingSession(_row(lease_expires_at=100))
    view = await ProjectImportRepository().read_command(
        session, command_id=COMMAND_ID, now_ms=100
    )
    assert view.retry_required is True
    assert view.target_project_id is None


@pytest.mark.asyncio
async def test_terminal_views_expose_only_their_fixed_outcome():
    succeeded = RecordingSession(_row(
        status="succeeded", phase="succeeded", owner_token=None,
        lease_expires_at=None,
    ))
    failed = RecordingSession(_row(
        status="failed", phase="failed", owner_token=None,
        lease_expires_at=None, public_error_code="PROJECT_IMPORT_FAILED",
    ))

    success_view = await ProjectImportRepository().read_command(
        succeeded, command_id=COMMAND_ID, now_ms=300
    )
    failed_view = await ProjectImportRepository().read_command(
        failed, command_id=COMMAND_ID, now_ms=300
    )

    assert success_view.target_project_id == TARGET_ID
    assert success_view.public_error_code is None
    assert failed_view.target_project_id is None
    assert failed_view.public_error_code == "PROJECT_IMPORT_FAILED"


@pytest.mark.asyncio
async def test_transition_is_one_parameterized_conditional_update_then_exact_read():
    session = RecordingSession(_row(status="failed", phase="failed", owner_token=None,
                                    lease_expires_at=None,
                                    public_error_code="PROJECT_IMPORT_FAILED"))

    view = await ProjectImportRepository().mark_failed(
        session,
        command_id=COMMAND_ID,
        request_fingerprint=FINGERPRINT,
        owner_token="30000000-0000-4000-8000-000000000001",
        now_ms=250,
    )

    assert view.status == "failed"
    assert [kind for kind, _, _ in session.calls] == ["execute", "fetchone"]
    _, update_sql, update_args = session.calls[0]
    assert "%s" in update_sql and COMMAND_ID not in update_sql
    assert " where " in f" {update_sql.lower()} "
    assert "request_fingerprint=%s" in " ".join(update_sql.lower().split())
    assert update_args[-4:] == (COMMAND_ID, FINGERPRINT,
                                "30000000-0000-4000-8000-000000000001", 250)
    assert "lease_expires_at>%s" in " ".join(update_sql.lower().split())


@pytest.mark.asyncio
async def test_failed_conditional_transition_raises_fixed_safe_error_from_none():
    session = RecordingSession(_row(), affected=0)
    with pytest.raises(ProjectImportCommandStateConflict) as caught:
        await ProjectImportRepository().mark_failed(
            session,
            command_id="secret-command",
            request_fingerprint="secret-fingerprint",
            owner_token="secret-owner",
            now_ms=250,
        )
    assert str(caught.value) == "project import command state conflict"
    assert caught.value.__cause__ is None
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_expired_owner_cannot_mark_command_failed():
    session = RecordingSession(_row(lease_expires_at=200), affected=0)
    with pytest.raises(ProjectImportCommandStateConflict):
        await ProjectImportRepository().mark_failed(
            session,
            command_id=COMMAND_ID,
            request_fingerprint=FINGERPRINT,
            owner_token="30000000-0000-4000-8000-000000000001",
            now_ms=200,
        )
    _, sql, args = session.calls[0]
    assert "lease_expires_at>%s" in " ".join(sql.lower().split())
    assert args[-1] == 200


def test_conflict_error_is_fixed_and_has_no_sensitive_constructor_fields():
    error = ProjectImportCommandConflict()
    assert str(error) == "project import command conflict"
    assert error.__cause__ is None


@pytest.mark.asyncio
async def test_lease_accepts_exact_bound_and_rejects_one_millisecond_over():
    repository = ProjectImportRepository()
    allowed = RecordingSession(_row(lease_expires_at=100 + MAX_IMPORT_LEASE_MS))
    view = await repository.acquire_lease(
        allowed,
        command_id=COMMAND_ID,
        request_fingerprint=FINGERPRINT,
        owner_token="30000000-0000-4000-8000-000000000001",
        now_ms=100,
        lease_expires_at=100 + MAX_IMPORT_LEASE_MS,
    )
    assert view.status == "running"

    rejected = RecordingSession(_row())
    with pytest.raises(ProjectImportCommandStateConflict) as caught:
        await repository.acquire_lease(
            rejected,
            command_id=COMMAND_ID,
            request_fingerprint=FINGERPRINT,
            owner_token="30000000-0000-4000-8000-000000000001",
            now_ms=100,
            lease_expires_at=101 + MAX_IMPORT_LEASE_MS,
        )
    assert rejected.calls == []
    assert str(caught.value) == "project import command state conflict"
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_zero_rowcount_acquire_is_idempotent_only_for_exact_post_state():
    owner = "30000000-0000-4000-8000-000000000001"
    exact = RecordingSession(
        _row(owner_token=owner, lease_expires_at=200), affected=0
    )
    view = await ProjectImportRepository().acquire_lease(
        exact,
        command_id=COMMAND_ID,
        request_fingerprint=FINGERPRINT,
        owner_token=owner,
        now_ms=100,
        lease_expires_at=200,
    )
    assert view.status == "running"
    assert [kind for kind, _, _ in exact.calls] == ["execute", "fetchone"]

    mismatch = RecordingSession(
        _row(owner_token=owner, lease_expires_at=201), affected=0
    )
    with pytest.raises(ProjectImportCommandStateConflict):
        await ProjectImportRepository().acquire_lease(
            mismatch,
            command_id=COMMAND_ID,
            request_fingerprint=FINGERPRINT,
            owner_token=owner,
            now_ms=100,
            lease_expires_at=200,
        )


_SENTINEL = "sql-id-hash-title-path-C:/private/archive.zip"


class _DuplicateError(Exception):
    errno = 1062


class FailingStorageSession:
    def __init__(self, *, fail_method: str, fail_call: int, duplicate_first=False):
        self.fail_method = fail_method
        self.fail_call = fail_call
        self.duplicate_first = duplicate_first
        self.counts = {"execute": 0, "fetchone": 0}

    def _failure(self, method):
        self.counts[method] += 1
        if self.duplicate_first and method == "execute" and self.counts[method] == 1:
            raise _DuplicateError(1062, _SENTINEL)
        if method == self.fail_method and self.counts[method] == self.fail_call:
            raise RuntimeError(_SENTINEL)

    async def execute(self, sql, args=None):
        self._failure("execute")
        return 1

    async def fetchone(self, sql, args=None):
        self._failure("fetchone")
        return _row()


class DuplicateClassificationSession:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        raise _DuplicateError(1062, _SENTINEL)

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        return next(self.rows)


async def _invoke_storage_case(case: str, session):
    repository = ProjectImportRepository()
    common = {
        "command_id": COMMAND_ID,
        "request_fingerprint": FINGERPRINT,
        "owner_token": "30000000-0000-4000-8000-000000000001",
        "now_ms": 100,
    }
    if case.startswith("reserve"):
        return await repository.reserve_command(
            session,
            command_id=COMMAND_ID,
            idempotency_key="1" * 64,
            request_fingerprint=FINGERPRINT,
            package_hash="b" * 64,
            manifest_hash="c" * 64,
            package_version=1,
            target_project_id=TARGET_ID,
            normalized_title="sensitive title",
            now_ms=100,
        )
    if case == "read":
        return await repository.read_command(session, command_id=COMMAND_ID, now_ms=100)
    if case.startswith("acquire"):
        return await repository.acquire_lease(
            session, **common, lease_expires_at=200
        )
    if case.startswith("mark_failed"):
        return await repository.mark_failed(session, **common)
    return await repository.mark_succeeded(
        session, **common, target_project_id=TARGET_ID
    )


@pytest.mark.parametrize(
    ("case", "fail_method", "fail_call", "duplicate_first"),
    (
        ("reserve_execute", "execute", 1, False),
        ("reserve_replay_fetch", "fetchone", 1, True),
        ("read", "fetchone", 1, False),
        ("acquire_execute", "execute", 1, False),
        ("acquire_read", "fetchone", 1, False),
        ("mark_failed_execute", "execute", 1, False),
        ("mark_failed_read", "fetchone", 1, False),
        ("mark_succeeded_execute", "execute", 1, False),
        ("mark_succeeded_read", "fetchone", 1, False),
    ),
)
@pytest.mark.asyncio
async def test_storage_failures_map_to_one_fixed_safe_boundary(
    case, fail_method, fail_call, duplicate_first
):
    session = FailingStorageSession(
        fail_method=fail_method,
        fail_call=fail_call,
        duplicate_first=duplicate_first,
    )
    with pytest.raises(ProjectImportPersistenceError) as caught:
        await _invoke_storage_case(case, session)

    assert str(caught.value) == "project import persistence failed"
    assert caught.value.__cause__ is None
    rendered = "".join(traceback.format_exception(caught.value))
    assert _SENTINEL not in rendered


@pytest.mark.asyncio
async def test_duplicate_replay_uses_locking_current_read():
    session = DuplicateClassificationSession((_row(),))
    view = await _invoke_storage_case("reserve_execute", session)
    assert view.command_id == COMMAND_ID
    _, sql, args = session.calls[1]
    assert "for update" in " ".join(sql.lower().split())
    assert args == ("1" * 64,)


@pytest.mark.asyncio
async def test_duplicate_command_classification_uses_locking_current_reads():
    session = DuplicateClassificationSession((None, {"id": COMMAND_ID}))
    with pytest.raises(ProjectImportCommandConflict):
        await _invoke_storage_case("reserve_execute", session)
    reads = [call for call in session.calls if call[0] == "fetchone"]
    assert len(reads) == 2
    assert all("for update" in " ".join(sql.lower().split()) for _, sql, _ in reads)
    assert reads[0][2] == ("1" * 64,)
    assert reads[1][2] == (COMMAND_ID,)


@pytest.mark.parametrize(
    "error",
    (ProjectImportCommandConflict(), ProjectImportCommandStateConflict()),
)
@pytest.mark.asyncio
async def test_business_conflicts_from_session_are_not_wrapped(error):
    class BusinessConflictSession:
        async def execute(self, sql, args=None):
            raise error

    with pytest.raises(type(error)) as caught:
        await _invoke_storage_case("reserve_execute", BusinessConflictSession())
    assert caught.value is error


@pytest.mark.asyncio
async def test_cancelled_error_remains_cancellation():
    class CancelledSession:
        async def execute(self, sql, args=None):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _invoke_storage_case("reserve_execute", CancelledSession())
