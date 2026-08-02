from __future__ import annotations

import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.database import connection, transaction
from backend.http_errors import PublicDomainError
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.runtime.draft_operation_tasks import DraftOperationTaskRegistry
from backend.services.draft_operations import (
    DraftOperationConflict,
    DraftOperationIdempotencyConflict,
    DraftOperationNotFound,
    DraftOperationPreconditionFailed,
    DraftOperationRequestInvalid,
    DraftOperationResult,
    DraftOperationService,
    DraftOperationStorageError,
    DraftOperationUnexpectedProviderError,
    StartDraftOperation,
)
from backend.services.chapter_sessions import (
    ChapterSessionConflict,
    ChapterSessionNotFound,
    ChapterSessionPreconditionFailed,
    ChapterSessionRequestInvalid as ServiceRequestInvalid,
    ChapterSessionService,
    CreateChapterSession,
    SaveDraftCandidate,
    SaveWorkingDraft,
)


router = APIRouter(tags=["chapter-sessions"])
_service = ChapterSessionService(
    ChapterSessionRepository(), transaction_factory=transaction,
    connection_factory=connection,
)
_draft_operation_repository = ChapterSessionRepository()
draft_operation_task_registry = DraftOperationTaskRegistry()
_draft_operation_service = DraftOperationService(
    _draft_operation_repository,
    task_registry=draft_operation_task_registry,
    transaction_factory=transaction,
)
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SAFE_DRAFT_FAILURE_CODES = frozenset({
    "DraftProviderFailed", "DraftProviderResultInvalid",
})
_DRAFT_OPERATION_CREATE_BODY_MAX_BYTES = 12 * 1024
_DRAFT_OPERATION_CANCEL_BODY_MAX_BYTES = 1024
_DRAFT_OPERATION_EVENT_CURSOR_MAX = 2_147_483_647
_DRAFT_OPERATION_CONTENT_TYPE = re.compile(
    r'^[ \t]*application/json[ \t]*(?:;[ \t]*charset[ \t]*=[ \t]*(?:"utf-8"|utf-8)[ \t]*)?$',
    re.IGNORECASE,
)


def get_chapter_session_service() -> ChapterSessionService:
    return _service


def get_draft_operation_service() -> DraftOperationService:
    return _draft_operation_service


def get_draft_operation_repository() -> ChapterSessionRepository:
    return _draft_operation_repository


def get_draft_operation_transaction_factory():
    return transaction


class ChapterSessionRequestInvalid(PublicDomainError):
    status_code = 422
    code = "ChapterSessionRequestInvalid"
    message = "Chapter session request is invalid"


class ChapterSessionResourceNotFound(PublicDomainError):
    status_code = 404
    code = "ChapterSessionNotFound"
    message = "Chapter session or project was not found"


class ChapterSessionStateConflict(PublicDomainError):
    status_code = 409
    code = "ChapterSessionConflict"
    message = "Chapter session state changed; refresh and retry"


class ChapterSessionPreconditionUnavailable(PublicDomainError):
    status_code = 422
    code = "ChapterSessionPreconditionFailed"
    message = "Chapter session prerequisites are unavailable"


class DraftOperationUnavailable(PublicDomainError):
    status_code = 502
    code = "DraftOperationUnavailable"
    message = "Draft operation is temporarily unavailable"


class _StrictBody(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )


class CreateSessionBody(_StrictBody):
    chapterNumber: int = Field(ge=1)
    expectedPlanningRevision: int = Field(ge=1)
    expectedPlanningHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedOutlineRevision: int = Field(ge=1)
    expectedOutlineHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedCanonRevision: int = Field(ge=0)


class SaveWorkingDraftBody(_StrictBody):
    expectedRevision: int = Field(ge=1)
    expectedContentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(max_length=100_000)


class SaveCandidateBody(_StrictBody):
    expectedWorkingDraftRevision: int = Field(ge=1)
    expectedContentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotencyKey: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{12}$"
        ),
    )


class CreateDraftOperationBody(_StrictBody):
    operationType: Literal["generate_new"]
    expectedWorkingDraftRevision: int = Field(ge=1)
    expectedContentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotencyKey: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{12}$"
        ),
    )
    authorInstruction: str = Field(default="", max_length=2000)


