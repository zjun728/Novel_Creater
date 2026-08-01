"""Persistent, idempotent and fenced chapter WorkingDraft generation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
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
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
    provider_public_value_contains_secret,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


DRAFT_OPERATION_LEASE_MS = 1_260_000
DRAFT_OPERATION_AUTHOR_INSTRUCTION_MAX_LENGTH = 2_000
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
_PROVIDER_AUTHORITY_FIELDS = (
    "binding_revision_id",
    "binding_revision",
    "binding_hash",
    "binding_item_hash",
    "id",
    "provider_type",
    "model_name",
    "base_url",
    "api_key",
    "temperature",
    "max_output_tokens",
)
_STATUSES = frozenset({"starting", "running", "completed", "failed", "expired"})
_SAFE_FAILURE_CODES = frozenset({"DraftProviderFailed", "DraftProviderResultInvalid"})


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


@dataclass(frozen=True)
class StartDraftOperation:
    project_id: str
    chapter_session_id: str
    operation_type: str
    expected_working_draft_revision: int
    expected_content_hash: str
    idempotency_key: str
    author_instruction: str = ""


@dataclass(frozen=True)
class DraftOperationResult:
    operation_id: str
    project_id: str
    chapter_session_id: str
    operation_type: str
    status: Literal["starting", "running", "completed", "failed", "expired"]
    last_event_sequence: int
    result_working_draft_revision: int | None
    result_content_hash: str | None
    failure_code: str | None
    provider_id: str
    model_name: str


class DraftOperationService:
    def __init__(
        self,
        repository,
        *,
        provider_gateway=None,
        transaction_factory,
        id_factory=None,
        clock=None,
    ):
        self.repository = repository
        self._gateway = provider_gateway or ChapterDraftProviderGateway()
        self._transaction = transaction_factory
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

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
            if (
                not isinstance(command, StartDraftOperation)
                or not cls._canonical_uuid(command.project_id)
                or not cls._canonical_uuid(command.chapter_session_id)
                or command.operation_type != "generate_new"
                or isinstance(command.expected_working_draft_revision, bool)
                or not isinstance(command.expected_working_draft_revision, int)
                or command.expected_working_draft_revision <= 0
                or not isinstance(command.expected_content_hash, str)
                or _HASH.fullmatch(command.expected_content_hash) is None
                or not cls._canonical_uuid(command.idempotency_key)
                or not isinstance(instruction, str)
                or len(instruction) > DRAFT_OPERATION_AUTHOR_INSTRUCTION_MAX_LENGTH
            ):
                raise ValueError
            instruction.encode("utf-8")
        except (AttributeError, TypeError, ValueError, UnicodeError):
            raise DraftOperationRequestInvalid() from None
        return StartDraftOperation(
            project_id=command.project_id,
            chapter_session_id=command.chapter_session_id,
            operation_type="generate_new",
            expected_working_draft_revision=command.expected_working_draft_revision,
            expected_content_hash=command.expected_content_hash,
            idempotency_key=command.idempotency_key,
            author_instruction=instruction.strip(),
        )

    async def start(self, command: StartDraftOperation) -> DraftOperationResult:
        command = self.validate(command)
        replay, context = await self._reserve(command)
        if replay is not None:
            return replay
        try:
            generated = await self._gateway.generate(
                provider=context["provider"],
                messages=context["messages"],
                generation_config=self._generation_config(context["provider"]),
            )
        except ChapterDraftProviderError:
            return await self._settle_failure(context, "DraftProviderFailed")
        return await self._settle_success(context, generated)

    async def _reserve(self, command):
        fingerprint = self._request_fingerprint(command)
        async with self._transaction() as session:
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
                    return self._expired_result(existing), None
                return self._result(existing), None

            if chapter_session.get("status") != "drafting":
                raise DraftOperationConflict()
            draft = await self.repository.lock_working_draft_for_operation(
                session, command.project_id, command.chapter_session_id
            )
            if not self._draft_matches_command(draft, command):
                raise DraftOperationConflict()

            authority = await self._read_authority(session, chapter_session, draft)
            manifest = self._manifest(command, authority)
            manifest_hash = canonical_hash(manifest)
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
                "operation_type": "generate_new",
                "idempotency_key": command.idempotency_key,
                "request_fingerprint": fingerprint,
                "active_slot": 1,
                "fencing_token": fencing_token,
                "lease_expires_at": now + DRAFT_OPERATION_LEASE_MS,
                "base_working_draft_revision": command.expected_working_draft_revision,
                "base_working_draft_hash": command.expected_content_hash,
                "input_manifest": manifest,
                "input_manifest_hash": manifest_hash,
                "provider_id": authority["provider"]["id"],
                "model_name_snapshot": authority["provider"]["model_name"],
                "result_working_draft_revision": None,
                "result_content_hash": None,
                "last_event_sequence": 0,
                "failure_code": None,
                "status": "starting",
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
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
            return None, {
                "command": command,
                "attempt": {**row, "status": "running", "last_event_sequence": 1},
                "manifest": manifest,
                "manifest_hash": manifest_hash,
                "authority": self._authority_snapshot(authority),
                "provider_authority_hash": self._provider_authority_hash(
                    authority["provider"]
                ),
                "provider": dict(authority["provider"]),
                "messages": build_chapter_draft_messages(
                    operation_type="generate_new",
                    chapter_session=prompt_session,
                    working_draft=draft,
                    author_instruction=command.author_instruction,
                ),
            }

    async def _settle_success(self, context, generated):
        async with self._transaction() as session:
            locked = await self._lock_settlement(session, context)
            terminal = await self._terminal_or_expire_drift(session, context, locked)
            if terminal is not None:
                return terminal
            attempt = locked["attempt"]
            draft = locked["draft"]
            try:
                content = validate_provider_response_text(generated, strip=True)
                secrets = normalize_provider_secrets(
                    (context["provider"].get("api_key"), context["provider"].get("base_url"))
                )
                if (
                    provider_response_text_contains_secret(content, secrets)
                    or provider_response_value_contains_secret(content, secrets)
                ):
                    raise ValueError
            except (TypeError, ValueError, RecursionError, UnicodeError):
                return await self._fail_locked(
                    session, context, attempt, "DraftProviderResultInvalid"
                )

            now = self._clock()
            result_revision = int(draft["revision"]) + 1
            result_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
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
                    "operationType": "generate_new",
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
                    2,
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
                    "updated_at": now,
                    "completed_at": now,
                },
            ):
                raise DraftOperationStorageError("could not complete draft operation")
            return DraftOperationResult(
                operation_id=attempt["id"],
                project_id=context["command"].project_id,
                chapter_session_id=context["command"].chapter_session_id,
                operation_type="generate_new",
                status="completed",
                last_event_sequence=2,
                result_working_draft_revision=result_revision,
                result_content_hash=result_hash,
                failure_code=None,
                provider_id=attempt["provider_id"],
                model_name=attempt["model_name_snapshot"],
            )

    async def _settle_failure(self, context, code):
        async with self._transaction() as session:
            locked = await self._lock_settlement(session, context)
            terminal = await self._terminal_or_expire_drift(session, context, locked)
            if terminal is not None:
                return terminal
            return await self._fail_locked(
                session, context, locked["attempt"], code
            )

    async def _fail_locked(self, session, context, attempt, code):
        now = self._clock()
        if not await self.repository.insert_draft_operation_event(
            session,
            self._event_row(
                context["command"].project_id,
                attempt["id"],
                2,
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
                "updated_at": now,
                "completed_at": now,
            },
        ):
            raise DraftOperationStorageError("could not fail draft operation")
        return DraftOperationResult(
            operation_id=attempt["id"],
            project_id=context["command"].project_id,
            chapter_session_id=context["command"].chapter_session_id,
            operation_type="generate_new",
            status="failed",
            last_event_sequence=2,
            result_working_draft_revision=None,
            result_content_hash=None,
            failure_code=code,
            provider_id=attempt["provider_id"],
            model_name=attempt["model_name_snapshot"],
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
            return self._result(attempt)
        now = self._clock()
        if int(attempt["lease_expires_at"]) <= now:
            if not await self.repository.expire_draft_operation(
                session, attempt["id"], int(attempt["fencing_token"]), now
            ):
                raise DraftOperationStorageError("could not expire elapsed operation")
            return self._expired_result(attempt)

        owned = (
            locked["session"].get("active_draft_operation_id") == attempt["id"]
            and int(attempt["fencing_token"])
            == int(context["attempt"]["fencing_token"])
            and attempt.get("active_slot") == 1
        )
        if not owned:
            return self._result(attempt)

        authority = await self._read_authority(
            session, locked["session"], locked["draft"], strict=False
        )
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
        authority_matches = (
            authority is not None
            and self._authority_snapshot(authority) == context["authority"]
            and self._provider_authority_hash(authority["provider"])
            == context["provider_authority_hash"]
            and canonical_hash(self._manifest(context["command"], authority))
            == context["manifest_hash"]
            and self._draft_matches_command(locked["draft"], context["command"])
        )
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
        return self._expired_result(attempt)

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
            authority = {
                "session": dict(authoritative_session),
                "outline": self._outline_snapshot(outline),
                "projection": self._projection_snapshot(projection),
                "draft": self._draft_snapshot(draft),
                "provider": dict(provider),
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
        provider = authority["provider"]
        if session["status"] != "drafting":
            raise ValueError
        for session_key, outline_key in (
            ("chapter_outline_revision_id", "revisionId"),
            ("chapter_outline_revision", "revision"),
            ("chapter_outline_hash", "contentHash"),
            ("planning_revision_id", "planningRevisionId"),
            ("planning_revision", "planningRevision"),
            ("planning_hash", "planningHash"),
            ("outline_canon_revision", "canonRevision"),
            ("outline_projection_revision", "projectionRevision"),
            ("outline_projection_hash", "projectionHash"),
        ):
            if session[session_key] != outline[outline_key]:
                raise ValueError
        if (
            int(session["expected_canon_revision"]) != projection["canonRevision"]
            or projection["canonRevision"] != projection["projectionRevision"]
            or outline["canonRevision"] != projection["canonRevision"]
            or outline["projectionRevision"] != projection["projectionRevision"]
            or outline["projectionHash"] != projection["contentHash"]
            or provider.get("provider_type") != "openai-compatible"
            or not all(
                isinstance(provider.get(key), str) and bool(provider[key].strip())
                for key in ("id", "model_name", "base_url", "api_key")
            )
            or int(provider["binding_revision"]) <= 0
            or _HASH.fullmatch(str(provider["binding_hash"])) is None
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
        return {
            "revisionId": outline["chapter_outline_revision_id"],
            "revision": int(outline["chapter_outline_revision"]),
            "contentHash": outline["chapter_outline_hash"],
            "planningRevisionId": outline["planning_revision_id"],
            "planningRevision": int(outline["planning_revision"]),
            "planningHash": outline["planning_hash"],
            "canonRevision": int(outline["canon_revision"]),
            "projectionRevision": int(outline["projection_revision"]),
            "projectionHash": outline["projection_hash"],
            "content": outline["chapter_outline"],
        }

    @staticmethod
    def _projection_snapshot(projection):
        if projection is None:
            raise ValueError
        return {
            "canonRevision": int(projection["canon_revision_number"]),
            "projectionRevision": int(projection["projection_revision_number"]),
            "contentHash": projection["content_hash"],
        }

    @staticmethod
    def _draft_snapshot(draft):
        if draft is None:
            raise ValueError
        return {
            "id": draft["id"],
            "revision": int(draft["revision"]),
            "contentHash": draft["content_hash"],
        }

    @classmethod
    def _authority_snapshot(cls, authority):
        return {
            "session": {
                key: authority["session"].get(key)
                for key in _SESSION_IDENTITY_FIELDS
            },
            "outline": authority["outline"],
            "projection": authority["projection"],
            "draft": authority["draft"],
            "binding": {
                "revisionId": authority["provider"].get("binding_revision_id"),
                "revision": authority["provider"].get("binding_revision"),
                "contentHash": authority["provider"].get("binding_hash"),
                "itemHash": authority["provider"].get("binding_item_hash"),
            },
            "model": {
                "providerId": authority["provider"].get("id"),
                "modelName": authority["provider"].get("model_name"),
            },
        }

    @classmethod
    def _manifest(cls, command, authority):
        manifest = {
            "schemaVersion": 1,
            "operationType": "generate_new",
            **cls._authority_snapshot(authority),
            "authorInstruction": command.author_instruction,
        }
        secrets = normalize_provider_secrets(
            (authority["provider"].get("api_key"), authority["provider"].get("base_url"))
        )
        if provider_public_value_contains_secret(manifest, secrets):
            raise DraftOperationPreconditionFailed()
        return manifest

    @staticmethod
    def _request_fingerprint(command):
        return canonical_hash({
            "projectId": command.project_id,
            "chapterSessionId": command.chapter_session_id,
            "operationType": "generate_new",
            "baseWorkingDraftRevision": command.expected_working_draft_revision,
            "baseWorkingDraftHash": command.expected_content_hash,
            "authorInstruction": command.author_instruction,
        })

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

    @staticmethod
    def _provider_authority_hash(provider):
        try:
            return canonical_hash({
                key: provider[key] for key in _PROVIDER_AUTHORITY_FIELDS
            })
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _generation_config(provider):
        return {
            "temperature": float(provider.get("temperature") or 0.82),
            "maxOutputTokens": int(provider.get("max_output_tokens") or 4500),
        }

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
            "replacement_reason": "generate_new",
            "source_operation_id": context["attempt"]["id"],
            "content": content,
            "content_hash": content_hash,
            "created_at": now,
        }

    @staticmethod
    def _expired_result(attempt):
        return DraftOperationResult(
            operation_id=attempt["id"],
            project_id=attempt["project_id"],
            chapter_session_id=attempt["chapter_session_id"],
            operation_type=attempt.get("operation_type", "generate_new"),
            status="expired",
            last_event_sequence=int(attempt.get("last_event_sequence") or 1),
            result_working_draft_revision=None,
            result_content_hash=None,
            failure_code=None,
            provider_id=attempt.get("provider_id", "unavailable"),
            model_name=attempt.get("model_name_snapshot", "unavailable"),
        )

    @staticmethod
    def _result(row):
        try:
            status = row["status"]
            operation_type = row["operation_type"]
            last_event_sequence = int(row["last_event_sequence"])
            result_revision = (
                int(row["result_working_draft_revision"])
                if row.get("result_working_draft_revision") is not None else None
            )
            result_hash = row.get("result_content_hash")
            failure_code = row.get("failure_code")
            provider_id = row["provider_id"]
            model_name = row["model_name_snapshot"]
            if (
                not DraftOperationService._canonical_uuid(row["id"])
                or not DraftOperationService._canonical_uuid(row["project_id"])
                or not DraftOperationService._canonical_uuid(row["chapter_session_id"])
                or operation_type != "generate_new"
                or status not in _STATUSES
                or last_event_sequence < 0
                or not isinstance(provider_id, str)
                or not provider_id.strip()
                or not isinstance(model_name, str)
                or not model_name.strip()
            ):
                raise ValueError
            if status == "completed":
                if (
                    result_revision is None
                    or result_revision <= int(row["base_working_draft_revision"])
                    or not isinstance(result_hash, str)
                    or _HASH.fullmatch(result_hash) is None
                    or failure_code is not None
                ):
                    raise ValueError
            elif status == "failed":
                if (
                    result_revision is not None
                    or result_hash is not None
                    or failure_code not in _SAFE_FAILURE_CODES
                ):
                    raise ValueError
            elif (
                result_revision is not None
                or result_hash is not None
                or failure_code is not None
            ):
                raise ValueError
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
            )
        except (KeyError, TypeError, ValueError):
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
    "StartDraftOperation",
]
