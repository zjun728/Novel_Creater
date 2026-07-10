"""Atomic orchestration for exactly two draft candidate writes."""

from __future__ import annotations

import hashlib
import json
from typing import Awaitable, Callable

from . import draft_write_repository as repository
from .draft_write_errors import (
    DraftWriteError,
    UnsafeDisposableDatabase,
    map_mysql_error,
    mysql_error_number,
)
from .draft_write_models import DraftWriteCommand, DraftWriteResult
from .draft_write_transaction import ConnectionLike, PoolLike, read_committed_transaction


DISPOSABLE_SCHEMA_PREFIX = "novel_creator_control_plane_disposable_"


class _LedgerDuplicate(Exception):
    pass


def _error(
    code: str,
    http_status: int,
    message: str,
    *,
    retryable: bool = False,
) -> DraftWriteError:
    return DraftWriteError(
        code=code,
        http_status=http_status,
        message=message,
        retryable=retryable,
    )


class DraftWriteService:
    def __init__(
        self,
        *,
        pool: PoolLike,
        expected_schema: str,
        run_token: str,
        uuid_factory: Callable[[], str],
        clock_ms: Callable[[], int],
        after_candidate_insert: Callable[[int], Awaitable[None]] | None = None,
        commit_operation: Callable[[ConnectionLike], Awaitable[None]] | None = None,
    ):
        """Accept only an explicitly injected disposable pool and dependencies."""

        if expected_schema != DISPOSABLE_SCHEMA_PREFIX + run_token:
            raise UnsafeDisposableDatabase()
        self._pool = pool
        self._expected_schema = expected_schema
        self._uuid_factory = uuid_factory
        self._clock_ms = clock_ms
        self._after_candidate_insert = after_candidate_insert
        self._commit_operation = commit_operation

    async def submit(self, command: DraftWriteCommand) -> DraftWriteResult:
        """Create both candidate rows and the complete ledger result atomically."""

        try:
            try:
                return await self._submit_new(command)
            except _LedgerDuplicate:
                return await self._resolve_duplicate(command)
        except BaseException as error:
            mapped = map_mysql_error(error)
            if mapped is not None:
                raise mapped from None
            raise

    async def _submit_new(self, command: DraftWriteCommand) -> DraftWriteResult:
        batch_id = str(self._uuid_factory())
        timestamp_ms = int(self._clock_ms())
        async with read_committed_transaction(
            pool=self._pool,
            expected_schema=self._expected_schema,
            commit_operation=self._commit_operation,
        ) as conn:
            project = await repository.lock_project(conn, command.project_id)
            if project is None:
                raise _error("project_not_found", 404, "Project was not found.")

            try:
                await repository.insert_pending_batch(
                    conn,
                    batch_id=batch_id,
                    project_id=command.project_id,
                    idempotency_key=command.idempotency_key,
                    manifest_sha256=command.manifest_sha256,
                    created_at=timestamp_ms,
                )
            except BaseException as error:
                if mysql_error_number(error) == 1062:
                    raise _LedgerDuplicate() from None
                raise

            chapters = await repository.lock_chapters(
                conn,
                (write.chapter_id for write in command.writes),
            )
            self._validate_chapters(command, chapters)

            sources = await repository.lock_source_versions(
                conn,
                (write.source_version_id for write in command.writes),
            )
            self._validate_sources(command, sources)
            self._validate_candidate_hashes(command)

            candidate_ids: list[str] = []
            for index, write in enumerate(command.writes, start=1):
                candidate_id = str(self._uuid_factory())
                candidate_ids.append(candidate_id)
                await repository.insert_candidate_version(
                    conn,
                    candidate_version_id=candidate_id,
                    project_id=command.project_id,
                    batch_id=batch_id,
                    write=write,
                    timestamp_ms=timestamp_ms,
                )
                if self._after_candidate_insert is not None:
                    await self._after_candidate_insert(index)

            result = DraftWriteResult(
                batch_id=batch_id,
                project_id=command.project_id,
                manifest_sha256=command.manifest_sha256,
                candidate_version_ids=(candidate_ids[0], candidate_ids[1]),
                committed_at=timestamp_ms,
            )
            await repository.complete_batch(conn, batch_id=batch_id, result=result)
            return result

    @staticmethod
    def _validate_chapters(command: DraftWriteCommand, rows: list[dict[str, object]]) -> None:
        by_id = {row.get("id"): row for row in rows}
        for write in command.writes:
            row = by_id.get(write.chapter_id)
            if row is None or row.get("project_id") != command.project_id:
                raise _error("chapter_not_found", 404, "Chapter was not found.")
            stored_number = row.get("chapter_num")
            if type(stored_number) is not int or stored_number != write.chapter_num:
                raise _error(
                    "chapter_identity_conflict",
                    409,
                    "Chapter identity does not match the manifest.",
                )
            if row.get("status") == "final" or row.get("final_version_id") is not None:
                raise _error("chapter_finalized", 409, "Chapter is already finalized.")

    @staticmethod
    def _validate_sources(command: DraftWriteCommand, rows: list[dict[str, object]]) -> None:
        by_id = {row.get("id"): row for row in rows}
        for write in command.writes:
            row = by_id.get(write.source_version_id)
            if row is None or row.get("project_id") != command.project_id:
                raise _error(
                    "source_version_not_found",
                    404,
                    "Source version was not found.",
                )
            if row.get("chapter_id") != write.chapter_id:
                raise _error(
                    "source_identity_conflict",
                    409,
                    "Source version identity does not match the manifest.",
                )
            content = row.get("content")
            if content is None or type(content) is not str:
                raise _error(
                    "source_content_unavailable",
                    409,
                    "Source version content is unavailable.",
                )
            actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if actual_hash != write.expected_source_content_sha256:
                raise _error(
                    "source_preimage_mismatch",
                    409,
                    "Source version content has changed.",
                )

    @staticmethod
    def _validate_candidate_hashes(command: DraftWriteCommand) -> None:
        for write in command.writes:
            actual_hash = hashlib.sha256(write.content.encode("utf-8")).hexdigest()
            if actual_hash != write.content_sha256:
                raise _error(
                    "candidate_content_hash_mismatch",
                    422,
                    "Candidate content hash does not match candidate content.",
                )

    async def _resolve_duplicate(self, command: DraftWriteCommand) -> DraftWriteResult:
        async with read_committed_transaction(
            pool=self._pool,
            expected_schema=self._expected_schema,
            commit_operation=self._commit_operation,
        ) as conn:
            row = await repository.read_batch(
                conn,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
            )
            if row is None:
                raise _error(
                    "idempotency_in_progress",
                    409,
                    "An idempotent write is still in progress.",
                    retryable=True,
                )
            if type(row) is not dict:
                raise _error(
                    "idempotency_in_progress",
                    409,
                    "An idempotent write is still in progress.",
                    retryable=True,
                )
            stored_hash = row.get("manifest_sha256")
            if isinstance(stored_hash, bytes):
                try:
                    stored_hash = stored_hash.decode("ascii")
                except UnicodeDecodeError:
                    stored_hash = None
            if stored_hash != command.manifest_sha256:
                raise _error(
                    "idempotency_manifest_conflict",
                    409,
                    "Idempotency key is already bound to another manifest.",
                )
            result = _stored_result(row, command)
            if result is None:
                raise _error(
                    "idempotency_in_progress",
                    409,
                    "An idempotent write is still in progress.",
                    retryable=True,
                )
            return result