def _raise_public(error: Exception):
    if isinstance(error, ChapterSessionNotFound):
        raise ChapterSessionResourceNotFound() from None
    if isinstance(error, ServiceRequestInvalid):
        raise ChapterSessionRequestInvalid() from None
    if isinstance(error, ChapterSessionConflict):
        raise ChapterSessionStateConflict() from None
    if isinstance(error, ChapterSessionPreconditionFailed):
        raise ChapterSessionPreconditionUnavailable() from None
    if isinstance(error, DraftOperationNotFound):
        raise error
    if isinstance(error, (DraftOperationConflict, DraftOperationIdempotencyConflict)):
        raise error
    if isinstance(error, DraftOperationPreconditionFailed):
        raise error
    if isinstance(error, DraftOperationRequestInvalid):
        raise error
    if isinstance(
        error,
        (DraftOperationStorageError, DraftOperationUnexpectedProviderError),
    ):
        raise DraftOperationUnavailable() from None
    raise error


def _canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _require_operation_identity(
    project_id: str,
    chapter_session_id: str,
    operation_id: str | None = None,
):
    if not _canonical_uuid(project_id) or not _canonical_uuid(chapter_session_id):
        raise DraftOperationNotFound()
    if operation_id is not None and not _canonical_uuid(operation_id):
        raise DraftOperationNotFound()


def _public_draft_operation(result: DraftOperationResult):
    return {
        "id": result.operation_id,
        "projectId": result.project_id,
        "chapterSessionId": result.chapter_session_id,
        "operationType": result.operation_type,
        "status": result.status,
        "lastEventSequence": result.last_event_sequence,
        "partialOutput": result.partial_output,
        "partialOutputHash": result.partial_output_hash,
        "partialOutputScalars": result.partial_output_scalars,
        "resultWorkingDraftRevision": result.result_working_draft_revision,
        "resultContentHash": result.result_content_hash,
        "failureCode": result.failure_code,
        "model": {
            "providerId": result.provider_id,
            "modelName": result.model_name,
        },
    }


def _require_closed_draft_operation(
    result: object,
    project_id: str,
    chapter_session_id: str,
    operation_id: str | None,
    error_type,
    expected_base_revision: int | None = None,
) -> DraftOperationResult:
    try:
        if not isinstance(result, DraftOperationResult):
            raise ValueError
        status = result.status
        result_revision = result.result_working_draft_revision
        result_hash = result.result_content_hash
        failure_code = result.failure_code
        partial = result.partial_output
        partial_hash = result.partial_output_hash
        partial_scalars = result.partial_output_scalars
        if (
            not _canonical_uuid(result.operation_id)
            or not _canonical_uuid(result.project_id)
            or not _canonical_uuid(result.chapter_session_id)
            or result.project_id != project_id
            or result.chapter_session_id != chapter_session_id
            or (
                operation_id is not None
                and result.operation_id != operation_id
            )
            or result.operation_type != "generate_new"
            or status not in {
                "starting", "running", "completed", "failed", "cancelled", "expired"
            }
            or isinstance(result.last_event_sequence, bool)
            or not isinstance(result.last_event_sequence, int)
            or not 1 <= result.last_event_sequence <= 2048
            or (
                status in {"starting", "running", "expired"}
                and result.last_event_sequence > 2047
            )
            or (
                status in {"completed", "failed", "cancelled"}
                and result.last_event_sequence < 2
            )
            or not isinstance(partial, str)
            or len(partial) > 100_000
            or not isinstance(partial_hash, str)
            or _HASH.fullmatch(partial_hash) is None
            or hashlib.sha256(partial.encode("utf-8")).hexdigest() != partial_hash
            or isinstance(partial_scalars, bool)
            or not isinstance(partial_scalars, int)
            or partial_scalars != len(partial)
            or not isinstance(result.provider_id, str)
            or not result.provider_id.strip()
            or not isinstance(result.model_name, str)
            or not result.model_name.strip()
        ):
            raise ValueError
        if status == "starting" and (
            result.last_event_sequence != 1 or partial or partial_scalars != 0
        ):
            raise ValueError
        if status == "running" and result.last_event_sequence == 1 and (
            partial or partial_scalars != 0
        ):
            raise ValueError
        result.provider_id.encode("utf-8")
        result.model_name.encode("utf-8")
        if status == "completed":
            if (
                isinstance(result_revision, bool)
                or not isinstance(result_revision, int)
                or result_revision < 1
                or (
                    expected_base_revision is not None
                    and result_revision != expected_base_revision + 1
                )
                or not isinstance(result_hash, str)
                or _HASH.fullmatch(result_hash) is None
                or failure_code is not None
                or not partial
                or partial != partial.strip()
                or result_hash != partial_hash
            ):
                raise ValueError
        elif status == "failed":
            if (
                result_revision is not None
                or result_hash is not None
                or failure_code not in _SAFE_DRAFT_FAILURE_CODES
            ):
                raise ValueError
        elif status == "cancelled":
            if (
                failure_code is not None
                or partial != partial.strip()
                or (bool(partial) != (result_revision is not None))
                or (result_revision is None) != (result_hash is None)
                or (
                    partial
                    and (
                        type(result_revision) is not int
                        or result_revision < 1
                        or (
                            expected_base_revision is not None
                            and result_revision != expected_base_revision + 1
                        )
                    )
                )
                or (result_hash is not None and result_hash != partial_hash)
            ):
                raise ValueError
        elif (
            result_revision is not None
            or result_hash is not None
            or failure_code is not None
        ):
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise error_type() from None


