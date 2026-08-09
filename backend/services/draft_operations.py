"""Persistent, idempotent and fenced chapter WorkingDraft generation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import time
from typing import Literal
from uuid import UUID, uuid4

from backend.domain.json_contracts import canonical_hash
from backend.gateways.chapter_draft_provider import (
    ChapterDraftProviderError,
    ChapterDraftProviderGateway,
)
from backend.http_errors import PublicDomainError
from backend.prompts.chapter_draft import build_chapter_draft_messages
from backend.runtime.draft_operation_tasks import DraftOperationTaskRegistry
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
    provider_public_value_contains_secret,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)
from backend.services.draft_operation_execution import (
    DRAFT_OPERATION_LEASE_MS,
    DraftOperationExecution,
    MAX_DRAFT_OPERATION_EVENTS,
)
from backend.services.draft_selection import (
    LOCAL_DRAFT_OPERATION_TYPES,
    replace_selection,
    selection_context,
    validate_selection,
)


DRAFT_OPERATION_AUTHOR_INSTRUCTION_MAX_LENGTH = 2_000
DRAFT_OPERATION_LOCAL_AUTHOR_INSTRUCTION_MAX_LENGTH = 1_000
DRAFT_OPERATION_CONTENT_MAX_SCALARS = 100_000
_EMPTY_OUTPUT_HASH = hashlib.sha256(b"").hexdigest()
_HASH = re.compile(r"^[0-9a-f]{64}$")
_FIXED_MESSAGE = "Draft operation state changed; refresh and retry"
_SESSION_IDENTITY_FIELDS = (
    "id",
    "project_id",
    "planning_revision_id",
    "planning_revision",
    "planning_hash",
    "story_block_id",
    "story_block_revision",
    "story_block_hash",
    "chapter_outline_revision_id",
    "chapter_outline_revision",
    "chapter_outline_hash",
    "chapter_num",
    "expected_canon_revision",
    "outline_canon_revision",
    "outline_projection_revision",
    "outline_projection_hash",
    "status",
)
_STATUSES = frozenset(
    {"starting", "running", "completed", "failed", "cancelled", "expired"}
)
_SAFE_FAILURE_CODES = frozenset({"DraftProviderFailed", "DraftProviderResultInvalid"})
_STORED_OPERATION_COLUMNS = frozenset({
    "id",
    "project_id",
    "chapter_session_id",
    "operation_type",
    "idempotency_key",
    "request_fingerprint",
    "active_slot",
    "fencing_token",
    "lease_expires_at",
    "base_working_draft_revision",
    "base_working_draft_hash",
    "input_manifest_json",
    "input_manifest_hash",
    "provider_id",
    "model_name_snapshot",
    "result_working_draft_revision",
    "result_content_hash",
    "last_event_sequence",
    "failure_code",
    "partial_output_text",
    "partial_output_hash",
    "partial_output_scalars",
    "heartbeat_at",
    "status",
    "created_at",
    "updated_at",
    "completed_at",
    "cancelled_at",
})


class DraftOperationRequestInvalid(PublicDomainError):
    status_code = 422
    code = "DraftOperationRequestInvalid"
    message = "Draft operation request is invalid"


class DraftOperationNotFound(PublicDomainError):
    status_code = 404
    code = "DraftOperationNotFound"
    message = "Draft operation or ChapterSession was not found"


class DraftOperationConflict(PublicDomainError):
    status_code = 409
    code = "DraftOperationConflict"
    message = _FIXED_MESSAGE


class DraftOperationIdempotencyConflict(DraftOperationConflict):
    code = "DraftOperationIdempotencyConflict"
    message = "Idempotency key was used for a different draft operation"


class DraftOperationPreconditionFailed(PublicDomainError):
    status_code = 422
    code = "DraftOperationPreconditionFailed"
    message = "Draft generation prerequisites are unavailable"


class DraftOperationStorageError(RuntimeError):
    """A coordination/storage write failed and its transaction must roll back."""


class DraftOperationUnexpectedProviderError(RuntimeError):
    """Unexpected internal Provider failure with no remote detail."""

    def __init__(self):
        super().__init__("Draft provider failed unexpectedly")


class _DraftOperationFenceLost(RuntimeError):
    """A persisted terminal/fence won while this in-process worker was active."""


class _DraftOperationResultInvalid(ValueError):
    """An intentional safe provider-result failure, never a storage exception."""


@dataclass(frozen=True)
class StartDraftOperation:
    project_id: str
    chapter_session_id: str
    operation_type: str
    expected_working_draft_revision: int
    expected_content_hash: str
    idempotency_key: str
    author_instruction: str = ""
    start_offset: int | None = None
    end_offset: int | None = None
    selected_text_hash: str | None = None


@dataclass(frozen=True)
class UndoLocalDraft:
    project_id: str
    chapter_session_id: str
    expected_working_draft_revision: int
    expected_content_hash: str
    source_operation_id: str


@dataclass(frozen=True)
class DraftOperationResult:
    operation_id: str
    project_id: str
    chapter_session_id: str
    operation_type: str
    status: Literal[
        "starting", "running", "completed", "failed", "cancelled", "expired"
    ]
    last_event_sequence: int
    result_working_draft_revision: int | None
    result_content_hash: str | None
    failure_code: str | None
    provider_id: str
    model_name: str
    partial_output: str
    partial_output_hash: str
    partial_output_scalars: int
    result_selection_start: int | None = None
    result_selection_end: int | None = None


class DraftOperationService:
    def __init__(
        self,
        repository,
        *,
        provider_gateway=None,
        task_registry=None,
        execution=None,
        transaction_factory,
        id_factory=None,
        clock=None,
    ):
        self.repository = repository
        self._gateway = provider_gateway or ChapterDraftProviderGateway()
        self._owns_registry = task_registry is None
        self._registry = task_registry or DraftOperationTaskRegistry()
        self._execution = execution or DraftOperationExecution(clock=clock)
        self._transaction = transaction_factory
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    @asynccontextmanager
    async def _storage_transaction(self):
        try:
            async with self._transaction() as session:
                yield session
        except (
            PublicDomainError,
            DraftOperationStorageError,
            _DraftOperationFenceLost,
            _DraftOperationResultInvalid,
        ):
            raise
        except Exception:
            raise DraftOperationStorageError(
                "draft operation storage transaction failed"
            ) from None

    @staticmethod
    def _canonical_uuid(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            return str(UUID(value)) == value
        except (ValueError, AttributeError, TypeError):
            return False

    @classmethod
    def validate(cls, command: StartDraftOperation) -> StartDraftOperation:
        try:
            instruction = command.author_instruction
            local = command.operation_type in LOCAL_DRAFT_OPERATION_TYPES
            instruction_limit = (
                DRAFT_OPERATION_LOCAL_AUTHOR_INSTRUCTION_MAX_LENGTH
                if local else DRAFT_OPERATION_AUTHOR_INSTRUCTION_MAX_LENGTH
            )
            if (
                not isinstance(command, StartDraftOperation)
                or not cls._canonical_uuid(command.project_id)
                or not cls._canonical_uuid(command.chapter_session_id)
                or command.operation_type not in (
                    LOCAL_DRAFT_OPERATION_TYPES | {"generate_new"}
                )
                or isinstance(command.expected_working_draft_revision, bool)
                or not isinstance(command.expected_working_draft_revision, int)
                or command.expected_working_draft_revision <= 0
                or not isinstance(command.expected_content_hash, str)
                or _HASH.fullmatch(command.expected_content_hash) is None
                or not cls._canonical_uuid(command.idempotency_key)
                or not isinstance(instruction, str)
                or len(instruction) > instruction_limit
                or (
                    local
                    and (
                        isinstance(command.start_offset, bool)
                        or not isinstance(command.start_offset, int)
                        or command.start_offset < 0
                        or isinstance(command.end_offset, bool)
                        or not isinstance(command.end_offset, int)
                        or command.end_offset <= command.start_offset
                        or not isinstance(command.selected_text_hash, str)
                        or _HASH.fullmatch(command.selected_text_hash) is None
                    )
                )
                or (
                    not local
                    and any(value is not None for value in (
                        command.start_offset,
                        command.end_offset,
                        command.selected_text_hash,
                    ))
                )
            ):
                raise ValueError
            instruction.encode("utf-8")
        except (AttributeError, TypeError, ValueError, UnicodeError):
            raise DraftOperationRequestInvalid() from None
        return StartDraftOperation(
            project_id=command.project_id,
            chapter_session_id=command.chapter_session_id,
            operation_type=command.operation_type,
            expected_working_draft_revision=command.expected_working_draft_revision,
            expected_content_hash=command.expected_content_hash,
            idempotency_key=command.idempotency_key,
            author_instruction=instruction.strip(),
            start_offset=command.start_offset,
            end_offset=command.end_offset,
            selected_text_hash=command.selected_text_hash,
        )

    async def start(self, command: StartDraftOperation) -> DraftOperationResult:
        command = self.validate(command)
        replay, context = await self._reserve(command)
        if replay is not None:
            return replay
        try:
            if self._owns_registry:
                await self._registry.start()
            self._registry.launch(
                context["attempt"]["id"],
                lambda cancellation: self._run_worker(context, cancellation),
            )
        except Exception:
            raise DraftOperationUnexpectedProviderError() from None
        return self._project_context_attempt(context)

    @classmethod
    def validate_undo(cls, command: UndoLocalDraft) -> UndoLocalDraft:
        try:
            if (
                not isinstance(command, UndoLocalDraft)
                or not cls._canonical_uuid(command.project_id)
                or not cls._canonical_uuid(command.chapter_session_id)
                or isinstance(command.expected_working_draft_revision, bool)
                or not isinstance(command.expected_working_draft_revision, int)
                or not 1 <= command.expected_working_draft_revision <= 2_147_483_646
                or not isinstance(command.expected_content_hash, str)
                or _HASH.fullmatch(command.expected_content_hash) is None
                or not cls._canonical_uuid(command.source_operation_id)
            ):
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            raise DraftOperationRequestInvalid() from None
        return command

    async def undo_local(self, command: UndoLocalDraft) -> int:
        command = self.validate_undo(command)
        async with self._storage_transaction() as session:
            project = await self.repository.lock_project(session, command.project_id)
            chapter = await self.repository.lock_session_for_operation(
                session, command.project_id, command.chapter_session_id,
            )
            draft = await self.repository.lock_working_draft_for_operation(
                session, command.project_id, command.chapter_session_id,
            )
            if project is None or chapter is None or draft is None:
                raise DraftOperationNotFound()
            if chapter.get("active_draft_operation_id") is not None:
                raise DraftOperationConflict()
            if (
                draft.get("revision") != command.expected_working_draft_revision
                or draft.get("content_hash") != command.expected_content_hash
            ):
                raise DraftOperationConflict()

            stored = await self.repository.read_draft_operation(
                session,
                command.project_id,
                command.chapter_session_id,
                command.source_operation_id,
            )
            if stored is None:
                raise DraftOperationNotFound()
            source = self.project_stored_result(stored)
            payload = draft.get("source_payload")
            expected_payload = {
                "source": "draft-operation",
                "operationId": source.operation_id,
                "operationType": source.operation_type,
                "providerId": source.provider_id,
                "modelName": source.model_name,
                "baseWorkingDraftRevision": stored["base_working_draft_revision"],
            }
            if (
                source.operation_type not in LOCAL_DRAFT_OPERATION_TYPES
                or source.status != "completed"
                or source.result_working_draft_revision != draft.get("revision")
                or source.result_content_hash != draft.get("content_hash")
                or payload != expected_payload
                or not isinstance(draft.get("content"), str)
            ):
                raise DraftOperationConflict()
            try:
                draft["content"].encode("utf-8")
            except UnicodeError:
                raise DraftOperationConflict() from None
            if (
                hashlib.sha256(draft["content"].encode("utf-8")).hexdigest()
                != draft["content_hash"]
            ):
                raise DraftOperationConflict()

            before = await self.repository.read_working_draft_recovery_for_operation(
                session,
                command.project_id,
                command.chapter_session_id,
                command.source_operation_id,
            )
            if not self._valid_undo_before(before, stored, draft):
                raise DraftOperationConflict()

            now = self._clock()
            current_snapshot = {
                "id": self._new_id(),
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "working_draft_id": draft["id"],
                "working_draft_revision": draft["revision"],
                "snapshot_role": "before",
                "replacement_reason": "undo_local",
                "source_operation_id": source.operation_id,
                "content": draft["content"],
                "content_hash": draft["content_hash"],
                "created_at": now,
            }
            if not await self.repository.insert_working_draft_revision(
                session, current_snapshot,
            ):
                raise DraftOperationStorageError("could not append undo snapshot")
            restored = {
                "id": draft["id"],
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "revision": draft["revision"] + 1,
                "content": before["content"],
                "content_hash": before["content_hash"],
                "source_payload": {
                    "source": "undo-local",
                    "sourceOperationId": source.operation_id,
                    "operationType": source.operation_type,
                    "baseWorkingDraftRevision": draft["revision"],
                },
                "updated_at": now,
            }
            if not await self.repository.upsert_working_draft(
                session,
                restored,
                expected_revision=draft["revision"],
                expected_content_hash=draft["content_hash"],
            ):
                raise DraftOperationStorageError("working draft undo CAS failed")
            chapter_number = chapter.get("chapter_num")
            if isinstance(chapter_number, bool) or not isinstance(chapter_number, int):
                raise DraftOperationStorageError("chapter identity is invalid")
            return chapter_number

    @staticmethod
    def _valid_undo_before(before, stored, draft) -> bool:
        try:
            content = before["content"]
            content_hash = before["content_hash"]
            content.encode("utf-8")
            return bool(
                isinstance(before, Mapping)
                and before["project_id"] == stored["project_id"]
                and before["chapter_session_id"] == stored["chapter_session_id"]
                and before["working_draft_id"] == draft["id"]
                and before["working_draft_revision"]
                == stored["base_working_draft_revision"]
                and before["snapshot_role"] == "before"
                and before["replacement_reason"] == stored["operation_type"]
                and before["source_operation_id"] == stored["id"]
                and isinstance(content, str)
                and len(content) <= DRAFT_OPERATION_CONTENT_MAX_SCALARS
                and isinstance(content_hash, str)
                and _HASH.fullmatch(content_hash) is not None
                and hashlib.sha256(content.encode("utf-8")).hexdigest()
                == content_hash
            )
        except (KeyError, TypeError, UnicodeError):
            return False

    @staticmethod
    def _validated_provider_content(context, generated, *, strip=True):
        content = validate_provider_response_text(generated, strip=strip)
        if len(content) > DRAFT_OPERATION_CONTENT_MAX_SCALARS:
            raise ValueError
        secrets = context["provider_secrets"]
        if (
            provider_response_text_contains_secret(content, secrets)
            or provider_response_value_contains_secret(content, secrets)
        ):
            raise ValueError
        return content

    @staticmethod
    def _validated_provider_partial(context, cumulative):
        if not isinstance(cumulative, str):
            raise ValueError
        try:
            cumulative.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError from None
        if len(cumulative) > DRAFT_OPERATION_CONTENT_MAX_SCALARS:
            raise ValueError
        secrets = context["provider_secrets"]
        if (
            (
                cumulative.strip()
                and provider_response_text_contains_secret(cumulative, secrets)
            )
            or provider_response_value_contains_secret(cumulative, secrets)
        ):
            raise ValueError
        return cumulative

    async def _run_worker(self, context, cancellation) -> None:
        del cancellation  # Task cancellation is authoritative; the signal is advisory.
        provider = dict(context["gateway_provider"])
        messages = [dict(message) for message in context["gateway_messages"]]
        config = dict(context["gateway_config"])

        async def on_delta(cumulative: str) -> None:
            validated = self._validated_provider_partial(context, cumulative)
            if validated != cumulative:
                raise ValueError
            await self._append_delta(context, cumulative)

        async def on_heartbeat() -> None:
            await self._append_heartbeat(context)

        async def on_complete(content: str) -> None:
            normalized = self._validated_provider_content(
                context,
                content,
                strip=context["command"].operation_type not in LOCAL_DRAFT_OPERATION_TYPES,
            )
            await self._settle_success(context, normalized)

        try:
            if context["stream_enabled"]:
                await self._execution.run_stream(
                    stream=self._gateway.stream(
                        provider=provider,
                        messages=messages,
                        generation_config=config,
                    ),
                    on_delta=on_delta,
                    on_heartbeat=on_heartbeat,
                    on_complete=on_complete,
                )
            else:
                await self._execution.run_non_stream(
                    generate=lambda: self._gateway.generate(
                        provider=provider,
                        messages=messages,
                        generation_config=config,
                    ),
                    on_heartbeat=on_heartbeat,
                    on_complete=on_complete,
                )
        except asyncio.CancelledError:
            raise
        except _DraftOperationFenceLost:
            return
        except DraftOperationStorageError:
            raise
        except ChapterDraftProviderError:
            await self._settle_failure(context, "DraftProviderFailed")
        except Exception:
            await self._settle_failure(context, "DraftProviderResultInvalid")

    @staticmethod
    def _project_context_attempt(context) -> DraftOperationResult:
        attempt = context["attempt"]
        return DraftOperationResult(
            operation_id=attempt["id"],
            project_id=attempt["project_id"],
            chapter_session_id=attempt["chapter_session_id"],
            operation_type=attempt["operation_type"],
            status="running",
            last_event_sequence=1,
            result_working_draft_revision=None,
            result_content_hash=None,
            failure_code=None,
            provider_id=attempt["provider_id"],
            model_name=attempt["model_name_snapshot"],
            partial_output="",
            partial_output_hash=_EMPTY_OUTPUT_HASH,
            partial_output_scalars=0,
        )

    async def _reserve(self, command):
        fingerprint = self._request_fingerprint(command)
        async with self._storage_transaction() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise DraftOperationNotFound()
            chapter_session = await self.repository.lock_session_for_operation(
                session, command.project_id, command.chapter_session_id
            )
            if chapter_session is None:
                raise DraftOperationNotFound()

            existing = await self.repository.read_draft_operation_by_key(
                session, command.chapter_session_id, command.idempotency_key
            )
            if existing is not None:
                if existing.get("request_fingerprint") != fingerprint:
                    raise DraftOperationIdempotencyConflict()
                now = self._clock()
                if (
                    existing.get("status") in {"starting", "running"}
                    and int(existing.get("lease_expires_at") or -1) <= now
                ):
                    if not await self.repository.expire_draft_operation(
                        session,
                        existing["id"],
                        int(existing["fencing_token"]),
                        now,
                    ):
                        raise DraftOperationStorageError(
                            "could not expire replayed operation"
                        )
                    return self._project_expired(existing, now), None
                return self.project_stored_result(existing), None

            if chapter_session.get("status") != "drafting":
                raise DraftOperationConflict()
            now = self._clock()
            active = await self.repository.read_active_draft_operation(
                session, command.chapter_session_id
            )
            if active is not None:
                if int(active["lease_expires_at"]) > now:
                    raise DraftOperationConflict()
                if not await self.repository.expire_draft_operation(
                    session,
                    active["id"],
                    int(active["fencing_token"]),
                    now,
                ):
                    raise DraftOperationStorageError("could not expire elapsed operation")

            draft = await self.repository.lock_working_draft_for_operation(
                session, command.project_id, command.chapter_session_id
            )
            if not self._draft_matches_command(draft, command):
                raise DraftOperationConflict()

            selection = None
            if command.operation_type in LOCAL_DRAFT_OPERATION_TYPES:
                try:
                    selection = validate_selection(
                        draft.get("content"),
                        command.start_offset,
                        command.end_offset,
                        command.selected_text_hash,
                    )
                except ValueError:
                    raise DraftOperationConflict() from None

            authority = await self._read_authority(session, chapter_session, draft)
            manifest = self._manifest(command, authority)
            manifest_hash = canonical_hash(manifest)
            provider_authority = authority["provider_authority"]
            fencing_token = await self.repository.next_draft_operation_fencing_token(
                session, command.project_id, command.chapter_session_id
            )
            if fencing_token is None:
                raise DraftOperationStorageError("could not allocate operation fence")
            operation_id = self._new_id()
            row = {
                "id": operation_id,
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "operation_type": command.operation_type,
                "idempotency_key": command.idempotency_key,
                "request_fingerprint": fingerprint,
                "active_slot": 1,
                "fencing_token": fencing_token,
                "lease_expires_at": now + DRAFT_OPERATION_LEASE_MS,
                "base_working_draft_revision": command.expected_working_draft_revision,
                "base_working_draft_hash": command.expected_content_hash,
                "input_manifest": manifest,
                "input_manifest_hash": manifest_hash,
                "provider_id": provider_authority["id"],
                "model_name_snapshot": provider_authority["model_name"],
                "result_working_draft_revision": None,
                "result_content_hash": None,
                "last_event_sequence": 0,
                "failure_code": None,
                "partial_output_text": "",
                "partial_output_hash": _EMPTY_OUTPUT_HASH,
                "partial_output_scalars": 0,
                "heartbeat_at": now,
                "status": "starting",
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "cancelled_at": None,
            }
            if not await self.repository.insert_draft_operation(session, row):
                raise DraftOperationStorageError("could not reserve draft operation")
            if not await self.repository.insert_draft_operation_event(
                session,
                self._event_row(
                    command.project_id, operation_id, 1, "started", None, now
                ),
            ):
                raise DraftOperationStorageError("could not append started event")
            if not await self.repository.mark_draft_operation_running(
                session, operation_id, fencing_token, now
            ):
                raise DraftOperationStorageError("could not mark draft operation running")

            prompt_session = dict(chapter_session)
            prompt_session["chapter_outline"] = authority["outline"]["content"]
            gateway_provider = {
                "id": provider_authority["id"],
                "provider_type": provider_authority["provider_type"],
                "model_name": provider_authority["model_name"],
                "base_url": provider_authority["base_url"],
                "api_key": provider_authority["api_key"],
            }
            gateway_messages = build_chapter_draft_messages(
                operation_type=command.operation_type,
                chapter_session=prompt_session,
                working_draft=draft,
                author_instruction=command.author_instruction,
                selection_context=(
                    selection_context(selection) if selection is not None else None
                ),
            )
            return None, {
                "command": command,
                "attempt": {
                    **row,
                    "status": "running",
                    "last_event_sequence": 1,
                },
                "manifest": manifest,
                "manifest_hash": manifest_hash,
                "authority": self._authority_snapshot(authority),
                "provider_authority_hash": canonical_hash(provider_authority),
                "provider_secrets": (
                    provider_authority["api_key"],
                    provider_authority["base_url"],
                ),
                "gateway_provider": gateway_provider,
                "gateway_config": self._generation_config(
                    authority["provider"]
                ),
                "gateway_messages": gateway_messages,
                "selection": selection,
                "stream_enabled": (
                    provider_authority["stream"]
                    and provider_authority["supports_streaming"]
                ),
            }

    async def _append_delta(self, context, cumulative: str) -> None:
        now = self._clock()
        output_hash = hashlib.sha256(cumulative.encode("utf-8")).hexdigest()
        async with self._storage_transaction() as session:
            if (
                await self.repository.lock_project(
                    session, context["command"].project_id
                )
                is None
                or await self.repository.lock_session_for_operation(
                    session,
                    context["command"].project_id,
                    context["command"].chapter_session_id,
                )
                is None
            ):
                raise _DraftOperationFenceLost()
            attempt = await self.repository.read_draft_operation(
                session,
                context["command"].project_id,
                context["command"].chapter_session_id,
                context["attempt"]["id"],
            )
            if not self._worker_owns(attempt, context, now):
                raise _DraftOperationFenceLost()
            sequence = int(attempt["last_event_sequence"]) + 1
            if sequence > MAX_DRAFT_OPERATION_EVENTS - 1:
                raise _DraftOperationResultInvalid(
                    "draft operation event budget exhausted"
                )
            previous_partial = attempt["partial_output_text"]
            if (
                not cumulative.startswith(previous_partial)
                or len(cumulative) <= len(previous_partial)
            ):
                raise _DraftOperationResultInvalid(
                    "draft operation partial is not append-only"
                )
            delta_text = cumulative[len(previous_partial):]
            row = {
                **self._stream_guard_row(context, attempt, sequence, now),
                "partial_output_text": cumulative,
                "partial_output_hash": output_hash,
                "partial_output_scalars": len(cumulative),
                "closed_payload": {
                    "text": delta_text,
                    "partialOutputHash": output_hash,
                    "partialOutputScalars": len(cumulative),
                },
            }
            if not await self.repository.append_draft_operation_delta(session, row):
                raise _DraftOperationFenceLost()
        context["attempt"].update(
            partial_output_text=cumulative,
            partial_output_hash=output_hash,
            partial_output_scalars=len(cumulative),
            heartbeat_at=now,
            lease_expires_at=now + DRAFT_OPERATION_LEASE_MS,
            updated_at=now,
            last_event_sequence=sequence,
        )

    async def _append_heartbeat(self, context) -> None:
        now = self._clock()
        async with self._storage_transaction() as session:
            if (
                await self.repository.lock_project(
                    session, context["command"].project_id
                )
                is None
                or await self.repository.lock_session_for_operation(
                    session,
                    context["command"].project_id,
                    context["command"].chapter_session_id,
                )
                is None
            ):
                raise _DraftOperationFenceLost()
            attempt = await self.repository.read_draft_operation(
                session,
                context["command"].project_id,
                context["command"].chapter_session_id,
                context["attempt"]["id"],
            )
            if not self._worker_owns(attempt, context, now):
                raise _DraftOperationFenceLost()
            sequence = int(attempt["last_event_sequence"]) + 1
            if sequence > MAX_DRAFT_OPERATION_EVENTS - 1:
                raise _DraftOperationResultInvalid(
                    "draft operation event budget exhausted"
                )
            row = self._stream_guard_row(context, attempt, sequence, now)
            if not await self.repository.append_draft_operation_heartbeat(
                session, row
            ):
                raise _DraftOperationFenceLost()
        context["attempt"].update(
            heartbeat_at=now,
            lease_expires_at=now + DRAFT_OPERATION_LEASE_MS,
            updated_at=now,
            last_event_sequence=sequence,
        )

    def _stream_guard_row(self, context, attempt, sequence, now):
        return {
            "id": self._new_id(),
            "project_id": context["command"].project_id,
            "chapter_session_id": context["command"].chapter_session_id,
            "draft_operation_id": context["attempt"]["id"],
            "fencing_token": int(context["attempt"]["fencing_token"]),
            "previous_partial_output_hash": attempt["partial_output_hash"],
            "previous_last_event_sequence": int(attempt["last_event_sequence"]),
            "sequence_num": sequence,
            "heartbeat_at": now,
            "lease_expires_at": now + DRAFT_OPERATION_LEASE_MS,
            "updated_at": now,
            "created_at": now,
            "closed_payload": None,
        }

    @staticmethod
    def _worker_owns(attempt, context, now):
        return bool(
            attempt
            and attempt.get("status") == "running"
            and attempt.get("active_slot") == 1
            and int(attempt.get("fencing_token") or -1)
            == int(context["attempt"]["fencing_token"])
            and int(attempt.get("lease_expires_at") or -1) > now
        )

    async def _settle_success(self, context, content):
        async with self._storage_transaction() as session:
            locked = await self._lock_settlement(session, context)
            terminal = await self._terminal_or_expire_drift(session, context, locked)
            if terminal is not None:
                return terminal
            attempt = locked["attempt"]
            draft = locked["draft"]

            local_operation = (
                context["command"].operation_type in LOCAL_DRAFT_OPERATION_TYPES
            )
            result_selection_start = None
            result_selection_end = None
            replacement = content
            if local_operation:
                try:
                    target = validate_selection(
                        draft["content"],
                        context["command"].start_offset,
                        context["command"].end_offset,
                        context["command"].selected_text_hash,
                    )
                    content, result_selection_start, result_selection_end = (
                        replace_selection(target, replacement)
                    )
                except ValueError:
                    raise _DraftOperationResultInvalid(
                        "local draft replacement is invalid"
                    ) from None
                if len(content) > DRAFT_OPERATION_CONTENT_MAX_SCALARS:
                    raise _DraftOperationResultInvalid(
                        "local draft replacement exceeds the draft limit"
                    )

            now = self._clock()
            sequence = int(attempt["last_event_sequence"]) + 1
            if sequence > MAX_DRAFT_OPERATION_EVENTS:
                raise _DraftOperationResultInvalid(
                    "draft operation event budget exhausted"
                )
            result_revision = int(draft["revision"]) + 1
            result_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            partial_output = replacement if local_operation else content
            partial_output_hash = hashlib.sha256(
                partial_output.encode("utf-8")
            ).hexdigest()
            before = self._recovery_row(
                context, draft, int(draft["revision"]), "before",
                draft["content"], draft["content_hash"], now,
            )
            after = self._recovery_row(
                context, draft, result_revision, "after", content, result_hash, now,
            )
            if not await self.repository.insert_working_draft_revision(session, before):
                raise DraftOperationStorageError("could not append before snapshot")
            row = {
                "id": draft["id"],
                "project_id": context["command"].project_id,
                "chapter_session_id": context["command"].chapter_session_id,
                "revision": result_revision,
                "content": content,
                "content_hash": result_hash,
                "source_payload": {
                    "source": "draft-operation",
                    "operationId": attempt["id"],
                    "operationType": context["command"].operation_type,
                    "providerId": attempt["provider_id"],
                    "modelName": attempt["model_name_snapshot"],
                    "baseWorkingDraftRevision": int(draft["revision"]),
                },
                "updated_at": now,
            }
            if not await self.repository.upsert_working_draft(
                session,
                row,
                expected_revision=int(draft["revision"]),
                expected_content_hash=draft["content_hash"],
            ):
                raise DraftOperationStorageError("working draft CAS failed")
            if not await self.repository.insert_working_draft_revision(session, after):
                raise DraftOperationStorageError("could not append after snapshot")
            if not await self.repository.insert_draft_operation_event(
                session,
                self._event_row(
                    context["command"].project_id,
                    attempt["id"],
                    sequence,
                    "completed",
                    {
                        "resultWorkingDraftRevision": result_revision,
                        "resultContentHash": result_hash,
                    },
                    now,
                ),
            ):
                raise DraftOperationStorageError("could not append completed event")
            if not await self.repository.complete_draft_operation(
                session,
                {
                    "id": attempt["id"],
                    "project_id": context["command"].project_id,
                    "chapter_session_id": context["command"].chapter_session_id,
                    "fencing_token": int(attempt["fencing_token"]),
                    "result_working_draft_revision": result_revision,
                    "result_content_hash": result_hash,
                    "partial_output_text": partial_output,
                    "partial_output_hash": partial_output_hash,
                    "partial_output_scalars": len(partial_output),
                    "previous_partial_output_hash": attempt["partial_output_hash"],
                    "previous_last_event_sequence": int(
                        attempt["last_event_sequence"]
                    ),
                    "sequence_num": sequence,
                    "updated_at": now,
                    "completed_at": now,
                },
            ):
                raise DraftOperationStorageError("could not complete draft operation")
            return DraftOperationResult(
                operation_id=attempt["id"],
                project_id=context["command"].project_id,
                chapter_session_id=context["command"].chapter_session_id,
                operation_type=context["command"].operation_type,
                status="completed",
                last_event_sequence=sequence,
                result_working_draft_revision=result_revision,
                result_content_hash=result_hash,
                failure_code=None,
                provider_id=attempt["provider_id"],
                model_name=attempt["model_name_snapshot"],
                partial_output=partial_output,
                partial_output_hash=partial_output_hash,
                partial_output_scalars=len(partial_output),
                result_selection_start=result_selection_start,
                result_selection_end=result_selection_end,
            )

    async def _settle_failure(self, context, code):
        async with self._storage_transaction() as session:
            locked = await self._lock_settlement(session, context)
            terminal = await self._terminal_or_expire_drift(session, context, locked)
            if terminal is not None:
                return terminal
            return await self._fail_locked(
                session, context, locked["attempt"], code
            )

    async def _fail_locked(self, session, context, attempt, code):
        now = self._clock()
        sequence = int(attempt["last_event_sequence"]) + 1
        if sequence > MAX_DRAFT_OPERATION_EVENTS:
            raise _DraftOperationFenceLost()
        if not await self.repository.insert_draft_operation_event(
            session,
            self._event_row(
                context["command"].project_id,
                attempt["id"],
                sequence,
                "failed",
                {"failureCode": code},
                now,
            ),
        ):
            raise DraftOperationStorageError("could not append failed event")
        if not await self.repository.fail_draft_operation(
            session,
            {
                "id": attempt["id"],
                "project_id": context["command"].project_id,
                "chapter_session_id": context["command"].chapter_session_id,
                "fencing_token": int(attempt["fencing_token"]),
                "failure_code": code,
                "previous_partial_output_hash": attempt["partial_output_hash"],
                "previous_last_event_sequence": int(
                    attempt["last_event_sequence"]
                ),
                "sequence_num": sequence,
                "updated_at": now,
                "completed_at": now,
            },
        ):
            raise DraftOperationStorageError("could not fail draft operation")
        return DraftOperationResult(
            operation_id=attempt["id"],
            project_id=context["command"].project_id,
            chapter_session_id=context["command"].chapter_session_id,
            operation_type=context["command"].operation_type,
            status="failed",
            last_event_sequence=sequence,
            result_working_draft_revision=None,
            result_content_hash=None,
            failure_code=code,
            provider_id=attempt["provider_id"],
            model_name=attempt["model_name_snapshot"],
            partial_output=attempt["partial_output_text"],
            partial_output_hash=attempt["partial_output_hash"],
            partial_output_scalars=int(attempt["partial_output_scalars"]),
        )

    async def _lock_settlement(self, session, context):
        command = context["command"]
        if await self.repository.lock_project(session, command.project_id) is None:
            raise DraftOperationNotFound()
        chapter_session = await self.repository.lock_session_for_operation(
            session, command.project_id, command.chapter_session_id
        )
        attempt = await self.repository.read_draft_operation(
            session, command.project_id, command.chapter_session_id,
            context["attempt"]["id"],
        )
        draft = await self.repository.lock_working_draft_for_operation(
            session, command.project_id, command.chapter_session_id
        )
        if chapter_session is None or attempt is None or draft is None:
            raise DraftOperationNotFound()
        return {
            "session": chapter_session,
            "attempt": attempt,
            "draft": draft,
        }

    async def _terminal_or_expire_drift(self, session, context, locked):
        attempt = locked["attempt"]
        if attempt.get("status") != "running":
            return self.project_stored_result(attempt)
        now = self._clock()
        if int(attempt["lease_expires_at"]) <= now:
            if not await self.repository.expire_draft_operation(
                session, attempt["id"], int(attempt["fencing_token"]), now
            ):
                raise DraftOperationStorageError("could not expire elapsed operation")
            return self._project_expired(attempt, now)

        owned = (
            locked["session"].get("active_draft_operation_id") == attempt["id"]
            and int(attempt["fencing_token"])
            == int(context["attempt"]["fencing_token"])
            and attempt.get("active_slot") == 1
        )
        if not owned:
            return self.project_stored_result(attempt)

        persisted_matches = (
            attempt.get("request_fingerprint")
            == context["attempt"]["request_fingerprint"]
            and attempt.get("input_manifest_hash") == context["manifest_hash"]
            and int(attempt.get("base_working_draft_revision") or -1)
            == context["command"].expected_working_draft_revision
            and attempt.get("base_working_draft_hash")
            == context["command"].expected_content_hash
            and attempt.get("provider_id") == context["attempt"]["provider_id"]
            and attempt.get("model_name_snapshot")
            == context["attempt"]["model_name_snapshot"]
        )
        authority = await self._read_authority(
            session, locked["session"], locked["draft"], strict=False
        )
        authority_matches = False
        if authority is not None:
            try:
                authority_matches = (
                    self._authority_snapshot(authority) == context["authority"]
                    and canonical_hash(authority["provider_authority"])
                    == context["provider_authority_hash"]
                    and canonical_hash(self._manifest(context["command"], authority))
                    == context["manifest_hash"]
                    and self._draft_matches_command(
                        locked["draft"], context["command"]
                    )
                )
            except (KeyError, TypeError, ValueError, UnicodeError, PublicDomainError):
                authority_matches = False
        if persisted_matches and authority_matches:
            return None
        if not await self.repository.expire_draft_operation_for_drift(
            session,
            context["command"].project_id,
            context["command"].chapter_session_id,
            attempt["id"],
            int(attempt["fencing_token"]),
            now,
        ):
            raise DraftOperationStorageError("could not expire drifted operation")
        return self._project_expired(attempt, now)

    async def read(
        self, project_id: str, session_id: str, operation_id: str
    ) -> DraftOperationResult:
        if not all(
            self._canonical_uuid(value)
            for value in (project_id, session_id, operation_id)
        ):
            raise DraftOperationNotFound()
        async with self._storage_transaction() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise DraftOperationNotFound()
            if await self.repository.lock_session_for_operation(
                session, project_id, session_id
            ) is None:
                raise DraftOperationNotFound()
            row = await self.repository.read_draft_operation(
                session, project_id, session_id, operation_id
            )
            if row is None:
                raise DraftOperationNotFound()
            projected = self.project_stored_result(row)
            now = self._clock()
            if (
                projected.status in {"starting", "running"}
                and int(row["lease_expires_at"]) <= now
            ):
                if not await self.repository.expire_draft_operation(
                    session, operation_id, int(row["fencing_token"]), now
                ):
                    raise DraftOperationStorageError(
                        "could not expire elapsed operation"
                    )
                return self._project_expired(row, now)
            return projected

    async def cancel(
        self, project_id: str, session_id: str, operation_id: str
    ) -> DraftOperationResult:
        if not all(
            self._canonical_uuid(value)
            for value in (project_id, session_id, operation_id)
        ):
            raise DraftOperationNotFound()
        cancelled = False
        try:
            async with self._storage_transaction() as session:
                if await self.repository.lock_project(session, project_id) is None:
                    raise DraftOperationNotFound()
                chapter_session = await self.repository.lock_session_for_operation(
                    session, project_id, session_id
                )
                attempt = await self.repository.read_draft_operation(
                    session, project_id, session_id, operation_id
                )
                if chapter_session is None or attempt is None:
                    raise DraftOperationNotFound()
                projected = self.project_stored_result(attempt)
                if projected.status not in {"starting", "running"}:
                    return projected
                now = self._clock()
                if int(attempt["lease_expires_at"]) <= now:
                    if not await self.repository.expire_draft_operation(
                        session, operation_id, int(attempt["fencing_token"]), now
                    ):
                        raise _DraftOperationFenceLost()
                    return self._project_expired(attempt, now)
                if attempt["status"] != "running":
                    raise _DraftOperationFenceLost()

                persisted = attempt["partial_output_text"]
                normalized = persisted.strip()
                if normalized:
                    normalized = validate_provider_response_text(
                        persisted, strip=True
                    )
                partial_hash = (
                    hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    if normalized
                    else None
                )
                local_operation = attempt["operation_type"] in LOCAL_DRAFT_OPERATION_TYPES
                result_hash = None if local_operation else partial_hash
                sequence = int(attempt["last_event_sequence"]) + 1
                if sequence > MAX_DRAFT_OPERATION_EVENTS:
                    raise DraftOperationStorageError(
                        "draft operation event budget is invalid"
                    )
                row = {
                    **self._stream_guard_row(context={
                        "command": StartDraftOperation(
                            project_id=project_id,
                            chapter_session_id=session_id,
                            operation_type=attempt["operation_type"],
                            expected_working_draft_revision=int(
                                attempt["base_working_draft_revision"]
                            ),
                            expected_content_hash=attempt[
                                "base_working_draft_hash"
                            ],
                            idempotency_key=attempt["idempotency_key"],
                        ),
                        "attempt": attempt,
                    }, attempt=attempt, sequence=sequence, now=now),
                    "cancelled_at": now,
                    "completed_at": now,
                    "result_working_draft_revision": None,
                    "result_content_hash": result_hash,
                    "partial_output_text": normalized,
                    "partial_output_hash": (
                        partial_hash if partial_hash is not None else _EMPTY_OUTPUT_HASH
                    ),
                    "partial_output_scalars": len(normalized),
                    "closed_payload": {
                        "resultWorkingDraftRevision": None,
                        "resultContentHash": result_hash,
                    },
                }
                if normalized and not local_operation:
                    draft = await self.repository.lock_working_draft_for_operation(
                        session, project_id, session_id
                    )
                    if draft is None:
                        raise DraftOperationNotFound()
                    base_revision = int(attempt["base_working_draft_revision"])
                    base_hash = attempt["base_working_draft_hash"]
                    if (
                        int(draft.get("revision") or -1) != base_revision
                        or draft.get("content_hash") != base_hash
                    ):
                        raise DraftOperationConflict()
                    result_revision = base_revision + 1
                    row.update(
                        result_working_draft_revision=result_revision,
                        expected_working_draft_revision=base_revision,
                        expected_working_draft_hash=base_hash,
                        working_draft=self._working_draft_row(
                            attempt, draft, normalized, result_hash, now
                        ),
                        before_revision=self._recovery_row_for_attempt(
                            attempt,
                            draft,
                            int(draft["revision"]),
                            "before",
                            draft["content"],
                            draft["content_hash"],
                            now,
                        ),
                        after_revision=self._recovery_row_for_attempt(
                            attempt,
                            draft,
                            result_revision,
                            "after",
                            normalized,
                            result_hash,
                            now,
                        ),
                    )
                    row["closed_payload"][
                        "resultWorkingDraftRevision"
                    ] = result_revision
                if not await self.repository.cancel_draft_operation(session, row):
                    raise _DraftOperationFenceLost()
                cancelled = True
        except _DraftOperationFenceLost:
            winner = await self.read(project_id, session_id, operation_id)
            if winner.status in {"starting", "running"}:
                raise DraftOperationStorageError(
                    "could not cancel draft operation"
                )
            return winner
        if cancelled:
            self._registry.cancel(operation_id)
        return await self.read(project_id, session_id, operation_id)

    @staticmethod
    def _working_draft_row(attempt, draft, content, content_hash, now):
        return {
            "id": draft["id"],
            "project_id": attempt["project_id"],
            "chapter_session_id": attempt["chapter_session_id"],
            "revision": int(draft["revision"]) + 1,
            "content": content,
            "content_hash": content_hash,
            "source_payload": {
                "source": "draft-operation",
                "operationId": attempt["id"],
                "operationType": attempt["operation_type"],
                "providerId": attempt["provider_id"],
                "modelName": attempt["model_name_snapshot"],
                "baseWorkingDraftRevision": int(draft["revision"]),
            },
            "updated_at": now,
        }

    def _recovery_row_for_attempt(
        self, attempt, draft, revision, role, content, content_hash, now
    ):
        return {
            "id": self._new_id(),
            "project_id": attempt["project_id"],
            "chapter_session_id": attempt["chapter_session_id"],
            "working_draft_id": draft["id"],
            "working_draft_revision": revision,
            "snapshot_role": role,
            "replacement_reason": attempt["operation_type"],
            "source_operation_id": attempt["id"],
            "content": content,
            "content_hash": content_hash,
            "created_at": now,
        }

    async def _read_authority(self, session, chapter_session, draft, *, strict=True):
        try:
            authoritative_session = await self.repository.read_session_by_id(
                session,
                chapter_session["project_id"],
                chapter_session["id"],
            )
            if authoritative_session is None:
                raise ValueError
            outline = await self.repository.read_current_outline(
                session,
                authoritative_session["project_id"],
                int(authoritative_session["chapter_num"]),
            )
            projection = await self.repository.read_projection_head(
                session, authoritative_session["project_id"]
            )
            provider = await self.repository.resolve_writing_provider(
                session, authoritative_session["project_id"]
            )
            provider_row = dict(provider)
            authority = {
                "session": dict(authoritative_session),
                "outline": self._outline_snapshot(outline),
                "projection": self._projection_snapshot(projection),
                "draft": self._draft_snapshot(draft),
                "provider": provider_row,
                "provider_authority": self._normalize_provider_authority(
                    provider_row
                ),
            }
            self._validate_authority(authority)
            return authority
        except (KeyError, TypeError, ValueError, UnicodeError):
            if not strict:
                return None
            raise DraftOperationPreconditionFailed() from None

    @classmethod
    def _validate_authority(cls, authority):
        session = authority["session"]
        outline = authority["outline"]
        projection = authority["projection"]
        provider = authority["provider_authority"]
        if session["status"] != "drafting":
            raise ValueError
        if (
            projection["canonRevision"] != projection["projectionRevision"]
            or outline["canonRevision"] != projection["canonRevision"]
            or outline["projectionRevision"] != projection["projectionRevision"]
            or outline["projectionHash"] != projection["contentHash"]
            or outline["planningBaseline"] != outline["currentBaseline"]
        ):
            raise ValueError
        secrets = normalize_provider_secrets((provider["api_key"], provider["base_url"]))
        public_model = {
            "providerId": provider["id"], "modelName": provider["model_name"]
        }
        if provider_public_fields_contain_secret(public_model, secrets):
            raise ValueError

    @staticmethod
    def _outline_snapshot(outline):
        if outline is None:
            raise ValueError
        planning_baseline = {
            "selectionRevision": DraftOperationService._positive_int(
                outline["planning_selection_revision"]
            ),
            "seedId": DraftOperationService._nonblank(outline["planning_seed_id"]),
            "seedRevisionId": DraftOperationService._nonblank(
                outline["planning_seed_revision_id"]
            ),
            "seedHash": DraftOperationService._hash(outline["planning_seed_hash"]),
            "contractRevision": DraftOperationService._positive_int(
                outline["planning_contract_revision"]
            ),
            "creationContractId": DraftOperationService._nonblank(
                outline["planning_creation_contract_id"]
            ),
            "creationHash": DraftOperationService._hash(
                outline["planning_creation_hash"]
            ),
            "styleContractId": DraftOperationService._nonblank(
                outline["planning_style_contract_id"]
            ),
            "styleHash": DraftOperationService._hash(outline["planning_style_hash"]),
            "bibleRevision": DraftOperationService._positive_int(
                outline["planning_bible_revision"]
            ),
            "bibleRevisionId": DraftOperationService._nonblank(
                outline["planning_bible_revision_id"]
            ),
            "bibleHash": DraftOperationService._hash(outline["planning_bible_hash"]),
        }
        current_baseline = {
            "selectionRevision": DraftOperationService._positive_int(
                outline["current_selection_revision"]
            ),
            "seedId": DraftOperationService._nonblank(outline["current_seed_id"]),
            "seedRevisionId": DraftOperationService._nonblank(
                outline["current_seed_revision_id"]
            ),
            "seedHash": DraftOperationService._hash(outline["current_seed_hash"]),
            "contractRevision": DraftOperationService._positive_int(
                outline["current_contract_revision"]
            ),
            "creationContractId": DraftOperationService._nonblank(
                outline["current_creation_contract_id"]
            ),
            "creationHash": DraftOperationService._hash(outline["current_creation_hash"]),
            "styleContractId": DraftOperationService._nonblank(
                outline["current_style_contract_id"]
            ),
            "styleHash": DraftOperationService._hash(outline["current_style_hash"]),
            "bibleRevision": DraftOperationService._positive_int(
                outline["current_bible_revision"]
            ),
            "bibleRevisionId": DraftOperationService._nonblank(
                outline["current_bible_revision_id"]
            ),
            "bibleHash": DraftOperationService._hash(outline["current_bible_hash"]),
        }
        content = outline["chapter_outline"]
        if not isinstance(content, Mapping):
            raise ValueError
        return {
            "revisionId": DraftOperationService._nonblank(
                outline["chapter_outline_revision_id"]
            ),
            "revision": DraftOperationService._positive_int(
                outline["chapter_outline_revision"]
            ),
            "contentHash": DraftOperationService._hash(
                outline["chapter_outline_hash"]
            ),
            "planningRevisionId": DraftOperationService._nonblank(
                outline["planning_revision_id"]
            ),
            "planningRevision": DraftOperationService._positive_int(
                outline["planning_revision"]
            ),
            "planningHash": DraftOperationService._hash(outline["planning_hash"]),
            "currentPlanning": {
                "revisionId": DraftOperationService._nonblank(
                    outline["current_planning_revision_id"]
                ),
                "revision": DraftOperationService._positive_int(
                    outline["current_planning_revision"]
                ),
                "contentHash": DraftOperationService._hash(
                    outline["current_planning_hash"]
                ),
            },
            "planningBaseline": planning_baseline,
            "currentBaseline": current_baseline,
            "storyBlock": {
                "id": DraftOperationService._nonblank(outline["story_block_id"]),
                "revision": DraftOperationService._positive_int(
                    outline["story_block_revision"]
                ),
                "contentHash": DraftOperationService._hash(
                    outline["story_block_hash"]
                ),
            },
            "canonRevision": DraftOperationService._nonnegative_int(
                outline["canon_revision"]
            ),
            "projectionRevision": DraftOperationService._nonnegative_int(
                outline["projection_revision"]
            ),
            "projectionHash": DraftOperationService._hash(outline["projection_hash"]),
            "content": dict(content),
        }

    @staticmethod
    def _projection_snapshot(projection):
        if projection is None:
            raise ValueError
        return {
            "canonRevision": DraftOperationService._nonnegative_int(
                projection["canon_revision_number"]
            ),
            "projectionRevision": DraftOperationService._nonnegative_int(
                projection["projection_revision_number"]
            ),
            "contentHash": DraftOperationService._hash(projection["content_hash"]),
        }

    @staticmethod
    def _draft_snapshot(draft):
        if draft is None:
            raise ValueError
        return {
            "id": DraftOperationService._nonblank(draft["id"]),
            "revision": DraftOperationService._positive_int(draft["revision"]),
            "contentHash": DraftOperationService._hash(draft["content_hash"]),
        }

    @classmethod
    def _authority_snapshot(cls, authority):
        provider = authority["provider_authority"]
        return {
            "session": {
                key: authority["session"].get(key)
                for key in _SESSION_IDENTITY_FIELDS
            },
            "outline": authority["outline"],
            "projection": authority["projection"],
            "draft": authority["draft"],
            "binding": {
                "revisionId": provider["binding_revision_id"],
                "revision": provider["binding_revision"],
                "contentHash": provider["binding_hash"],
                "itemHash": provider["binding_item_hash"],
            },
            "model": {
                "providerId": provider["id"],
                "modelName": provider["model_name"],
                "stream": provider["stream"],
                "supportsStreaming": provider["supports_streaming"],
            },
        }

    @classmethod
    def _manifest(cls, command, authority):
        manifest = {
            "schemaVersion": 1,
            "operationType": command.operation_type,
            **cls._authority_snapshot(authority),
            "authorInstruction": command.author_instruction,
        }
        if command.operation_type in LOCAL_DRAFT_OPERATION_TYPES:
            manifest["selection"] = {
                "startOffset": command.start_offset,
                "endOffset": command.end_offset,
                "selectedTextHash": command.selected_text_hash,
            }
        secrets = normalize_provider_secrets(
            (authority["provider"].get("api_key"), authority["provider"].get("base_url"))
        )
        if provider_public_value_contains_secret(manifest, secrets):
            raise DraftOperationPreconditionFailed()
        return manifest

    @staticmethod
    def _request_fingerprint(command):
        fingerprint = {
            "projectId": command.project_id,
            "chapterSessionId": command.chapter_session_id,
            "operationType": command.operation_type,
            "baseWorkingDraftRevision": command.expected_working_draft_revision,
            "baseWorkingDraftHash": command.expected_content_hash,
            "authorInstruction": command.author_instruction,
        }
        if command.operation_type in LOCAL_DRAFT_OPERATION_TYPES:
            fingerprint["selection"] = {
                "startOffset": command.start_offset,
                "endOffset": command.end_offset,
                "selectedTextHash": command.selected_text_hash,
            }
        return canonical_hash(fingerprint)

    @staticmethod
    def _draft_matches_command(draft, command):
        return (
            draft is not None
            and draft.get("project_id") == command.project_id
            and draft.get("chapter_session_id") == command.chapter_session_id
            and int(draft.get("revision") or -1)
            == command.expected_working_draft_revision
            and draft.get("content_hash") == command.expected_content_hash
        )

    @classmethod
    def _normalize_provider_authority(cls, provider):
        if not isinstance(provider, Mapping):
            raise ValueError
        temperature_value = provider["temperature"]
        if temperature_value is None:
            temperature = Decimal("0.82")
        elif isinstance(temperature_value, bool) or not isinstance(
            temperature_value, (Decimal, int, float)
        ):
            raise ValueError
        else:
            try:
                temperature = Decimal(str(temperature_value))
            except (InvalidOperation, ValueError, TypeError):
                raise ValueError from None
        if not temperature.is_finite() or temperature < 0:
            raise ValueError
        if temperature == 0:
            temperature_text = "0"
        else:
            temperature_text = format(temperature.normalize(), "f")
        max_output_tokens = provider["max_output_tokens"]
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens <= 0
        ):
            raise ValueError
        stream = cls._provider_boolean(provider["stream"])
        supports_streaming = cls._provider_boolean(provider["supports_streaming"])
        normalized = {
            "binding_revision_id": cls._nonblank(provider["binding_revision_id"]),
            "binding_revision": cls._positive_int(provider["binding_revision"]),
            "binding_hash": cls._hash(provider["binding_hash"]),
            "binding_item_hash": cls._hash(provider["binding_item_hash"]),
            "id": cls._nonblank(provider["id"]),
            "provider_type": cls._nonblank(provider["provider_type"]),
            "model_name": cls._nonblank(provider["model_name"]),
            "base_url": cls._nonblank(provider["base_url"]),
            "api_key": cls._nonblank(provider["api_key"]),
            "temperature": temperature_text,
            "max_output_tokens": max_output_tokens,
            "stream": stream,
            "supports_streaming": supports_streaming,
        }
        if normalized["provider_type"] != "openai-compatible":
            raise ValueError
        canonical_hash(normalized)
        return normalized

    @staticmethod
    def _provider_boolean(value):
        if type(value) is bool:
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise ValueError

    @classmethod
    def _generation_config(cls, provider):
        authority = cls._normalize_provider_authority(provider)
        return {
            "temperature": float(Decimal(authority["temperature"])),
            "maxOutputTokens": authority["max_output_tokens"],
        }

    @staticmethod
    def _nonblank(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError
        value.encode("utf-8")
        return value.strip()

    @staticmethod
    def _hash(value):
        if not isinstance(value, str) or _HASH.fullmatch(value) is None:
            raise ValueError
        return value

    @staticmethod
    def _positive_int(value):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError
        return value

    @staticmethod
    def _nonnegative_int(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError
        return value

    def _new_id(self):
        value = self._id()
        if not self._canonical_uuid(value):
            raise DraftOperationStorageError("generated identity is invalid")
        return value

    def _event_row(self, project_id, operation_id, sequence, event_type, payload, now):
        return {
            "id": self._new_id(),
            "project_id": project_id,
            "draft_operation_id": operation_id,
            "sequence_num": sequence,
            "event_type": event_type,
            "closed_payload": payload,
            "created_at": now,
        }

    def _recovery_row(self, context, draft, revision, role, content, content_hash, now):
        return {
            "id": self._new_id(),
            "project_id": context["command"].project_id,
            "chapter_session_id": context["command"].chapter_session_id,
            "working_draft_id": draft["id"],
            "working_draft_revision": revision,
            "snapshot_role": role,
            "replacement_reason": context["command"].operation_type,
            "source_operation_id": context["attempt"]["id"],
            "content": content,
            "content_hash": content_hash,
            "created_at": now,
        }

    @staticmethod
    def _project_expired(attempt, completed_at):
        DraftOperationService.project_stored_result(attempt)
        return DraftOperationService.project_stored_result({
            **attempt,
            "status": "expired",
            "active_slot": None,
            "result_working_draft_revision": None,
            "result_content_hash": None,
            "failure_code": None,
            "updated_at": completed_at,
            "completed_at": completed_at,
            "cancelled_at": None,
        })

    @staticmethod
    def project_stored_result(row) -> DraftOperationResult:
        try:
            if not isinstance(row, Mapping):
                raise ValueError
            if not _STORED_OPERATION_COLUMNS.issubset(row.keys()):
                raise ValueError
            status = row["status"]
            operation_type = row["operation_type"]
            idempotency_key = row["idempotency_key"]
            request_fingerprint = row["request_fingerprint"]
            last_event_sequence = row["last_event_sequence"]
            fencing_token = row["fencing_token"]
            lease_expires_at = row["lease_expires_at"]
            base_revision = row["base_working_draft_revision"]
            base_hash = row["base_working_draft_hash"]
            manifest_json = row["input_manifest_json"]
            manifest_hash = row["input_manifest_hash"]
            result_revision = row["result_working_draft_revision"]
            result_hash = row["result_content_hash"]
            failure_code = row["failure_code"]
            partial_output = row["partial_output_text"]
            partial_output_hash = row["partial_output_hash"]
            partial_output_scalars = row["partial_output_scalars"]
            heartbeat_at = row["heartbeat_at"]
            active_slot = row["active_slot"]
            created_at = row["created_at"]
            updated_at = row["updated_at"]
            completed_at = row["completed_at"]
            cancelled_at = row["cancelled_at"]
            provider_id = row["provider_id"]
            model_name = row["model_name_snapshot"]
            required_integers = (
                fencing_token,
                lease_expires_at,
                base_revision,
                last_event_sequence,
                created_at,
                updated_at,
                heartbeat_at,
                partial_output_scalars,
            )
            if any(type(value) is not int for value in required_integers):
                raise ValueError
            if result_revision is not None and type(result_revision) is not int:
                raise ValueError
            if completed_at is not None and type(completed_at) is not int:
                raise ValueError
            if cancelled_at is not None and type(cancelled_at) is not int:
                raise ValueError
            if (
                fencing_token <= 0
                or base_revision <= 0
                or created_at < 0
                or updated_at < created_at
                or lease_expires_at < created_at
                or heartbeat_at < created_at
                or partial_output_scalars < 0
                or lease_expires_at != heartbeat_at + DRAFT_OPERATION_LEASE_MS
            ):
                raise ValueError
            if not isinstance(partial_output, str):
                raise ValueError
            partial_output.encode("utf-8")
            if (
                len(partial_output) != partial_output_scalars
                or partial_output_scalars > DRAFT_OPERATION_CONTENT_MAX_SCALARS
                or hashlib.sha256(partial_output.encode("utf-8")).hexdigest()
                != partial_output_hash
            ):
                raise ValueError
            DraftOperationService._hash(partial_output_hash)
            if not isinstance(manifest_json, str):
                raise ValueError
            manifest = json.loads(manifest_json)
            if not isinstance(manifest, dict):
                raise ValueError
            if canonical_hash(manifest) != manifest_hash:
                raise ValueError
            model = manifest.get("model")
            selection_manifest = manifest.get("selection")
            if operation_type in LOCAL_DRAFT_OPERATION_TYPES:
                if (
                    not isinstance(selection_manifest, Mapping)
                    or set(selection_manifest) != {
                        "startOffset", "endOffset", "selectedTextHash",
                    }
                    or isinstance(selection_manifest.get("startOffset"), bool)
                    or not isinstance(selection_manifest.get("startOffset"), int)
                    or selection_manifest["startOffset"] < 0
                    or isinstance(selection_manifest.get("endOffset"), bool)
                    or not isinstance(selection_manifest.get("endOffset"), int)
                    or selection_manifest["endOffset"]
                    <= selection_manifest["startOffset"]
                    or not isinstance(selection_manifest.get("selectedTextHash"), str)
                    or _HASH.fullmatch(selection_manifest["selectedTextHash"]) is None
                ):
                    raise ValueError
            elif "selection" in manifest:
                raise ValueError
            if (
                not isinstance(model, Mapping)
                or model.get("providerId") != provider_id
                or model.get("modelName") != model_name
                or type(model.get("stream")) is not bool
                or type(model.get("supportsStreaming")) is not bool
                or manifest.get("operationType") != operation_type
                or manifest.get("draft", {}).get("revision") != base_revision
                or manifest.get("draft", {}).get("contentHash") != base_hash
            ):
                raise ValueError
            if not DraftOperationService._canonical_uuid(idempotency_key):
                raise ValueError
            DraftOperationService._hash(request_fingerprint)
            DraftOperationService._hash(base_hash)
            DraftOperationService._hash(manifest_hash)
            if (
                not DraftOperationService._canonical_uuid(row["id"])
                or not DraftOperationService._canonical_uuid(row["project_id"])
                or not DraftOperationService._canonical_uuid(row["chapter_session_id"])
                or operation_type not in (
                    LOCAL_DRAFT_OPERATION_TYPES | {"generate_new"}
                )
                or status not in _STATUSES
                or not 1 <= last_event_sequence <= MAX_DRAFT_OPERATION_EVENTS
                or (
                    status in {"starting", "running"}
                    and last_event_sequence > MAX_DRAFT_OPERATION_EVENTS - 1
                )
                or (
                    status == "expired"
                    and last_event_sequence > MAX_DRAFT_OPERATION_EVENTS - 1
                )
                or (
                    status in {"completed", "failed", "cancelled"}
                    and last_event_sequence < 2
                )
                or not isinstance(provider_id, str)
                or not provider_id.strip()
                or not isinstance(model_name, str)
                or not model_name.strip()
                or (
                    status in {"starting", "running"}
                    and (type(active_slot) is not int or active_slot != 1)
                )
                or (
                    status in {"completed", "failed", "cancelled", "expired"}
                    and active_slot is not None
                )
                or (
                    status in {"starting", "running"}
                    and completed_at is not None
                )
                or (
                    status in {"starting", "running"}
                    and (
                        heartbeat_at != updated_at
                        or updated_at >= lease_expires_at
                    )
                )
                or (
                    status in {"completed", "failed", "cancelled"}
                    and (
                        heartbeat_at > updated_at
                        or updated_at >= lease_expires_at
                    )
                )
                or (
                    status == "expired"
                    and (
                        heartbeat_at > updated_at
                        or completed_at != updated_at
                    )
                )
                or (
                    status in {"completed", "failed", "cancelled", "expired"}
                    and (
                        type(completed_at) is not int
                        or completed_at < updated_at
                    )
                )
            ):
                raise ValueError
            if status == "starting" and (
                last_event_sequence != 1
                or partial_output
                or partial_output_hash != _EMPTY_OUTPUT_HASH
                or partial_output_scalars != 0
            ):
                raise ValueError
            if status == "running" and last_event_sequence == 1 and (
                partial_output
                or partial_output_hash != _EMPTY_OUTPUT_HASH
                or partial_output_scalars != 0
            ):
                raise ValueError
            if status == "completed":
                if (
                    result_revision is None
                    or result_revision != base_revision + 1
                    or not isinstance(result_hash, str)
                    or _HASH.fullmatch(result_hash) is None
                    or failure_code is not None
                    or not partial_output
                    or cancelled_at is not None
                    or (
                        operation_type == "generate_new"
                        and (
                            result_hash != partial_output_hash
                            or partial_output != partial_output.strip()
                        )
                    )
                ):
                    raise ValueError
            elif status == "cancelled":
                if (
                    failure_code is not None
                    or cancelled_at != completed_at
                    or partial_output != partial_output.strip()
                    or (
                        operation_type in LOCAL_DRAFT_OPERATION_TYPES
                        and (result_revision is not None or result_hash is not None)
                    )
                    or (
                        operation_type == "generate_new"
                        and bool(partial_output)
                        and (
                            result_revision is None
                            or result_revision != base_revision + 1
                            or result_hash != partial_output_hash
                        )
                    )
                    or (
                        operation_type == "generate_new"
                        and not partial_output
                        and (result_revision is not None or result_hash is not None)
                    )
                ):
                    raise ValueError
            elif status == "failed":
                if (
                    result_revision is not None
                    or result_hash is not None
                    or failure_code not in _SAFE_FAILURE_CODES
                    or cancelled_at is not None
                ):
                    raise ValueError
            elif (
                result_revision is not None
                or result_hash is not None
                or failure_code is not None
                or cancelled_at is not None
            ):
                raise ValueError
            result_selection_start = None
            result_selection_end = None
            if (
                operation_type in LOCAL_DRAFT_OPERATION_TYPES
                and status == "completed"
            ):
                result_selection_start = selection_manifest["startOffset"]
                result_selection_end = (
                    result_selection_start + partial_output_scalars
                )
            return DraftOperationResult(
                operation_id=row["id"],
                project_id=row["project_id"],
                chapter_session_id=row["chapter_session_id"],
                operation_type=operation_type,
                status=status,
                last_event_sequence=last_event_sequence,
                result_working_draft_revision=result_revision,
                result_content_hash=result_hash,
                failure_code=failure_code,
                provider_id=provider_id,
                model_name=model_name,
                partial_output=partial_output,
                partial_output_hash=partial_output_hash,
                partial_output_scalars=partial_output_scalars,
                result_selection_start=result_selection_start,
                result_selection_end=result_selection_end,
            )
        except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
            raise DraftOperationStorageError("stored draft operation is invalid") from None


__all__ = [
    "DRAFT_OPERATION_LEASE_MS",
    "DraftOperationConflict",
    "DraftOperationIdempotencyConflict",
    "DraftOperationNotFound",
    "DraftOperationPreconditionFailed",
    "DraftOperationRequestInvalid",
    "DraftOperationResult",
    "DraftOperationService",
    "DraftOperationStorageError",
    "DraftOperationUnexpectedProviderError",
    "StartDraftOperation",
    "UndoLocalDraft",
]
