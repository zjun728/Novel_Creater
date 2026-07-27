"""Lease-owned, fenced generation for one authoritative Outline Draft."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
import time
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from pymysql.err import MySQLError

from backend.domain.chapter_outlines import (
    ChapterOutlineDomainError,
    DraftChapterOutline,
    EditableChapterOutlineContent,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import PlanningAggregate
from backend.domain.provider_policy import provider_is_generation_ready
from backend.gateways.chapter_outline_provider import (
    ChapterOutlineProviderError,
)
from backend.http_errors import ProjectArchived
from backend.prompts.chapter_outline import (
    ChapterOutlineGenerationManifest,
    PlanningAuthority,
    ProjectionAuthority,
    PublicBindingAuthority,
)
from backend.prompts.planning import planning_text_contains_private_material
from backend.repositories.planning import PlanningRepository
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
)
from backend.services.chapter_outlines import (
    ChapterOutlineArchived,
    ChapterOutlineConflict,
    ChapterOutlineNotFound,
    ChapterOutlinePreconditionFailed,
    ChapterOutlineRequestInvalid,
    authoritative_chapter,
)
from backend.services.planning_generation import (
    PublicModelSummary,
    is_safe_planning_idempotency_key,
)


CHAPTER_OUTLINE_GENERATION_LEASE_MS = 240_000
CHAPTER_OUTLINE_AUTHOR_INSTRUCTIONS_MAX_LENGTH = 4_000
CHAPTER_OUTLINE_RESERVE_RECONCILIATION_LIMIT = 3
CHAPTER_OUTLINE_SETTLEMENT_RETRY_LIMIT = 3
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MYSQL_COORDINATION_CODES = frozenset({1205, 1213, 3572})
_PLANNING_BASIS_FIELDS = (
    "selection_revision",
    "seed_id",
    "seed_revision_id",
    "seed_hash",
    "contract_revision",
    "creation_contract_id",
    "creation_hash",
    "style_contract_id",
    "style_hash",
    "bible_revision",
    "bible_revision_id",
    "bible_hash",
)
_BINDING_FIELDS = (
    "binding_revision_id",
    "binding_revision",
    "binding_hash",
    "provider_id",
    "model_name_snapshot",
)
_PROVIDER_AUTHORITY_FIELDS = (
    "id",
    "provider_type",
    "model_name",
    "base_url",
    "api_key",
    "enabled",
    "lifecycle_status",
    "revision",
    "temperature",
    "max_context_tokens",
    "max_output_tokens",
)
_SAFE_FAILURE_CODES = frozenset(
    {
        "ChapterOutlineGenerationCancelled",
        "ChapterOutlineProviderFailed",
        "ChapterOutlineProviderResultInvalid",
    }
)
_STATUSES = frozenset({"pending", "succeeded", "failed", "superseded"})
_MAX_MYSQL_INT = 2_147_483_647
_FIXED_ERROR = "ChapterOutline generation state changed"


class ChapterOutlineGenerationNotReady(ChapterOutlinePreconditionFailed):
    pass


class ChapterOutlineGenerationRequestInvalid(ChapterOutlineRequestInvalid):
    pass


class ChapterOutlineGenerationConflict(ChapterOutlineConflict):
    pass


class ChapterOutlineGenerationIdempotencyConflict(
    ChapterOutlineGenerationConflict
):
    pass


class ChapterOutlineGenerationOperationNotFound(ChapterOutlineNotFound):
    pass


class ChapterOutlineGenerationRetryable(ChapterOutlineGenerationConflict):
    pass


def _raise_archived() -> None:
    raise ChapterOutlineArchived("Project is archived")


def _raise_not_found() -> None:
    raise ChapterOutlineNotFound("Project not found")


def _raise_generation_not_ready() -> None:
    raise ChapterOutlineGenerationNotReady(_FIXED_ERROR)


def _raise_generation_request_invalid() -> None:
    raise ChapterOutlineGenerationRequestInvalid(_FIXED_ERROR)


def _raise_generation_conflict() -> None:
    raise ChapterOutlineGenerationConflict(_FIXED_ERROR)


def _raise_generation_idempotency_conflict() -> None:
    raise ChapterOutlineGenerationIdempotencyConflict(_FIXED_ERROR)


def _raise_generation_operation_not_found() -> None:
    raise ChapterOutlineGenerationOperationNotFound(_FIXED_ERROR)


def _raise_generation_retryable() -> None:
    raise ChapterOutlineGenerationRetryable(_FIXED_ERROR)


def _raise_clean_cancelled_error() -> None:
    raise asyncio.CancelledError()


@dataclass(frozen=True)
class GenerateChapterOutline:
    project_id: str
    chapter_number: int
    draft_id: str
    draft_revision: int
    draft_hash: str
    idempotency_key: str
    author_instructions: str


@dataclass(frozen=True)
class ChapterOutlineOperationResult:
    operation_id: str
    status: Literal["pending", "succeeded", "failed", "superseded"]
    failure_code: str | None
    model: PublicModelSummary
    loaded: bool
    loaded_draft_revision: int | None


class ChapterOutlineGenerationService:
    def __init__(
        self,
        repository,
        chapter_repository,
        *,
        planning_repository=None,
        provider_gateway,
        transaction_factory,
        id_factory=None,
        clock=None,
    ):
        self.repository = repository
        self.chapter_repository = chapter_repository
        self.planning_repository = planning_repository or PlanningRepository()
        self._gateway = provider_gateway
        self._transaction = transaction_factory
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    async def generate(
        self,
        command: GenerateChapterOutline,
    ) -> ChapterOutlineOperationResult:
        result = None
        failure = None
        try:
            result = await self._generate_sensitive(command)
        except asyncio.CancelledError:
            failure = "cancelled"
        except ChapterOutlineGenerationIdempotencyConflict:
            failure = "idempotency"
        except ChapterOutlineGenerationRetryable:
            failure = "retryable"
        except ChapterOutlineGenerationNotReady:
            failure = "not_ready"
        except ChapterOutlineGenerationRequestInvalid:
            failure = "request_invalid"
        except ChapterOutlineGenerationOperationNotFound:
            failure = "operation_not_found"
        except ChapterOutlineArchived:
            failure = "archived"
        except ChapterOutlineNotFound:
            failure = "not_found"
        except ChapterOutlineGenerationConflict:
            failure = "conflict"
        except Exception as error:
            failure = (
                "retryable"
                if self._is_coordination_failure(error)
                else "conflict"
            )

        command = None
        self = None
        if failure is None:
            assert result is not None
            return result
        result = None
        if failure == "cancelled":
            _raise_clean_cancelled_error()
        if failure == "idempotency":
            _raise_generation_idempotency_conflict()
        if failure == "retryable":
            _raise_generation_retryable()
        if failure == "not_ready":
            _raise_generation_not_ready()
        if failure == "request_invalid":
            _raise_generation_request_invalid()
        if failure == "operation_not_found":
            _raise_generation_operation_not_found()
        if failure == "archived":
            _raise_archived()
        if failure == "not_found":
            _raise_not_found()
        _raise_generation_conflict()

    async def _generate_sensitive(
        self,
        command: GenerateChapterOutline,
    ) -> ChapterOutlineOperationResult:
        self._validate(command)
        context = None
        for _ in range(CHAPTER_OUTLINE_RESERVE_RECONCILIATION_LIMIT):
            try:
                replay, context = await self._reserve(command)
            except Exception as error:
                self._raise_if_coordination_failure(error)
                raise
            if replay is not None:
                return replay
            assert context is not None
            if "expired_attempt" not in context:
                break
            await self._await_settlement(
                self._supersede_expired(command, context)
            )
            context = None
        if context is None:
            raise ChapterOutlineGenerationRetryable(
                "ChapterOutline generation could not reserve a lease"
            )

        try:
            output = await self._gateway.generate(
                provider=context["provider"],
                model_name=context["binding"]["model_name_snapshot"],
                manifest=context["manifest"],
            )
        except asyncio.CancelledError:
            await self._settle_cancelled(command, context)
            raise
        except ChapterOutlineProviderError:
            return await self._await_settlement(
                self._settle_failure_with_retry(
                    command,
                    context,
                    "ChapterOutlineProviderFailed",
                )
            )
        except Exception:
            return await self._await_settlement(
                self._settle_failure_with_retry(
                    command,
                    context,
                    "ChapterOutlineProviderFailed",
                )
            )

        return await self._await_settlement(
            self._publish(command, context, output)
        )

    async def get_operation(
        self,
        project_id: str,
        operation_id: str,
    ) -> ChapterOutlineOperationResult:
        if (
            not isinstance(project_id, str)
            or not project_id.strip()
            or not isinstance(operation_id, str)
            or not operation_id.strip()
        ):
            raise ChapterOutlineGenerationOperationNotFound(
                "ChapterOutline operation not found"
            )
        try:
            async with self._transaction() as session:
                project = await self.repository.read_project_any(
                    session, project_id
                )
                row = await self.repository.read_attempt(
                    session, project_id, operation_id
                )
                if project is None or row is None:
                    raise ChapterOutlineGenerationOperationNotFound(
                        "ChapterOutline operation not found"
                    )
                return self._operation_result(row)
        except Exception as error:
            self._raise_if_coordination_failure(error)
            raise

    async def get_operation_by_key(
        self,
        project_id: str,
        idempotency_key: str,
    ) -> ChapterOutlineOperationResult:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ChapterOutlineGenerationOperationNotFound(
                "ChapterOutline operation not found"
            )
        if not is_safe_planning_idempotency_key(idempotency_key):
            raise ChapterOutlineGenerationRequestInvalid(
                "idempotency key is invalid"
            )
        try:
            async with self._transaction() as session:
                project = await self.repository.read_project_any(
                    session, project_id
                )
                row = await self.repository.read_attempt_by_key(
                    session, project_id, idempotency_key
                )
                if project is None or row is None:
                    raise ChapterOutlineGenerationOperationNotFound(
                        "ChapterOutline operation not found"
                    )
                return self._operation_result(row)
        except Exception as error:
            self._raise_if_coordination_failure(error)
            raise

    async def _reserve(self, command):
        async with self._transaction() as session:
            authority = await self._lock_authority(session, command)
            self._require_reservable(command, authority)
            binding = authority["binding"]
            if not self._provider_ready(binding):
                raise ChapterOutlineGenerationNotReady(
                    "planning model binding is unavailable"
                )

            existing = await self.repository.lock_attempt_by_key(
                session,
                command.project_id,
                command.idempotency_key,
            )
            if existing is not None:
                expected = self._fingerprint_from_persisted(
                    existing, command
                )
                if (
                    expected is None
                    or existing["request_fingerprint"] != expected
                ):
                    raise ChapterOutlineGenerationIdempotencyConflict(
                        "idempotency key fingerprint conflict"
                    )
                if (
                    existing["status"] == "pending"
                    and int(existing["lease_expires_at"]) <= self._clock()
                ):
                    return None, {
                        "expired_attempt": dict(existing),
                        "authority": self._authority_snapshot(authority),
                    }
                return self._operation_result(existing), None

            draft = authority["draft"]
            if not self._draft_is_exact(command, draft):
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline Draft changed"
                )
            manifest = self._manifest(command, authority)
            manifest_payload = manifest.model_dump(mode="json", by_alias=True)
            fingerprint = self._request_fingerprint(
                command, manifest_payload
            )

            active = await self.repository.lock_active_attempt(
                session, command.draft_id
            )
            now = self._clock()
            if active is not None:
                if int(active["lease_expires_at"]) > now:
                    raise ChapterOutlineGenerationConflict(
                        "ChapterOutline generation is already pending"
                    )
                return None, {
                    "expired_attempt": dict(active),
                    "authority": self._authority_snapshot(authority),
                }

            fencing_token = await self.repository.next_fencing_token(
                session, command.draft_id
            )
            attempt_id = self._id()
            operation_id = self._id()
            manifest_hash = canonical_hash(manifest_payload)
            row = {
                "id": attempt_id,
                "project_id": command.project_id,
                "outline_draft_id": command.draft_id,
                "operation_id": operation_id,
                "idempotency_key": command.idempotency_key,
                "request_fingerprint": fingerprint,
                **self._binding_snapshot(binding),
                "fencing_token": fencing_token,
                "lease_expires_at": now
                + CHAPTER_OUTLINE_GENERATION_LEASE_MS,
                "input_manifest": manifest_payload,
                "input_manifest_hash": manifest_hash,
                "created_at": now,
                "updated_at": now,
            }
            if not await self.repository.insert_attempt(session, row):
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline generation was not reserved"
                )
            return None, {
                "attempt": {**row, "status": "pending"},
                "authority": self._authority_snapshot(authority),
                "binding": self._binding_snapshot(binding),
                "provider_authority_hash": self._provider_authority_hash(
                    binding
                ),
                "provider": dict(binding),
                "manifest": manifest,
                "manifest_hash": manifest_hash,
                "fingerprint": fingerprint,
            }

    async def _publish(self, command, context, output):
        if self._request_fingerprint(
            command,
            context["manifest"].model_dump(mode="json", by_alias=True),
        ) != context["fingerprint"]:
            raise ChapterOutlineGenerationConflict(
                "ChapterOutline generation request changed"
            )
        attempt_context = context["attempt"]
        async with self._transaction() as session:
            authority = await self._lock_authority(session, command)
            attempt = await self.repository.lock_attempt(
                session,
                command.project_id,
                attempt_context["operation_id"],
            )
            if attempt is None:
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline generation operation changed"
                )
            if attempt["status"] != "pending":
                return self._operation_result(attempt)
            if not self._attempt_is_owned(attempt, context):
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline generation fence changed"
                )
            if not self._authority_is_current(authority, context):
                return await self._supersede_locked(session, attempt)
            try:
                content = EditableChapterOutlineContent.model_validate(
                    output,
                    strict=True,
                )
                if not self._has_exact_refs(content, context["manifest"]):
                    raise ValueError("generated references differ")
                payload = content.model_dump(mode="json", by_alias=True)
                self._validate_confirmable_content(
                    content,
                    authority,
                    command.chapter_number,
                )
                content_hash = canonical_hash(payload)
            except (
                ChapterOutlineDomainError,
                ValidationError,
                TypeError,
                ValueError,
                KeyError,
                RecursionError,
                UnicodeError,
            ):
                return await self._fail_locked(
                    session,
                    attempt,
                    "ChapterOutlineProviderResultInvalid",
                )

            if await self.repository.load_result_into_draft(
                session,
                command.draft_id,
                command.draft_revision,
                command.draft_hash,
                attempt["operation_id"],
                int(attempt["fencing_token"]),
                payload,
                content_hash,
                self._clock(),
            ):
                terminal = await self.repository.lock_attempt(
                    session,
                    command.project_id,
                    attempt["operation_id"],
                )
                if terminal is None:
                    raise ChapterOutlineGenerationConflict(
                        "ChapterOutline generation result is missing"
                    )
                return self._operation_result(terminal)

            terminal = await self.repository.lock_attempt(
                session,
                command.project_id,
                attempt["operation_id"],
            )
            if terminal is not None and terminal["status"] != "pending":
                return self._operation_result(terminal)
            return await self._supersede_locked(session, attempt)

    @classmethod
    def _validate_confirmable_content(
        cls,
        content,
        authority,
        chapter_number,
    ):
        current = authority["authorities"]
        planning = PlanningAggregate.model_validate(
            current["planning_content"],
            strict=True,
        )
        capacity = cls._capacity_policy(
            current["chapter_capacity_policy"]
        )
        payload = content.model_dump(mode="json", by_alias=True)
        payload.pop("schemaVersion")
        draft = DraftChapterOutline.model_validate(
            {
                "schemaVersion": "chapter-outline-v1",
                "chapterNumber": chapter_number,
                "planningRevisionId": current["planning_revision_id"],
                "planningRevision": int(current["planning_revision"]),
                "planningHash": current["planning_hash"],
                **payload,
                "capacityPolicy": capacity.model_dump(
                    mode="json", by_alias=True
                ),
            },
            strict=True,
        )
        normalize_chapter_outline(
            draft,
            planning=planning,
            authoritative_chapter_number=chapter_number,
            planning_revision_id=str(current["planning_revision_id"]),
            planning_revision=int(current["planning_revision"]),
            capacity_policy=capacity,
            canon_revision=int(current["canon_revision"]),
            projection_revision=int(current["projection_revision"]),
            projection_hash=str(current["projection_hash"]),
        )

    async def _settle_failure_with_retry(
        self,
        command,
        context,
        failure_code,
    ):
        for attempt_index in range(CHAPTER_OUTLINE_SETTLEMENT_RETRY_LIMIT):
            try:
                return await self._settle_failure(
                    command,
                    context,
                    failure_code,
                )
            except Exception as error:
                if not self._is_coordination_failure(error):
                    raise
                if (
                    attempt_index + 1
                    == CHAPTER_OUTLINE_SETTLEMENT_RETRY_LIMIT
                ):
                    raise ChapterOutlineGenerationRetryable(
                        _FIXED_ERROR
                    ) from None
        raise ChapterOutlineGenerationRetryable(_FIXED_ERROR)

    async def _settle_failure(self, command, context, failure_code):
        attempt_context = context["attempt"]
        async with self._transaction() as session:
            authority = await self._lock_authority(session, command)
            attempt = await self.repository.lock_attempt(
                session,
                command.project_id,
                attempt_context["operation_id"],
            )
            if attempt is None:
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline generation operation changed"
                )
            if attempt["status"] != "pending":
                return self._operation_result(attempt)
            if not self._attempt_is_owned(attempt, context):
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline generation fence changed"
                )
            if not self._authority_is_current(authority, context):
                return await self._supersede_locked(session, attempt)
            return await self._fail_locked(session, attempt, failure_code)

    async def _supersede_expired(self, command, context):
        expected = context["expired_attempt"]
        async with self._transaction() as session:
            await self._lock_authority(session, command)
            attempt = await self.repository.lock_attempt(
                session,
                command.project_id,
                expected["operation_id"],
            )
            if attempt is None:
                raise ChapterOutlineGenerationConflict(
                    "expired ChapterOutline operation changed"
                )
            if attempt["status"] != "pending":
                return self._operation_result(attempt)
            if (
                attempt["request_fingerprint"]
                != expected["request_fingerprint"]
                or int(attempt["fencing_token"])
                != int(expected["fencing_token"])
                or int(attempt["lease_expires_at"]) > self._clock()
            ):
                raise ChapterOutlineGenerationConflict(
                    "expired ChapterOutline lease changed"
                )
            return await self._supersede_locked(session, attempt)

    async def _supersede_locked(self, session, attempt):
        if not await self.repository.supersede_attempt(
            session,
            attempt["project_id"],
            attempt["operation_id"],
            int(attempt["fencing_token"]),
        ):
            terminal = await self.repository.lock_attempt(
                session,
                attempt["project_id"],
                attempt["operation_id"],
            )
            if terminal is None or terminal["status"] == "pending":
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline generation supersession changed"
                )
            return self._operation_result(terminal)
        terminal = await self.repository.lock_attempt(
            session,
            attempt["project_id"],
            attempt["operation_id"],
        )
        if terminal is None:
            raise ChapterOutlineGenerationConflict(
                "ChapterOutline generation operation is missing"
            )
        return self._operation_result(terminal)

    async def _fail_locked(self, session, attempt, failure_code):
        if not await self.repository.fail_attempt(
            session,
            attempt["project_id"],
            attempt["operation_id"],
            int(attempt["fencing_token"]),
            failure_code,
        ):
            terminal = await self.repository.lock_attempt(
                session,
                attempt["project_id"],
                attempt["operation_id"],
            )
            if terminal is None or terminal["status"] == "pending":
                raise ChapterOutlineGenerationConflict(
                    "ChapterOutline generation failure changed"
                )
            return self._operation_result(terminal)
        terminal = await self.repository.lock_attempt(
            session,
            attempt["project_id"],
            attempt["operation_id"],
        )
        if terminal is None:
            raise ChapterOutlineGenerationConflict(
                "ChapterOutline generation operation is missing"
            )
        return self._operation_result(terminal)

    async def _lock_authority(self, session, command):
        project = None
        archived = False
        try:
            project = await self.repository.lock_project(
                session, command.project_id
            )
        except ProjectArchived:
            archived = True
        active_session = await self.chapter_repository.read_active_session(
            session, command.project_id
        )
        max_final = (
            await self.chapter_repository.read_max_final_chapter_number(
                session, command.project_id
            )
        )
        basis = await self.planning_repository.read_current_basis(
            session, command.project_id
        )
        planning_head = await self.planning_repository.lock_planning_head(
            session, command.project_id
        )
        authorities = await self.repository.read_current_authorities(
            session, command.project_id
        )
        outline_head = await self.repository.lock_outline_head(
            session, command.project_id, command.chapter_number
        )
        draft = await self.repository.read_draft(
            session,
            command.project_id,
            command.chapter_number,
            command.draft_id,
        )
        binding = await self.planning_repository.lock_planning_binding(
            session, command.project_id
        )
        return {
            "project": project,
            "archived": archived,
            "active_session": active_session,
            "max_final": max_final,
            "chapter_number": authoritative_chapter(
                active_session, max_final
            ),
            "basis": basis,
            "planning_head": planning_head,
            "authorities": authorities,
            "outline_head": outline_head,
            "draft": draft,
            "binding": binding,
        }

    def _require_reservable(self, command, authority):
        if authority["archived"]:
            raise ChapterOutlineArchived("Project is archived")
        if authority["project"] is None:
            raise ChapterOutlineNotFound("Project not found")
        if (
            authority["chapter_number"] != command.chapter_number
            or authority["active_session"] is not None
        ):
            raise ChapterOutlineGenerationConflict(
                "authoritative chapter changed"
            )
        if not self._authority_shape_is_valid(authority):
            raise ChapterOutlineGenerationNotReady(
                "ChapterOutline generation authority is unavailable"
            )

    @classmethod
    def _authority_shape_is_valid(cls, authority):
        basis = authority["basis"]
        head = authority["planning_head"]
        current = authority["authorities"]
        draft = authority["draft"]
        if (
            basis is None
            or head is None
            or current is None
            or draft is None
            or int(head.get("revision") or 0) < 1
            or current.get("planning_revision_id")
            != head.get("planning_revision_id")
            or int(current.get("planning_revision") or 0)
            != int(head.get("revision") or 0)
            or current.get("planning_hash") != head.get("content_hash")
            or any(
                head.get(field) != basis.get(field)
                for field in _PLANNING_BASIS_FIELDS
            )
            or int(current.get("canon_revision") or 0)
            != int(current.get("projection_revision") or 0)
            or _HASH.fullmatch(
                str(current.get("projection_hash") or "")
            )
            is None
            or draft.get("status") != "active"
            or draft.get("active_slot") != 1
            or int(draft.get("base_head_revision") or 0)
            != cls._outline_head_revision(authority["outline_head"])
        ):
            return False
        return all(
            draft.get(key) == current.get(key)
            for key in (
                "planning_revision_id",
                "planning_revision",
                "planning_hash",
                "canon_revision",
                "projection_revision",
                "projection_hash",
            )
        )

    @classmethod
    def _authority_snapshot(cls, authority):
        return {
            "chapter_number": authority["chapter_number"],
            "active_session": cls._stable_mapping(
                authority["active_session"]
            ),
            "max_final": authority["max_final"],
            "basis": {
                key: authority["basis"].get(key)
                for key in _PLANNING_BASIS_FIELDS
            }
            if authority["basis"] is not None
            else None,
            "planning_head": {
                "revision": int(
                    authority["planning_head"].get("revision") or 0
                ),
                "planning_revision_id": authority["planning_head"].get(
                    "planning_revision_id"
                ),
                "content_hash": authority["planning_head"].get(
                    "content_hash"
                ),
            }
            if authority["planning_head"] is not None
            else None,
            "authorities": {
                key: authority["authorities"].get(key)
                for key in (
                    "planning_revision_id",
                    "planning_revision",
                    "planning_hash",
                    "canon_revision",
                    "projection_revision",
                    "projection_hash",
                )
            }
            if authority["authorities"] is not None
            else None,
            "outline_head": {
                "revision": cls._outline_head_revision(
                    authority["outline_head"]
                ),
                "outline_revision_id": (
                    authority["outline_head"].get("outline_revision_id")
                    if authority["outline_head"] is not None
                    else None
                ),
                "content_hash": (
                    authority["outline_head"].get("content_hash")
                    if authority["outline_head"] is not None
                    else None
                ),
            },
            "draft": cls._draft_snapshot(authority["draft"]),
        }

    def _authority_is_current(self, authority, context):
        return (
            not authority["archived"]
            and authority["project"] is not None
            and self._authority_shape_is_valid(authority)
            and self._authority_snapshot(authority) == context["authority"]
            and self._binding_snapshot(authority["binding"])
            == context["binding"]
            and self._provider_authority_hash(authority["binding"])
            == context["provider_authority_hash"]
            and int(context["attempt"]["lease_expires_at"]) > self._clock()
        )

    @classmethod
    def _manifest(cls, command, authority):
        try:
            planning = PlanningAggregate.model_validate(
                authority["authorities"]["planning_content"],
                strict=True,
            )
            block = next(
                item
                for item in planning.story_blocks
                if item.id == planning.active_story_block_id
                and item.lifecycle == "active"
            )
            volume = next(
                item
                for item in planning.volumes
                if item.id == block.volume_id and item.lifecycle == "active"
            )
            plots_by_id = {item.id: item for item in planning.plots}
            plots = tuple(plots_by_id[item] for item in block.plot_ids)
            if any(item.lifecycle != "active" for item in plots):
                raise ValueError("inactive Plot")
            stages = tuple(
                item for item in block.stages if item.lifecycle == "active"
            )
            tasks = tuple(
                task
                for stage in stages
                for task in stage.scene_tasks
                if task.lifecycle == "active"
            )
            capacity = cls._capacity_policy(
                authority["authorities"]["chapter_capacity_policy"]
            )
            binding = authority["binding"]
            return ChapterOutlineGenerationManifest.model_validate(
                {
                    "chapter_number": command.chapter_number,
                    "planning": PlanningAuthority(
                        revision_id=str(
                            authority["planning_head"][
                                "planning_revision_id"
                            ]
                        ),
                        revision=int(
                            authority["planning_head"]["revision"]
                        ),
                        content_hash=str(
                            authority["planning_head"]["content_hash"]
                        ),
                    ),
                    "canon_revision": int(
                        authority["authorities"]["canon_revision"]
                    ),
                    "projection": ProjectionAuthority(
                        revision=int(
                            authority["authorities"][
                                "projection_revision"
                            ]
                        ),
                        content_hash=str(
                            authority["authorities"]["projection_hash"]
                        ),
                    ),
                    "story_block": block,
                    "allowed_stages": stages,
                    "allowed_scene_tasks": tasks,
                    "volume": volume,
                    "plots": plots,
                    "capacity_policy": capacity,
                    "draft_revision": command.draft_revision,
                    "draft_hash": command.draft_hash,
                    "author_instructions": command.author_instructions,
                    "binding": PublicBindingAuthority(
                        revision_id=str(binding["binding_revision_id"]),
                        revision=int(binding["binding_revision"]),
                        content_hash=str(binding["binding_hash"]),
                        provider_id=str(binding["provider_id"]),
                        model_name=str(binding["model_name_snapshot"]),
                    ),
                },
                strict=True,
            )
        except (
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
            ValidationError,
            RecursionError,
            UnicodeError,
        ):
            raise ChapterOutlineGenerationNotReady(
                "ChapterOutline generation manifest is unavailable"
            ) from None

    @staticmethod
    def _capacity_policy(value):
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, Mapping):
            raise ValueError("chapter capacity policy is invalid")
        if {
            "targetMin",
            "targetMax",
            "softCeiling",
        }.issubset(value):
            return OutlineCapacityPolicy.model_validate(value, strict=True)
        word_range = value.get("chapterWordRangePreference")
        if (
            not isinstance(word_range, (list, tuple))
            or len(word_range) != 2
            or any(type(item) is not int for item in word_range)
        ):
            raise ValueError("chapter capacity policy is invalid")
        return OutlineCapacityPolicy.model_validate(
            {
                "targetMin": word_range[0],
                "targetMax": word_range[1],
                "softCeiling": word_range[1],
            },
            strict=True,
        )

    @staticmethod
    def _request_fingerprint(command, manifest_payload):
        return canonical_hash(
            {
                "projectId": command.project_id,
                "chapterNumber": command.chapter_number,
                "draftId": command.draft_id,
                "draftRevision": command.draft_revision,
                "draftHash": command.draft_hash,
                "manifest": manifest_payload,
            }
        )

    @classmethod
    def _fingerprint_from_persisted(cls, attempt, command):
        try:
            manifest = ChapterOutlineGenerationManifest.model_validate(
                attempt["input_manifest"], strict=True
            )
            payload = manifest.model_dump(mode="json", by_alias=True)
            if (
                manifest.chapter_number != command.chapter_number
                or manifest.draft_revision != command.draft_revision
                or manifest.draft_hash != command.draft_hash
                or manifest.author_instructions
                != command.author_instructions
            ):
                return None
            return cls._request_fingerprint(command, payload)
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            RecursionError,
            UnicodeError,
        ):
            return None

    @classmethod
    def _attempt_is_owned(cls, attempt, context):
        expected = context["attempt"]
        return (
            attempt["project_id"] == expected["project_id"]
            and attempt["outline_draft_id"]
            == expected["outline_draft_id"]
            and attempt["operation_id"] == expected["operation_id"]
            and attempt["request_fingerprint"] == context["fingerprint"]
            and int(attempt["fencing_token"])
            == int(expected["fencing_token"])
            and cls._binding_snapshot(attempt) == context["binding"]
            and cls._persisted_manifest_matches(attempt, context)
        )

    @staticmethod
    def _persisted_manifest_matches(attempt, context):
        try:
            persisted = ChapterOutlineGenerationManifest.model_validate(
                attempt["input_manifest"], strict=True
            )
            payload = persisted.model_dump(mode="json", by_alias=True)
            frozen = context["manifest"].model_dump(
                mode="json", by_alias=True
            )
            return (
                payload == frozen
                and canonical_json(payload) == canonical_json(frozen)
                and canonical_hash(payload)
                == attempt["input_manifest_hash"]
                == context["manifest_hash"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            RecursionError,
            UnicodeError,
        ):
            return False

    @staticmethod
    def _has_exact_refs(content, manifest):
        def matches(ref, node):
            return (
                ref is not None
                and ref.id == node.id
                and ref.revision == node.revision
                and ref.content_hash == node.content_hash
            )

        return (
            matches(content.volume_ref, manifest.volume)
            and matches(content.story_block_ref, manifest.story_block)
            and len(content.stage_refs) == len(manifest.allowed_stages)
            and all(
                matches(ref, node)
                for ref, node in zip(
                    content.stage_refs,
                    manifest.allowed_stages,
                    strict=True,
                )
            )
            and len(content.scene_task_refs)
            == len(manifest.allowed_scene_tasks)
            and all(
                matches(ref, node)
                for ref, node in zip(
                    content.scene_task_refs,
                    manifest.allowed_scene_tasks,
                    strict=True,
                )
            )
        )

    @staticmethod
    def _provider_ready(binding):
        if binding is None:
            return False
        try:
            secrets = normalize_provider_secrets(
                (binding["api_key"], binding["base_url"])
            )
            public_model = {
                "providerId": binding["provider_id"],
                "modelName": binding["model_name_snapshot"],
            }
            return (
                binding["binding_task_key"] == "planning"
                and binding["resolution_status"] == "bound"
                and binding["provider_id"] == binding["id"]
                and binding["model_name_snapshot"] == binding["model_name"]
                and int(binding["binding_revision"]) > 0
                and _HASH.fullmatch(binding["binding_hash"]) is not None
                and provider_is_generation_ready(binding)
                and not provider_public_fields_contain_secret(
                    public_model, secrets
                )
            )
        except (KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _binding_snapshot(binding):
        if binding is None:
            return None
        try:
            return {key: binding[key] for key in _BINDING_FIELDS}
        except (KeyError, TypeError):
            return None

    @staticmethod
    def _provider_authority_hash(binding):
        if binding is None:
            return None

        def stable(value):
            if value is None or isinstance(
                value, (str, int, float, bool)
            ):
                return value
            return str(value)

        try:
            return canonical_hash(
                {
                    key: stable(binding[key])
                    for key in _PROVIDER_AUTHORITY_FIELDS
                }
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _draft_is_exact(command, draft):
        return (
            draft is not None
            and draft.get("id") == command.draft_id
            and int(draft.get("draft_revision") or 0)
            == command.draft_revision
            and draft.get("content_hash") == command.draft_hash
        )

    @staticmethod
    def _draft_snapshot(draft):
        if draft is None:
            return None
        return {
            "id": draft.get("id"),
            "chapter_num": int(draft.get("chapter_num") or 0),
            "base_head_revision": int(
                draft.get("base_head_revision") or 0
            ),
            "draft_revision": int(draft.get("draft_revision") or 0),
            "content_hash": draft.get("content_hash"),
            "status": draft.get("status"),
            **{
                key: draft.get(key)
                for key in (
                    "planning_revision_id",
                    "planning_revision",
                    "planning_hash",
                    "canon_revision",
                    "projection_revision",
                    "projection_hash",
                )
            },
        }

    @staticmethod
    def _outline_head_revision(head):
        return 0 if head is None else int(head.get("revision") or 0)

    @staticmethod
    def _stable_mapping(value):
        if value is None:
            return None
        return {
            key: value.get(key)
            for key in ("id", "chapter_num", "status")
        }

    @staticmethod
    def _operation_result(row):
        result = None
        operation_id = None
        status = None
        failure_code = None
        loaded_revision = None
        loaded_at = None
        result_content = None
        result_content_hash = None
        active_slot = None
        provider_id = None
        model_name = None
        try:
            operation_id = row.get("operation_id")
            status = row.get("status")
            active_slot = row.get("active_slot")
            failure_code = row.get("failure_code")
            loaded_revision = row.get(
                "loaded_outline_draft_revision"
            )
            loaded_at = row.get("loaded_at")
            result_content = row.get("result_content")
            result_content_hash = row.get("result_content_hash")
            provider_id = str(row.get("provider_id") or "")
            model_name = str(row.get("model_name_snapshot") or "")
            if (
                not provider_id
                or not model_name
                or planning_text_contains_private_material(provider_id)
                or planning_text_contains_private_material(model_name)
            ):
                provider_id = "unavailable"
                model_name = "unavailable"
            state_valid = (
                status in _STATUSES
                and (
                    (
                        status == "pending"
                        and type(active_slot) is int
                        and active_slot == 1
                        and failure_code is None
                        and result_content is None
                        and result_content_hash is None
                        and loaded_revision is None
                        and loaded_at is None
                    )
                    or (
                        status == "succeeded"
                        and active_slot is None
                        and failure_code is None
                        and result_content is not None
                        and isinstance(result_content_hash, str)
                        and _HASH.fullmatch(result_content_hash) is not None
                        and type(loaded_revision) is int
                        and 0 < loaded_revision <= _MAX_MYSQL_INT
                        and type(loaded_at) is int
                        and loaded_at >= 0
                    )
                    or (
                        status == "failed"
                        and active_slot is None
                        and failure_code in _SAFE_FAILURE_CODES
                        and result_content is None
                        and result_content_hash is None
                        and loaded_revision is None
                        and loaded_at is None
                    )
                    or (
                        status == "superseded"
                        and active_slot is None
                        and failure_code is None
                        and result_content is None
                        and result_content_hash is None
                        and loaded_revision is None
                        and loaded_at is None
                    )
                )
            )
            if (
                state_valid
                and ChapterOutlineGenerationService._operation_id_is_valid(
                    operation_id
                )
            ):
                result = ChapterOutlineOperationResult(
                    operation_id=operation_id,
                    status=status,
                    failure_code=failure_code,
                    model=PublicModelSummary(provider_id, model_name),
                    loaded=status == "succeeded",
                    loaded_draft_revision=(
                        loaded_revision
                        if status == "succeeded"
                        else None
                    ),
                )
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            UnicodeError,
        ):
            result = None

        row = None
        operation_id = None
        status = None
        failure_code = None
        loaded_revision = None
        loaded_at = None
        result_content = None
        result_content_hash = None
        active_slot = None
        provider_id = None
        model_name = None
        if result is None:
            _raise_generation_conflict()
        return result

    @staticmethod
    def _operation_id_is_valid(value) -> bool:
        if type(value) is not str or len(value) != 36:
            return False
        try:
            parsed = UUID(value)
        except (AttributeError, TypeError, ValueError):
            return False
        return str(parsed) == value

    @staticmethod
    def public_operation_is_valid(result) -> bool:
        try:
            if (
                not isinstance(result, ChapterOutlineOperationResult)
                or not ChapterOutlineGenerationService._operation_id_is_valid(
                    result.operation_id
                )
                or not isinstance(result.model, PublicModelSummary)
                or not isinstance(result.model.provider_id, str)
                or not result.model.provider_id
                or not isinstance(result.model.model_name, str)
                or not result.model.model_name
            ):
                return False
            revision = result.loaded_draft_revision
            revision_is_positive = (
                type(revision) is int
                and 0 < revision <= _MAX_MYSQL_INT
            )
            return (
                (
                    result.status == "pending"
                    and result.failure_code is None
                    and result.loaded is False
                    and revision is None
                )
                or (
                    result.status == "succeeded"
                    and result.failure_code is None
                    and result.loaded is True
                    and revision_is_positive
                )
                or (
                    result.status == "failed"
                    and result.failure_code in _SAFE_FAILURE_CODES
                    and result.loaded is False
                    and revision is None
                )
                or (
                    result.status == "superseded"
                    and result.failure_code is None
                    and result.loaded is False
                    and revision is None
                )
            )
        except (
            AttributeError,
            TypeError,
            ValueError,
            OverflowError,
            UnicodeError,
        ):
            return False

    @staticmethod
    def _validate(command):
        if not isinstance(command, GenerateChapterOutline):
            raise ChapterOutlineGenerationRequestInvalid(
                "ChapterOutline generation request is invalid"
            )
        if not is_safe_planning_idempotency_key(command.idempotency_key):
            raise ChapterOutlineGenerationRequestInvalid(
                "idempotency key is invalid"
            )
        if (
            not isinstance(command.project_id, str)
            or not command.project_id.strip()
            or type(command.chapter_number) is not int
            or command.chapter_number < 1
            or not isinstance(command.draft_id, str)
            or not command.draft_id.strip()
            or type(command.draft_revision) is not int
            or command.draft_revision < 1
            or _HASH.fullmatch(command.draft_hash or "") is None
            or not isinstance(command.author_instructions, str)
            or len(command.author_instructions)
            > CHAPTER_OUTLINE_AUTHOR_INSTRUCTIONS_MAX_LENGTH
        ):
            raise ChapterOutlineGenerationRequestInvalid(
                "ChapterOutline generation request is invalid"
            )
        try:
            command.author_instructions.encode("utf-8")
        except UnicodeError:
            raise ChapterOutlineGenerationRequestInvalid(
                "ChapterOutline generation request is invalid"
            ) from None

    async def _await_settlement(self, awaitable):
        task = asyncio.create_task(
            awaitable,
            name="chapter-outline-generation-settlement",
        )
        current = asyncio.current_task()
        cancellation_observed = False
        consumed_cancellations = 0

        def consume_outer_cancellation():
            nonlocal cancellation_observed, consumed_cancellations
            if current is None or current.cancelling() <= 0:
                return False
            cancellation_observed = True
            uncancel = getattr(current, "uncancel", None)
            if uncancel is not None:
                while current.cancelling() > 0:
                    before = current.cancelling()
                    uncancel()
                    after = current.cancelling()
                    if after >= before:
                        break
                    consumed_cancellations += before - after
            return True

        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.done():
                    break
                if consume_outer_cancellation():
                    continue
                break
            except Exception:
                break
        consume_outer_cancellation()
        try:
            result = task.result()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._raise_if_coordination_failure(error)
            raise
        if cancellation_observed:
            if current is not None:
                for _ in range(consumed_cancellations):
                    current.cancel()
            raise asyncio.CancelledError
        return result

    async def _settle_cancelled(self, command, context):
        await self._await_settlement(
            self._settle_failure_with_retry(
                command,
                context,
                "ChapterOutlineGenerationCancelled",
            )
        )

    @staticmethod
    def _is_coordination_failure(error):
        if isinstance(error, BaseExceptionGroup):
            return bool(error.exceptions) and all(
                ChapterOutlineGenerationService._is_coordination_failure(
                    nested
                )
                for nested in error.exceptions
            )
        return (
            isinstance(error, MySQLError)
            and bool(error.args)
            and error.args[0] in _MYSQL_COORDINATION_CODES
        )

    @classmethod
    def _raise_if_coordination_failure(cls, error):
        if cls._is_coordination_failure(error):
            raise ChapterOutlineGenerationRetryable(
                "ChapterOutline generation coordination changed"
            ) from None


__all__ = (
    "CHAPTER_OUTLINE_AUTHOR_INSTRUCTIONS_MAX_LENGTH",
    "CHAPTER_OUTLINE_GENERATION_LEASE_MS",
    "CHAPTER_OUTLINE_RESERVE_RECONCILIATION_LIMIT",
    "CHAPTER_OUTLINE_SETTLEMENT_RETRY_LIMIT",
    "ChapterOutlineGenerationConflict",
    "ChapterOutlineGenerationIdempotencyConflict",
    "ChapterOutlineGenerationNotReady",
    "ChapterOutlineGenerationOperationNotFound",
    "ChapterOutlineGenerationRequestInvalid",
    "ChapterOutlineGenerationRetryable",
    "ChapterOutlineGenerationService",
    "ChapterOutlineOperationResult",
    "GenerateChapterOutline",
    "PublicModelSummary",
)