def _reject_duplicate_json_members(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_nonfinite_json_number(_value):
    raise ValueError


def _strict_json_object(raw: bytes | str):
    try:
        decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_json_members,
            parse_constant=_reject_nonfinite_json_number,
        )
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (
        AttributeError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
    ):
        raise ValueError from None


def _require_json_nesting_within_limit(value: str):
    depth = 0
    inside_string = False
    escaping = False
    for character in value:
        if inside_string:
            if escaping:
                escaping = False
            elif character == "\\":
                escaping = True
            elif character == '"':
                inside_string = False
            continue
        if character == '"':
            inside_string = True
        elif character in "{[":
            depth += 1
            if depth > 64:
                raise ValueError
        elif character in "}]":
            depth -= 1


def _has_draft_operation_json_content_type(request: Request) -> bool:
    values = [
        value
        for name, value in request.scope.get("headers", ())
        if name.lower() == b"content-type"
    ]
    if len(values) != 1:
        return False
    try:
        value = values[0].decode("ascii")
    except UnicodeDecodeError:
        return False
    return _DRAFT_OPERATION_CONTENT_TYPE.fullmatch(value) is not None


async def _read_draft_operation_create_body(request: Request):
    if not _has_draft_operation_json_content_type(request):
        raise DraftOperationRequestInvalid()
    try:
        chunks = []
        byte_count = 0
        async for chunk in request.stream():
            byte_count += len(chunk)
            if byte_count > _DRAFT_OPERATION_CREATE_BODY_MAX_BYTES:
                raise ValueError
            chunks.append(chunk)
        raw = b"".join(chunks)
        decoded = raw.decode("utf-8")
        _require_json_nesting_within_limit(decoded)
        return _strict_json_object(decoded)
    except ValueError:
        raise DraftOperationRequestInvalid() from None


async def _read_empty_cancel_body(request: Request) -> None:
    content_types = [
        value
        for name, value in request.scope.get("headers", ())
        if name.lower() == b"content-type"
    ]
    if len(content_types) > 1:
        raise DraftOperationRequestInvalid()
    try:
        chunks = []
        byte_count = 0
        async for chunk in request.stream():
            byte_count += len(chunk)
            if byte_count > _DRAFT_OPERATION_CANCEL_BODY_MAX_BYTES:
                raise ValueError
            chunks.append(chunk)
        raw = b"".join(chunks)
        if not content_types:
            if raw:
                raise ValueError
            return
        if not _has_draft_operation_json_content_type(request) or not raw:
            raise ValueError
        decoded = raw.decode("utf-8")
        _require_json_nesting_within_limit(decoded)
        if _strict_json_object(decoded) != {}:
            raise ValueError
    except (UnicodeDecodeError, ValueError):
        raise DraftOperationRequestInvalid() from None