def _stored_result(
    row: dict[str, object],
    command: DraftWriteCommand,
) -> DraftWriteResult | None:
    row_id = row.get("id")
    row_project_id = row.get("project_id")
    row_manifest_sha256 = row.get("manifest_sha256")
    row_committed_at = row.get("committed_at")
    if isinstance(row_manifest_sha256, bytes):
        try:
            row_manifest_sha256 = row_manifest_sha256.decode("ascii")
        except UnicodeDecodeError:
            return None
    if (
        type(row_id) is not str
        or not row_id
        or type(row_project_id) is not str
        or row_project_id != command.project_id
        or row_manifest_sha256 != command.manifest_sha256
        or type(row_committed_at) is not int
    ):
        return None

    value = row.get("result_json")
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if type(value) is not dict:
        return None
    expected_keys = {
        "batchId",
        "projectId",
        "manifestSha256",
        "candidateVersionIds",
        "committedAt",
    }
    if set(value) != expected_keys:
        return None
    candidate_ids = value.get("candidateVersionIds")
    committed_at = value.get("committedAt")
    if (
        type(value.get("batchId")) is not str
        or value["batchId"] != row_id
        or value.get("projectId") != row_project_id
        or value.get("manifestSha256") != row_manifest_sha256
        or type(candidate_ids) is not list
        or len(candidate_ids) != 2
        or any(type(candidate_id) is not str or not candidate_id for candidate_id in candidate_ids)
        or candidate_ids[0] == candidate_ids[1]
        or type(committed_at) is not int
        or committed_at != row_committed_at
    ):
        return None
    return DraftWriteResult(
        batch_id=value["batchId"],
        project_id=value["projectId"],
        manifest_sha256=value["manifestSha256"],
        candidate_version_ids=(candidate_ids[0], candidate_ids[1]),
        committed_at=committed_at,
    )
