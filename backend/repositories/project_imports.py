"""Recoverable command persistence for atomic project imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


_PUBLIC_ERROR_CODE = "PROJECT_IMPORT_FAILED"
MAX_IMPORT_LEASE_MS = 300_000
_PUBLIC_COLUMNS = """id,request_fingerprint,status,phase,owner_token,
lease_expires_at,target_project_id,public_error_code"""


class ProjectImportCommandConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("project import command conflict")


class ProjectImportCommandStateConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("project import command state conflict")


class ProjectImportPersistenceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("project import persistence failed")


@dataclass(frozen=True, slots=True)
class ProjectImportCommandView:
    command_id: str
    status: Literal["reserved", "running", "succeeded", "failed"]
    phase: Literal[
        "uploaded", "preflighted", "staged", "publishing", "succeeded", "failed"
    ]
    retry_required: bool
    target_project_id: str | None
    public_error_code: str | None


def _is_duplicate_key_error(exc: Exception) -> bool:
    errno = getattr(exc, "errno", None)
    if errno == 1062:
        return True
    if not exc.args:
        return False
    first = exc.args[0]
    return first == 1062 or (
        isinstance(first, tuple) and bool(first) and first[0] == 1062
    )


def _view(row, now_ms: int) -> ProjectImportCommandView:
    status = row["status"]
    succeeded = status == "succeeded"
    failed = status == "failed"
    lease_expires_at = row["lease_expires_at"]
    return ProjectImportCommandView(
        command_id=row["id"],
        status=status,
        phase=row["phase"],
        retry_required=(
            status == "running"
            and lease_expires_at is not None
            and lease_expires_at <= now_ms
        ),
        target_project_id=row["target_project_id"] if succeeded else None,
        public_error_code=row["public_error_code"] if failed else None,
    )


async def _execute(session, sql: str, args):
    try:
        return await session.execute(sql, args)
    except (
        ProjectImportCommandConflict,
        ProjectImportCommandStateConflict,
        ProjectImportPersistenceError,
    ):
        raise
    except Exception:
        raise ProjectImportPersistenceError() from None


async def _fetchone(session, sql: str, args):
    try:
        return await session.fetchone(sql, args)
    except (
        ProjectImportCommandConflict,
        ProjectImportCommandStateConflict,
        ProjectImportPersistenceError,
    ):
        raise
    except Exception:
        raise ProjectImportPersistenceError() from None


class ProjectImportRepository:
    async def _read_exact(self, session, command_id: str):
        return await _fetchone(
            session,
            f"""SELECT {_PUBLIC_COLUMNS}
                FROM project_package_import_commands WHERE id=%s""",
            (command_id,),
        )

    async def read_command(
        self, session, *, command_id: str, now_ms: int
    ) -> ProjectImportCommandView | None:
        row = await self._read_exact(session, command_id)
        return None if row is None else _view(row, now_ms)

    async def reserve_command(
        self,
        session,
        *,
        command_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        package_hash: str,
        manifest_hash: str,
        package_version: int,
        target_project_id: str,
        normalized_title: str,
        now_ms: int,
    ) -> ProjectImportCommandView:
        try:
            await session.execute(
                """INSERT INTO project_package_import_commands
                   (id,idempotency_key,request_fingerprint,package_hash,
                    manifest_hash,package_version,target_project_id,
                    normalized_title,status,phase,owner_token,lease_expires_at,
                    staging_manifest_json,public_error_code,created_at,updated_at,
                    completed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'reserved','preflighted',
                           NULL,NULL,NULL,NULL,%s,%s,NULL)""",
                (
                    command_id,
                    idempotency_key,
                    request_fingerprint,
                    package_hash,
                    manifest_hash,
                    package_version,
                    target_project_id,
                    normalized_title,
                    now_ms,
                    now_ms,
                ),
            )
        except (
            ProjectImportCommandConflict,
            ProjectImportCommandStateConflict,
            ProjectImportPersistenceError,
        ):
            raise
        except Exception as exc:
            if not _is_duplicate_key_error(exc):
                raise ProjectImportPersistenceError() from None
            replay = await _fetchone(
                session,
                f"""SELECT {_PUBLIC_COLUMNS}
                    FROM project_package_import_commands
                    WHERE idempotency_key=%s FOR UPDATE""",
                (idempotency_key,),
            )
            if replay is not None and replay["request_fingerprint"] == request_fingerprint:
                return _view(replay, now_ms)
            await _fetchone(
                session,
                """SELECT id FROM project_package_import_commands
                   WHERE id=%s FOR UPDATE""",
                (command_id,),
            )
            raise ProjectImportCommandConflict() from None

        row = await self._read_exact(session, command_id)
        if row is None:
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)

    async def acquire_lease(
        self,
        session,
        *,
        command_id: str,
        request_fingerprint: str,
        owner_token: str,
        now_ms: int,
        lease_expires_at: int,
    ) -> ProjectImportCommandView:
        if not now_ms < lease_expires_at <= now_ms + MAX_IMPORT_LEASE_MS:
            raise ProjectImportCommandStateConflict() from None
        affected = await _execute(
            session,
            """UPDATE project_package_import_commands
               SET status='running',owner_token=%s,lease_expires_at=%s,updated_at=%s
               WHERE id=%s AND request_fingerprint=%s
                 AND status IN ('reserved','running')
                 AND (status='reserved' OR owner_token=%s OR lease_expires_at<=%s)""",
            (
                owner_token,
                lease_expires_at,
                now_ms,
                command_id,
                request_fingerprint,
                owner_token,
                now_ms,
            ),
        )
        row = await self._read_exact(session, command_id)
        if (
            affected not in (0, 1)
            or row is None
            or row["request_fingerprint"] != request_fingerprint
            or row["status"] != "running"
            or row["owner_token"] != owner_token
            or row["lease_expires_at"] != lease_expires_at
        ):
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)

    async def mark_failed(
        self,
        session,
        *,
        command_id: str,
        request_fingerprint: str,
        owner_token: str,
        now_ms: int,
    ) -> ProjectImportCommandView:
        affected = await _execute(
            session,
            """UPDATE project_package_import_commands
               SET status='failed',phase='failed',owner_token=NULL,
                   lease_expires_at=NULL,public_error_code=%s,
                   updated_at=%s,completed_at=%s
               WHERE id=%s AND request_fingerprint=%s AND owner_token=%s
                 AND status='running' AND lease_expires_at>%s""",
            (
                _PUBLIC_ERROR_CODE,
                now_ms,
                now_ms,
                command_id,
                request_fingerprint,
                owner_token,
                now_ms,
            ),
        )
        row = await self._read_exact(session, command_id)
        if affected != 1 or row is None:
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)

    async def mark_succeeded(
        self,
        session,
        *,
        command_id: str,
        request_fingerprint: str,
        owner_token: str,
        target_project_id: str,
        now_ms: int,
    ) -> ProjectImportCommandView:
        affected = await _execute(
            session,
            """UPDATE project_package_import_commands
               SET status='succeeded',phase='succeeded',owner_token=NULL,
                   lease_expires_at=NULL,public_error_code=NULL,
                   updated_at=%s,completed_at=%s
               WHERE id=%s AND request_fingerprint=%s AND owner_token=%s
                 AND target_project_id=%s AND status='running'
                 AND lease_expires_at>%s""",
            (
                now_ms,
                now_ms,
                command_id,
                request_fingerprint,
                owner_token,
                target_project_id,
                now_ms,
            ),
        )
        row = await self._read_exact(session, command_id)
        if affected != 1 or row is None:
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)