def _public_draft_operation_events(
    rows: object,
    result: DraftOperationResult,
    project_id: str,
    operation_id: str,
    after_sequence: int,
):
    try:
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError
        expected_count = min(
            100,
            max(0, result.last_event_sequence - after_sequence),
        )
        if len(rows) < expected_count:
            raise ValueError
        for offset, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError
            sequence = row["sequence_num"]
            created_at = row["created_at"]
            if (
                not _canonical_uuid(row["id"])
                or row["project_id"] != project_id
                or row["draft_operation_id"] != operation_id
                or type(sequence) is not int
                or sequence != after_sequence + offset
                or type(created_at) is not int
                or created_at < 0
            ):
                raise ValueError
        rows = rows[:expected_count]
        expected_sequences = range(after_sequence + 1, after_sequence + 1 + len(rows))
        events = []
        known_partial = "" if after_sequence == 0 else None
        last_partial_scalars = None
        for expected_sequence, row in zip(expected_sequences, rows, strict=True):
            if not isinstance(row, dict):
                raise ValueError
            sequence = row["sequence_num"]
            event_type = row["event_type"]
            created_at = row["created_at"]
            if (
                not _canonical_uuid(row["id"])
                or row["project_id"] != project_id
                or row["draft_operation_id"] != operation_id
                or isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence != expected_sequence
                or isinstance(created_at, bool)
                or not isinstance(created_at, int)
                or created_at < 0
            ):
                raise ValueError
            payload = row["closed_payload_json"]
            event = {
                "sequence": sequence,
                "type": event_type,
                "createdAt": created_at,
            }
            if sequence > result.last_event_sequence:
                raise ValueError
            if (
                sequence == result.last_event_sequence
                and result.status in {"completed", "failed", "cancelled"}
                and event_type != result.status
            ):
                raise ValueError
            if sequence == 1:
                if event_type != "started" or payload is not None:
                    raise ValueError
            elif event_type == "delta":
                closed = _strict_json_object(payload)
                text = closed.get("text")
                output_hash = closed.get("partialOutputHash")
                scalars = closed.get("partialOutputScalars")
                if (
                    set(closed) != {"text", "partialOutputHash", "partialOutputScalars"}
                    or not isinstance(text, str)
                    or not text
                    or len(text) > 100_000
                    or not isinstance(output_hash, str)
                    or _HASH.fullmatch(output_hash) is None
                    or type(scalars) is not int
                    or not len(text) <= scalars <= 100_000
                    or (
                        last_partial_scalars is not None
                        and scalars != last_partial_scalars + len(text)
                    )
                ):
                    raise ValueError
                text.encode("utf-8")
                if known_partial is not None:
                    known_partial += text
                    if (
                        len(known_partial) != scalars
                        or hashlib.sha256(
                            known_partial.encode("utf-8")
                        ).hexdigest() != output_hash
                    ):
                        raise ValueError
                last_partial_scalars = scalars
                event.update(
                    text=text,
                    partialOutputHash=output_hash,
                    partialOutputScalars=scalars,
                )
            elif event_type == "heartbeat":
                if payload is not None:
                    raise ValueError
            elif event_type == "completed":
                if (
                    result.status != "completed"
                    or sequence != result.last_event_sequence
                ):
                    raise ValueError
                if _strict_json_object(payload) != {
                    "resultWorkingDraftRevision": (
                        result.result_working_draft_revision
                    ),
                    "resultContentHash": result.result_content_hash,
                }:
                    raise ValueError
                event["resultWorkingDraftRevision"] = (
                    result.result_working_draft_revision
                )
                event["resultContentHash"] = result.result_content_hash
            elif event_type == "failed":
                if (
                    result.status != "failed"
                    or sequence != result.last_event_sequence
                    or _strict_json_object(payload)
                    != {"failureCode": result.failure_code}
                ):
                    raise ValueError
                event["failureCode"] = result.failure_code
            elif event_type == "cancelled":
                if (
                    result.status != "cancelled"
                    or sequence != result.last_event_sequence
                    or _strict_json_object(payload) != {
                        "resultWorkingDraftRevision": (
                            result.result_working_draft_revision
                        ),
                        "resultContentHash": result.result_content_hash,
                    }
                ):
                    raise ValueError
                event["resultWorkingDraftRevision"] = (
                    result.result_working_draft_revision
                )
                event["resultContentHash"] = result.result_content_hash
            else:
                raise ValueError
            events.append(event)
        return events
    except (KeyError, TypeError, ValueError):
        raise DraftOperationNotFound() from None


