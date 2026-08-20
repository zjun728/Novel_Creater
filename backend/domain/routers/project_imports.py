"""Closed multipart API for atomic project imports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile
from starlette.requests import ClientDisconnect
from python_multipart.multipart import MultipartParser, parse_options_header

from backend.config import (
    current_runtime_configuration,
    require_managed_corpus_root,
)
from backend.domain.project_imports import (
    OwnedImportQuarantine,
    ProjectImportInvalid,
    ProjectImportSensitiveData,
    ProjectImportTooLarge,
)
from backend.domain.project_packages import MAX_ARCHIVE_BYTES
from backend.repositories.project_imports import (
    ProjectImportCommandConflict,
    ProjectImportCommandStateConflict,
    ProjectImportCommandView,
    ProjectImportPersistenceError,
    ProjectImportRepository,
)
from backend.services.project_imports import ImportProjectRequest, ProjectImportService


router = APIRouter(tags=["project-imports"])
PROJECT_IMPORT_TEMP_PARENT = Path(tempfile.gettempdir())
_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}
_KEY = re.compile(r"[a-z0-9_-]{16,64}")
_HASH = re.compile(r"[0-9a-f]{64}")
MAX_IMPORT_FILE_BYTES = MAX_ARCHIVE_BYTES
MAX_IMPORT_FIELD_BYTES = 1024
MAX_IMPORT_HEADER_BYTES = 4096
MAX_IMPORT_MULTIPART_OVERHEAD = 64 * 1024


async def get_project_import_service() -> ProjectImportService:
    snapshot = current_runtime_configuration()
    return ProjectImportService(
        repository=ProjectImportRepository(),
        managed_corpus_root=require_managed_corpus_root(
            snapshot.managed_corpus_root
        ),
        temp_parent=PROJECT_IMPORT_TEMP_PARENT,
    )


def _response(content: dict[str, object], status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=content, headers=_PRIVATE_HEADERS)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return _response({
        "code": code,
        "message": message,
        "correlationId": str(uuid4()),
    }, status)


def _invalid_response() -> JSONResponse:
    return _error(422, "ProjectImportInvalid", "Project import package is invalid")


def _strict_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return None
    return value if str(parsed) == value else None


@dataclass(slots=True)
class _OwnedMultipart:
    upload: UploadFile
    fields: dict[str, str]
    owner: OwnedImportQuarantine

    async def close(self) -> None:
        for attempt in range(2):
            try:
                await self.upload.close()
                self.owner.cleanup()
                return
            except BaseException:
                if attempt:
                    return


async def _close_partial(upload, opened, owner) -> None:
    for attempt in range(2):
        try:
            if upload is not None:
                await upload.close()
            elif opened is not None:
                opened.close()
            if owner is not None:
                owner.cleanup()
            return
        except BaseException:
            if attempt:
                return


async def _stream_form(request: Request, expected: frozenset[str]) -> _OwnedMultipart:
    content_type = request.headers.get("content-type", "")
    media_type, options = parse_options_header(content_type)
    boundary = options.get(b"boundary")
    if media_type != b"multipart/form-data" or not boundary:
        raise ProjectImportInvalid("invalid project import multipart")
    try:
        temp_parent = PROJECT_IMPORT_TEMP_PARENT.resolve(strict=True)
        if not temp_parent.is_dir() or PROJECT_IMPORT_TEMP_PARENT.is_symlink():
            raise OSError
    except (OSError, RuntimeError, ValueError):
        raise ProjectImportInvalid("invalid project import multipart") from None

    opened = None
    upload = None
    owner = None
    fields: dict[str, str] = {}
    seen: set[str] = set()
    header_field = bytearray()
    header_value = bytearray()
    headers: dict[bytes, bytes] = {}
    current_name = None
    current_is_file = False
    field_value = bytearray()
    file_bytes = 0
    ended = False

    def data_slice(data: bytes, start: int, end: int) -> bytes:
        return data[start:end]

    def on_part_begin() -> None:
        nonlocal headers, current_name, current_is_file, field_value
        headers = {}
        current_name = None
        current_is_file = False
        field_value = bytearray()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        header_field.extend(data_slice(data, start, end))
        if len(header_field) > MAX_IMPORT_HEADER_BYTES:
            raise ProjectImportInvalid("invalid project import multipart")

    def on_header_value(data: bytes, start: int, end: int) -> None:
        header_value.extend(data_slice(data, start, end))
        if len(header_value) > MAX_IMPORT_HEADER_BYTES:
            raise ProjectImportInvalid("invalid project import multipart")

    def on_header_end() -> None:
        headers[bytes(header_field).lower()] = bytes(header_value)
        header_field.clear()
        header_value.clear()

    def on_headers_finished() -> None:
        nonlocal opened, upload, owner, current_name, current_is_file
        disposition, parameters = parse_options_header(headers.get(b"content-disposition"))
        raw_name = parameters.get(b"name")
        if disposition != b"form-data" or raw_name is None:
            raise ProjectImportInvalid("invalid project import multipart")
        try:
            current_name = raw_name.decode("utf-8", errors="strict")
        except UnicodeError:
            raise ProjectImportInvalid("invalid project import multipart") from None
        if current_name not in expected or current_name in seen:
            raise ProjectImportInvalid("invalid project import multipart")
        seen.add(current_name)
        current_is_file = b"filename" in parameters
        if current_name == "file":
            if not current_is_file or opened is not None:
                raise ProjectImportInvalid("invalid project import multipart")
            owner = OwnedImportQuarantine.create(temp_parent=temp_parent)
            opened = owner.archive_path.open("w+b")
            upload = UploadFile(opened, filename="project-import.zip")
        elif current_is_file:
            raise ProjectImportInvalid("invalid project import multipart")

    def on_part_data(data: bytes, start: int, end: int) -> None:
        nonlocal file_bytes
        chunk = data_slice(data, start, end)
        if current_name == "file":
            file_bytes += len(chunk)
            if file_bytes > MAX_IMPORT_FILE_BYTES:
                raise ProjectImportTooLarge("project import archive exceeds configured limit")
            opened.write(chunk)
            return
        field_value.extend(chunk)
        if len(field_value) > MAX_IMPORT_FIELD_BYTES:
            raise ProjectImportTooLarge("project import form field exceeds configured limit")

    def on_part_end() -> None:
        if current_name != "file":
            try:
                fields[current_name] = bytes(field_value).decode("utf-8", errors="strict")
            except UnicodeError:
                raise ProjectImportInvalid("invalid project import multipart") from None

    def on_end() -> None:
        nonlocal ended
        ended = True

    callbacks = {
        "on_part_begin": on_part_begin,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
        "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished,
        "on_part_data": on_part_data,
        "on_part_end": on_part_end,
        "on_end": on_end,
    }
    parser = MultipartParser(boundary, callbacks)
    aggregate = 0
    try:
        async for chunk in request.stream():
            aggregate += len(chunk)
            if aggregate > MAX_IMPORT_FILE_BYTES + MAX_IMPORT_MULTIPART_OVERHEAD:
                raise ProjectImportTooLarge("project import multipart exceeds configured limit")
            parser.write(chunk)
        parser.finalize()
        if not ended or seen != expected or upload is None:
            raise ProjectImportInvalid("invalid project import multipart")
        opened.seek(0)
        return _OwnedMultipart(upload, fields, owner)
    except (asyncio.CancelledError, ClientDisconnect):
        await _close_partial(upload, opened, owner)
        raise
    except BaseException:
        await _close_partial(upload, opened, owner)
        raise


def _summary(value) -> dict[str, object]:
    return {
        "packageHash": value.package_hash,
        "manifestHash": value.manifest_hash,
        "packageVersion": value.package_version,
        "sourceTitle": value.source_title,
        "proposedTitle": value.proposed_title,
        "counts": dict(value.counts),
        "hasFinalizedChapters": value.has_finalized_chapters,
        "providerHistoryCount": value.provider_history_count,
    }


def _command(value: ProjectImportCommandView) -> dict[str, object]:
    return {
        "commandId": value.command_id,
        "status": value.status,
        "phase": value.phase,
        "retryRequired": value.retry_required,
        "targetProjectId": value.target_project_id,
        "publicErrorCode": value.public_error_code,
    }


def _mapped(error: Exception, *, get: bool = False) -> JSONResponse:
    if isinstance(error, ProjectImportTooLarge):
        return _error(413, "ProjectImportTooLarge", "Project import package is too large")
    if isinstance(error, ProjectImportSensitiveData):
        return _error(422, "ProjectImportSensitiveData", "Project import package contains unsupported sensitive data")
    if isinstance(error, ProjectImportInvalid):
        return _invalid_response()
    if isinstance(error, (ProjectImportCommandConflict, ProjectImportCommandStateConflict)):
        if get:
            return _error(404, "ProjectImportNotFound", "Project import command was not found")
        return _error(409, "ProjectImportConflict", "Project import command conflicts with current state")
    if isinstance(error, ProjectImportPersistenceError):
        return _error(500, "ProjectImportIntegrity", "Project import could not be completed")
    return _error(500, "ProjectImportIntegrity", "Project import could not be completed")


@router.post("/project-imports/preflight")
async def preflight_project_import(
    request: Request,
    service: Annotated[ProjectImportService, Depends(get_project_import_service)],
) -> JSONResponse:
    owned = None
    try:
        owned = await _stream_form(request, frozenset({"file"}))
        return _response(_summary(await service.preflight(owned.upload)))
    except (asyncio.CancelledError, ClientDisconnect):
        raise
    except Exception as error:
        return _mapped(error)
    finally:
        if owned is not None:
            await owned.close()


@router.post("/project-imports")
async def import_project(
    request: Request,
    service: Annotated[ProjectImportService, Depends(get_project_import_service)],
) -> JSONResponse:
    owned = None
    try:
        owned = await _stream_form(request, frozenset({
            "file", "commandId", "idempotencyKey", "expectedPackageHash", "newTitle",
        }))
        values = owned.fields
        command_id = _strict_uuid(values["commandId"])
        key = values["idempotencyKey"]
        expected_hash = values["expectedPackageHash"]
        title = values["newTitle"]
        if (
            command_id is None
            or _KEY.fullmatch(key) is None
            or _HASH.fullmatch(expected_hash) is None
            or title != title.strip()
            or not 1 <= len(title) <= 200
        ):
            return _invalid_response()
        import_request = ImportProjectRequest(command_id, key, expected_hash, title)
        return _response(_command(await service.import_project(owned.upload, import_request)))
    except (asyncio.CancelledError, ClientDisconnect):
        raise
    except Exception as error:
        return _mapped(error)
    finally:
        if owned is not None:
            await owned.close()


@router.get("/project-imports/{command_id}")
async def get_project_import(
    command_id: str,
    service: Annotated[ProjectImportService, Depends(get_project_import_service)],
) -> JSONResponse:
    strict_id = _strict_uuid(command_id)
    if strict_id is None:
        return _invalid_response()
    try:
        return _response(_command(await service.get_command(strict_id)))
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return _mapped(error, get=True)


__all__ = (
    "PROJECT_IMPORT_TEMP_PARENT", "get_project_import_service",
    "get_project_import", "import_project", "preflight_project_import", "router",
)
