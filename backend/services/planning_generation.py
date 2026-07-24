"""Lease-owned, fenced generation for the single Planning Draft chain."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import time
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import (
    DraftPlanningAggregate,
    PlanningAggregate,
    PlanningDomainError,
    normalize_planning_aggregate,
)
from backend.domain.provider_policy import provider_is_generation_ready
from backend.gateways.planning_provider import PlanningProviderError
from backend.http_errors import ProjectArchived, PublicDomainError
from backend.prompts.planning import PlanningGenerationManifest
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
)


PLANNING_GENERATION_LEASE_MS = 240_000
PLANNING_AUTHOR_INSTRUCTIONS_MAX_LENGTH = 4_000
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_BASIS_FIELDS = (
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


class PlanningGenerationNotReady(PublicDomainError):
    status_code = 422
    code = "PlanningGenerationNotReady"
    message = "Planning generation prerequisites are unavailable"


class PlanningGenerationConflict(PublicDomainError):
    status_code = 409
    code = "PlanningGenerationConflict"
    message = "Planning generation inputs changed; refresh and retry"


class PlanningGenerationIdempotencyConflict(PublicDomainError):
    status_code = 409
    code = "PlanningGenerationIdempotencyConflict"
    message = "Planning generation key was used for another request"


class PlanningGenerationOperationNotFound(PublicDomainError):
    status_code = 404
    code = "PlanningGenerationOperationNotFound"
    message = "Planning generation operation not found"


@dataclass(frozen=True)
class GeneratePlanningDraft:
    project_id: str
    draft_id: str
    draft_revision: int
    draft_hash: str
    idempotency_key: str
    author_instructions: str


@dataclass(frozen=True)
class PublicModelSummary:
    provider_id: str
    model_name: str


@dataclass(frozen=True)
class PlanningOperationResult:
    operation_id: str
    status: Literal["pending", "succeeded", "failed", "superseded"]
    failure_code: str | None
    model: PublicModelSummary
    loaded: bool
    loaded_draft_revision: int | None


class PlanningGenerationService:
    def __init__(
        self,
        repository,
        *,
        provider_gateway,
        transaction_factory,
        id_factory=None,
        clock=None,
    ):
        self.repository = repository
        self._gateway = provider_gateway
        self._transaction = transaction_factory
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    async def generate(
        self,
        command: GeneratePlanningDraft,
    ) -> PlanningOperationResult:
        self._validate(command)
        replay, context = await self._reserve(command)
        if replay is not None:
            return replay
        assert context is not None

        try:
            output = await self._gateway.generate(
                provider=context["provider"],
                model_name=context["binding"]["model_name_snapshot"],
                manifest=context["manifest"],
                author_instructions=command.author_instructions,
            )
        except asyncio.CancelledError:
            await self._settle_cancelled(context)
            raise
        except PlanningProviderError:
            return await self._fail(
                context, "PlanningProviderFailed"
            )
        except Exception:
            return await self._fail(
                context, "PlanningProviderFailed"
            )

        try:
            draft_result = DraftPlanningAggregate.model_validate(
                output,
                strict=True,
            )
        except (
            ValidationError,
            TypeError,
            ValueError,
            RecursionError,
        ):
            return await self._fail(
                context, "PlanningProviderResultInvalid"
            )

        try:
            return await self._publish(command, context, draft_result)
        except asyncio.CancelledError:
            await self._settle_cancelled(context)
            raise

    async def get_operation(
        self,
        project_id: str,
        operation_id: str,
    ) -> PlanningOperationResult:
        if (
            not isinstance(project_id, str)
            or not project_id.strip()
            or not isinstance(operation_id, str)
            or not operation_id.strip()
        ):
            raise PlanningGenerationOperationNotFound()
        async with self._transaction() as session:
            project = await self.repository.read_project_any(
                session, project_id
            )
            operation = await self.repository.lock_generation_attempt(
                session, project_id, operation_id
            )
            if project is None or operation is None:
                raise PlanningGenerationOperationNotFound()
            return self._operation_result(operation)

    async def _reserve(self, command):
        fingerprint = self._request_fingerprint(command)
        async with self._transaction() as session:
            try:
                project = await self.repository.lock_active_project(
                    session, command.project_id
                )
            except ProjectArchived:
                project = None
            if project is None:
                raise PlanningGenerationNotReady()
            basis = await self.repository.read_current_basis(
                session, command.project_id
            )
            if basis is None:
                raise PlanningGenerationNotReady()
            head = await self.repository.lock_planning_head(
                session, command.project_id
            )
            draft = await self.repository.read_draft(
                session, command.project_id, command.draft_id
            )
            binding = await self.repository.lock_planning_binding(
                session, command.project_id
            )

            existing = (
                await self.repository.lock_generation_attempt_by_key(
                    session,
                    command.project_id,
                    command.idempotency_key,
                )
            )
            if existing is not None:
                if existing["request_fingerprint"] != fingerprint:
                    raise PlanningGenerationIdempotencyConflict()
                if (
                    existing["status"] == "pending"
                    and int(existing["lease_expires_at"])
                    <= self._clock()
                ):
                    if not await self.repository.supersede_generation_attempt(
                        session,
                        project_id=command.project_id,
                        operation_id=existing["operation_id"],
                        fencing_token=int(existing["fencing_token"]),
                        updated_at=self._clock(),
                    ):
                        raise PlanningGenerationConflict()
                    existing = (
                        await self.repository.lock_generation_attempt(
                            session,
                            command.project_id,
                            existing["operation_id"],
                        )
                    )
                return self._operation_result(existing), None
            if (
                head is None
                or draft is None
                or not self._draft_is_exact(command, draft)
                or not self._draft_authority_matches(draft, basis, head)
            ):
                raise PlanningGenerationConflict()
            if not self._provider_ready(binding):
                raise PlanningGenerationNotReady()

            active = await self.repository.lock_active_generation_attempt(
                session, command.draft_id
            )
            now = self._clock()
            if active is not None:
                if int(active["lease_expires_at"]) > now:
                    raise PlanningGenerationConflict()
                if not await self.repository.supersede_generation_attempt(
                    session,
                    project_id=command.project_id,
                    operation_id=active["operation_id"],
                    fencing_token=int(active["fencing_token"]),
                    updated_at=now,
                ):
                    raise PlanningGenerationConflict()

            fencing_token = await self.repository.next_fencing_token(
                session, command.draft_id
            )
            manifest = self._manifest(
                command,
                basis=basis,
                draft=draft,
            )
            manifest_json = canonical_json(
                manifest.model_dump(mode="json", by_alias=True)
            )
            manifest_hash = canonical_hash(
                manifest.model_dump(mode="json", by_alias=True)
            )
            attempt_id = self._id()
            operation_id = self._id()
            row = {
                "id": attempt_id,
                "project_id": command.project_id,
                "draft_id": command.draft_id,
                "operation_id": operation_id,
                "idempotency_key": command.idempotency_key,
                "request_fingerprint": fingerprint,
                **self._binding_snapshot(binding),
                "fencing_token": fencing_token,
                "lease_expires_at": now + PLANNING_GENERATION_LEASE_MS,
                "input_manifest_json": manifest_json,
                "input_manifest_hash": manifest_hash,
                "created_at": now,
                "updated_at": now,
            }
            if not await self.repository.insert_generation_attempt(
                session, row
            ):
                raise PlanningGenerationConflict()
            context = {
                "attempt": {**row, "status": "pending"},
                "fingerprint": fingerprint,
                "manifest_hash": manifest_hash,
                "basis": self._basis_snapshot(basis),
                "head": self._head_snapshot(head),
                "draft": self._draft_snapshot(draft),
                "binding": self._binding_snapshot(binding),
                "provider_authority_hash": self._provider_authority_hash(
                    binding
                ),
                "provider": dict(binding),
                "manifest": manifest,
            }
            return None, context

    async def _publish(self, command, context, output):
        if self._request_fingerprint(command) != context["fingerprint"]:
            raise PlanningGenerationConflict()
        raw_payload = output.model_dump(mode="json", by_alias=True)
        raw_json = canonical_json(raw_payload)
        raw_hash = canonical_hash(raw_payload)
        attempt_context = context["attempt"]
        async with self._transaction() as session:
            attempt = await self.repository.lock_generation_attempt(
                session,
                command.project_id,
                attempt_context["operation_id"],
            )
            if attempt is None:
                raise PlanningGenerationConflict()
            if attempt["status"] != "pending":
                return self._operation_result(attempt)
            if not self._attempt_is_owned(
                attempt, context
            ):
                raise PlanningGenerationConflict()

            try:
                project = await self.repository.lock_active_project(
                    session, command.project_id
                )
            except ProjectArchived:
                project = None
            basis = await self.repository.read_current_basis(
                session, command.project_id
            )
            head = await self.repository.lock_planning_head(
                session, command.project_id
            )
            draft = await self.repository.read_draft(
                session, command.project_id, command.draft_id
            )
            binding = await self.repository.lock_planning_binding(
                session, command.project_id
            )
            current = (
                project is not None
                and basis is not None
                and head is not None
                and draft is not None
                and self._basis_snapshot(basis) == context["basis"]
                and self._head_snapshot(head) == context["head"]
                and self._draft_snapshot(draft) == context["draft"]
                and self._binding_snapshot(binding) == context["binding"]
                and self._provider_authority_hash(binding)
                == context["provider_authority_hash"]
                and int(attempt["lease_expires_at"]) >= self._clock()
            )
            if not current:
                if not await self.repository.succeed_generation_attempt(
                    session,
                    project_id=command.project_id,
                    operation_id=attempt["operation_id"],
                    fencing_token=int(attempt["fencing_token"]),
                    result_content_json=raw_json,
                    result_content_hash=raw_hash,
                    updated_at=self._clock(),
                ):
                    terminal = (
                        await self.repository.lock_generation_attempt(
                            session,
                            command.project_id,
                            attempt["operation_id"],
                        )
                    )
                    if terminal is not None and terminal["status"] != "pending":
                        return self._operation_result(terminal)
                    raise PlanningGenerationConflict()
                terminal = await self.repository.lock_generation_attempt(
                    session,
                    command.project_id,
                    attempt["operation_id"],
                )
                return self._operation_result(terminal)

            try:
                previous_draft = self._planning_from_json(
                    draft["content_json"]
                )
                previous_confirmed = (
                    self._planning_from_json(head["content_json"])
                    if int(head["revision"]) > 0
                    else None
                )
                normalized = normalize_planning_aggregate(
                    output,
                    previous_confirmed=previous_confirmed,
                    previous_draft=previous_draft,
                    id_factory=self._id,
                )
            except (
                PlanningDomainError,
                ValidationError,
                TypeError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                UnicodeError,
            ):
                return await self._fail_locked(
                    session,
                    attempt,
                    "PlanningProviderResultInvalid",
                )

            content_payload = normalized.model_dump(
                mode="json", by_alias=True
            )
            content_json = canonical_json(content_payload)
            if await self.repository.load_generation_result_into_draft(
                session,
                project_id=command.project_id,
                draft_id=command.draft_id,
                expected_revision=command.draft_revision,
                expected_hash=command.draft_hash,
                operation_id=attempt["operation_id"],
                fencing_token=int(attempt["fencing_token"]),
                content_json=content_json,
                content_hash=normalized.content_hash,
                loaded_at=self._clock(),
            ):
                terminal = await self.repository.lock_generation_attempt(
                    session,
                    command.project_id,
                    attempt["operation_id"],
                )
                return self._operation_result(terminal)

            terminal = await self.repository.lock_generation_attempt(
                session, command.project_id, attempt["operation_id"]
            )
            if terminal is not None and terminal["status"] != "pending":
                return self._operation_result(terminal)
            raise PlanningGenerationConflict()

    async def _fail(self, context, failure_code):
        attempt_context = context["attempt"]
        async with self._transaction() as session:
            attempt = await self.repository.lock_generation_attempt(
                session,
                attempt_context["project_id"],
                attempt_context["operation_id"],
            )
            if attempt is None:
                raise PlanningGenerationConflict()
            if attempt["status"] != "pending":
                return self._operation_result(attempt)
            return await self._fail_locked(
                session, attempt, failure_code
            )

    async def _fail_locked(self, session, attempt, failure_code):
        if not await self.repository.fail_generation_attempt(
            session,
            project_id=attempt["project_id"],
            operation_id=attempt["operation_id"],
            fencing_token=int(attempt["fencing_token"]),
            failure_code=failure_code,
            updated_at=self._clock(),
        ):
            terminal = await self.repository.lock_generation_attempt(
                session,
                attempt["project_id"],
                attempt["operation_id"],
            )
            if terminal is None or terminal["status"] == "pending":
                raise PlanningGenerationConflict()
            return self._operation_result(terminal)
        terminal = await self.repository.lock_generation_attempt(
            session,
            attempt["project_id"],
            attempt["operation_id"],
        )
        return self._operation_result(terminal)

    async def _settle_cancelled(self, context):
        try:
            await asyncio.shield(
                self._fail(context, "PlanningGenerationCancelled")
            )
        except BaseException:
            pass

    @classmethod
    def _manifest(cls, command, *, basis, draft):
        editable = cls._editable_draft(draft["content_json"])
        volumes = tuple(editable.volumes)
        premise = "；".join(
            f"{volume.title}：{volume.core_change}"
            for volume in volumes
        ) or "基于已确认创作依据规划未来分卷与情节线。"
        guardrails = tuple(
            rule
            for volume in volumes
            for rule in volume.forbidden_events
        )
        basis_snapshot = cls._basis_snapshot(basis)
        return PlanningGenerationManifest.model_validate(
            {
                "basis": {
                    "projectId": command.project_id,
                    "basisHash": canonical_hash(basis_snapshot),
                    "draftRevision": command.draft_revision,
                    "draftHash": command.draft_hash,
                },
                "draft": editable.model_dump(
                    mode="json", by_alias=True
                ),
                "storyContext": {
                    "premise": premise,
                    "continuityGuardrails": guardrails,
                },
            },
            strict=True,
        )

    @staticmethod
    def _editable_draft(value) -> DraftPlanningAggregate:
        persisted = PlanningGenerationService._planning_from_json(value)
        payload = persisted.model_dump(mode="json", by_alias=True)
        payload["activeStoryBlockRef"] = payload.pop(
            "activeStoryBlockId"
        )
        payload.pop("schemaVersion")
        payload.pop("contentHash")
        for block in payload["storyBlocks"]:
            block["volumeRef"] = block.pop("volumeId")
            block["plotRefs"] = block.pop("plotIds")
            for stage in block["stages"]:
                stage.pop("storyBlockId")
                for task in stage["sceneTasks"]:
                    task.pop("stageId")
        return DraftPlanningAggregate.model_validate(
            payload, strict=True
        )

    @staticmethod
    def _planning_from_json(value) -> PlanningAggregate:
        if isinstance(value, PlanningAggregate):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        return PlanningAggregate.model_validate(value, strict=True)

    @staticmethod
    def _basis_snapshot(basis):
        return {key: basis[key] for key in _BASIS_FIELDS}

    @staticmethod
    def _binding_snapshot(binding):
        if binding is None:
            return None
        return {key: binding[key] for key in _BINDING_FIELDS}

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

        return canonical_hash(
            {
                key: stable(binding[key])
                for key in _PROVIDER_AUTHORITY_FIELDS
            }
        )

    @staticmethod
    def _head_snapshot(head):
        return {
            "revision": int(head["revision"]),
            "planning_revision_id": head.get("planning_revision_id"),
            "content_hash": head.get("content_hash"),
        }

    @classmethod
    def _draft_snapshot(cls, draft):
        return {
            "draft_id": draft["id"],
            "draft_revision": int(draft["draft_revision"]),
            "draft_hash": draft["content_hash"],
            "base_head_revision": int(draft["base_head_revision"]),
            **{
                key: draft[key]
                for key in _BASIS_FIELDS
            },
        }

    @classmethod
    def _draft_authority_matches(cls, draft, basis, head):
        return (
            draft.get("status") == "active"
            and draft.get("active_slot") == 1
            and int(draft["base_head_revision"]) == int(head["revision"])
            and all(
                draft.get(key) == basis.get(key)
                for key in _BASIS_FIELDS
            )
        )

    @staticmethod
    def _draft_is_exact(command, draft):
        return (
            draft.get("id") == command.draft_id
            and int(draft.get("draft_revision") or 0)
            == command.draft_revision
            and draft.get("content_hash") == command.draft_hash
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
                and binding["model_name_snapshot"]
                == binding["model_name"]
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
    def _attempt_is_owned(attempt, context):
        expected = context["attempt"]
        return (
            attempt["project_id"] == expected["project_id"]
            and attempt["draft_id"] == expected["draft_id"]
            and attempt["operation_id"] == expected["operation_id"]
            and attempt["request_fingerprint"] == context["fingerprint"]
            and attempt["input_manifest_hash"]
            == context["manifest_hash"]
            and context["manifest_hash"]
            == canonical_hash(
                context["manifest"].model_dump(
                    mode="json", by_alias=True
                )
            )
            and int(attempt["fencing_token"])
            == int(expected["fencing_token"])
            and all(
                attempt[key] == context["binding"][key]
                for key in _BINDING_FIELDS
            )
        )

    @staticmethod
    def _request_fingerprint(command):
        return canonical_hash(
            {
                "projectId": command.project_id,
                "draftId": command.draft_id,
                "draftRevision": command.draft_revision,
                "draftHash": command.draft_hash,
                "authorInstructionsHash": canonical_hash(
                    command.author_instructions
                ),
            }
        )

    @staticmethod
    def _operation_result(row):
        loaded_revision = row.get("loaded_draft_revision")
        return PlanningOperationResult(
            operation_id=str(row["operation_id"]),
            status=row["status"],
            failure_code=row.get("failure_code"),
            model=PublicModelSummary(
                provider_id=str(row["provider_id"]),
                model_name=str(row["model_name_snapshot"]),
            ),
            loaded=loaded_revision is not None,
            loaded_draft_revision=(
                int(loaded_revision)
                if loaded_revision is not None
                else None
            ),
        )

    @staticmethod
    def _validate(command):
        if (
            not isinstance(command, GeneratePlanningDraft)
            or not isinstance(command.project_id, str)
            or not command.project_id.strip()
            or not isinstance(command.draft_id, str)
            or not command.draft_id.strip()
            or type(command.draft_revision) is not int
            or command.draft_revision < 1
            or _HASH.fullmatch(command.draft_hash or "") is None
            or _IDEMPOTENCY_KEY.fullmatch(
                command.idempotency_key or ""
            )
            is None
            or not isinstance(command.author_instructions, str)
            or len(command.author_instructions)
            > PLANNING_AUTHOR_INSTRUCTIONS_MAX_LENGTH
        ):
            raise PlanningGenerationNotReady()
        try:
            command.author_instructions.encode("utf-8")
        except UnicodeError:
            raise PlanningGenerationNotReady() from None


__all__ = (
    "GeneratePlanningDraft",
    "PLANNING_AUTHOR_INSTRUCTIONS_MAX_LENGTH",
    "PLANNING_GENERATION_LEASE_MS",
    "PlanningGenerationConflict",
    "PlanningGenerationIdempotencyConflict",
    "PlanningGenerationNotReady",
    "PlanningGenerationOperationNotFound",
    "PlanningGenerationService",
    "PlanningOperationResult",
    "PublicModelSummary",
)