def _public_workspace(workspace):
    active_draft_operation_id = workspace.active_draft_operation_id
    if (
        active_draft_operation_id is not None
        and not _canonical_uuid(active_draft_operation_id)
    ):
        raise ChapterSessionStateConflict()
    return {
        "projectId": workspace.project_id,
        "activeDraftOperationId": active_draft_operation_id,
        "session": {
            "id": workspace.session.id,
            "projectId": workspace.session.project_id,
            "planningRevisionId": workspace.session.planning_revision_id,
            "planningRevision": workspace.session.planning_revision,
            "planningHash": workspace.session.planning_hash,
            "storyBlockId": workspace.session.story_block_id,
            "storyBlockRevision": workspace.session.story_block_revision,
            "storyBlockHash": workspace.session.story_block_hash,
            "chapterOutlineRevisionId": (
                workspace.session.chapter_outline_revision_id
            ),
            "chapterOutlineRevision": (
                workspace.session.chapter_outline_revision
            ),
            "chapterOutlineHash": workspace.session.chapter_outline_hash,
            "chapterNum": workspace.session.chapter_num,
            "expectedCanonRevision": workspace.session.expected_canon_revision,
            "status": workspace.session.status,
        },
        "workingDraft": {
            "id": workspace.working_draft.id,
            "projectId": workspace.working_draft.project_id,
            "chapterSessionId": workspace.working_draft.chapter_session_id,
            "revision": workspace.working_draft.revision,
            "content": workspace.working_draft.content,
            "contentHash": workspace.working_draft.content_hash,
        },
        "candidates": [{
            "id": candidate.id,
            "projectId": candidate.project_id,
            "chapterSessionId": candidate.chapter_session_id,
            "workingDraftRevision": candidate.working_draft_revision,
            "content": candidate.content,
            "contentHash": candidate.content_hash,
            "outlineRevisionId": candidate.outline_revision_id,
            "outlineRevision": candidate.outline_revision,
            "outlineHash": candidate.outline_hash,
            "planningRevisionId": candidate.planning_revision_id,
            "planningRevision": candidate.planning_revision,
            "planningHash": candidate.planning_hash,
            "canonRevision": candidate.canon_revision,
            "projectionRevision": candidate.projection_revision,
            "projectionHash": candidate.projection_hash,
            "basisStatus": candidate.basis_status,
        } for candidate in workspace.candidates],
    }


@router.get("/projects/{pid}/chapter-sessions/{chapter_number}")
async def get_chapter_session(
    pid: str,
    chapter_number: int,
    service=Depends(get_chapter_session_service),
):
    try:
        workspace = await service.get(pid, chapter_number)
        return None if workspace is None else _public_workspace(workspace)
    except Exception as error:
        _raise_public(error)


@router.post(
    "/projects/{pid}/chapter-sessions/{chapter_number}",
    status_code=201,
)
async def create_chapter_session(
    pid: str,
    chapter_number: int,
    raw_body: object = Body(...),
    service=Depends(get_chapter_session_service),
):
    try:
        body = CreateSessionBody.model_validate(raw_body)
        if body.chapterNumber != chapter_number:
            raise ChapterSessionRequestInvalid()
        workspace = await service.create_session(CreateChapterSession(
            project_id=pid,
            chapter_number=body.chapterNumber,
            expected_planning_revision=body.expectedPlanningRevision,
            expected_planning_hash=body.expectedPlanningHash,
            expected_outline_revision=body.expectedOutlineRevision,
            expected_outline_hash=body.expectedOutlineHash,
            expected_canon_revision=body.expectedCanonRevision,
        ))
    except ValidationError:
        raise ChapterSessionRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    return _public_workspace(workspace)


@router.put("/projects/{pid}/chapter-sessions/{session_id}/working-draft")
async def save_working_draft(
    pid: str, session_id: str, raw_body: object = Body(...),
    service=Depends(get_chapter_session_service),
):
    try:
        body = SaveWorkingDraftBody.model_validate(raw_body)
        workspace = await service.save_working_draft(SaveWorkingDraft(
            project_id=pid,
            chapter_session_id=session_id,
            expected_revision=body.expectedRevision,
            expected_content_hash=body.expectedContentHash,
            content=body.content,
        ))
    except ValidationError:
        raise ChapterSessionRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    return _public_workspace(workspace)


@router.post("/projects/{pid}/chapter-sessions/{session_id}/draft-operations")
async def create_draft_operation(
    pid: str, session_id: str, request: Request,
    service=Depends(get_draft_operation_service),
):
    try:
        _require_operation_identity(pid, session_id)
        raw_body = await _read_draft_operation_create_body(request)
        body = CreateDraftOperationBody.model_validate(raw_body)
        result = await service.start(StartDraftOperation(
            project_id=pid,
            chapter_session_id=session_id,
            operation_type=body.operationType,
            expected_working_draft_revision=body.expectedWorkingDraftRevision,
            expected_content_hash=body.expectedContentHash,
            idempotency_key=body.idempotencyKey,
            author_instruction=body.authorInstruction,
        ))
    except ValidationError:
        raise DraftOperationRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    result = _require_closed_draft_operation(
        result,
        pid,
        session_id,
        None,
        DraftOperationUnavailable,
        body.expectedWorkingDraftRevision,
    )
    return _public_draft_operation(result)


@router.get(
    "/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}"
)
async def get_draft_operation(
    pid: str,
    session_id: str,
    operation_id: str,
    service=Depends(get_draft_operation_service),
):
    try:
        _require_operation_identity(pid, session_id, operation_id)
        result = await service.read(pid, session_id, operation_id)
        result = _require_closed_draft_operation(
            result, pid, session_id, operation_id, DraftOperationNotFound,
        )
        return _public_draft_operation(result)
    except Exception as error:
        _raise_public(error)


@router.get(
    "/projects/{pid}/chapter-sessions/{session_id}/draft-operations/"
    "{operation_id}/events"
)
async def list_draft_operation_events(
    pid: str,
    session_id: str,
    operation_id: str,
    after: str = Query("0"),
    service=Depends(get_draft_operation_service),
    repository=Depends(get_draft_operation_repository),
    transaction_factory=Depends(get_draft_operation_transaction_factory),
):
    try:
        _require_operation_identity(pid, session_id, operation_id)
        if (
            not re.fullmatch(r"(?:0|[1-9][0-9]*)", after)
            or len(after) > 10
        ):
            raise DraftOperationRequestInvalid()
        after_sequence = int(after)
        if after_sequence > _DRAFT_OPERATION_EVENT_CURSOR_MAX:
            raise DraftOperationRequestInvalid()
        result = await service.read(pid, session_id, operation_id)
        result = _require_closed_draft_operation(
            result, pid, session_id, operation_id, DraftOperationNotFound,
        )
        try:
            async with transaction_factory() as session:
                events = await repository.list_draft_operation_events(
                    session, operation_id, after_sequence, 100,
                )
        except DraftOperationStorageError:
            raise
        except Exception:
            raise DraftOperationStorageError(
                "draft operation event read failed"
            ) from None
        public_events = _public_draft_operation_events(
            events, result, pid, operation_id, after_sequence,
        )
        next_after = (
            public_events[-1]["sequence"] if public_events else after_sequence
        )
        return {
            "operationId": operation_id,
            "events": public_events,
            "lastEventSequence": result.last_event_sequence,
            "nextAfter": next_after,
            "hasMore": next_after < result.last_event_sequence,
        }
    except Exception as error:
        _raise_public(error)


@router.post(
    "/projects/{pid}/chapter-sessions/{session_id}/draft-operations/"
    "{operation_id}/cancel"
)
async def cancel_draft_operation(
    pid: str,
    session_id: str,
    operation_id: str,
    request: Request,
    service=Depends(get_draft_operation_service),
):
    try:
        _require_operation_identity(pid, session_id, operation_id)
        await _read_empty_cancel_body(request)
        result = await service.cancel(pid, session_id, operation_id)
        result = _require_closed_draft_operation(
            result, pid, session_id, operation_id, DraftOperationNotFound,
        )
        return _public_draft_operation(result)
    except Exception as error:
        _raise_public(error)


@router.post("/projects/{pid}/chapter-sessions/{session_id}/candidates", status_code=201)
async def save_candidate(
    pid: str, session_id: str, raw_body: object = Body(...),
    service=Depends(get_chapter_session_service),
):
    try:
        body = SaveCandidateBody.model_validate(raw_body)
        result = await service.save_candidate(SaveDraftCandidate(
            project_id=pid,
            chapter_session_id=session_id,
            expected_working_draft_revision=body.expectedWorkingDraftRevision,
            expected_content_hash=body.expectedContentHash,
            idempotency_key=body.idempotencyKey,
        ))
    except ValidationError:
        raise ChapterSessionRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    public_workspace = _public_workspace(result.workspace)
    public_workspace["savedCandidateId"] = result.saved_candidate_id
    return public_workspace
