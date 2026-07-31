"""Owned, bounded, backend-only creation-Bible generation attempts."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import re
import time
from uuid import uuid4

from pydantic import ValidationError

from backend.domain.bibles import BiblePayload, canonical_bible_hash
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.provider_policy import provider_is_generation_ready
from backend.domain.seeds import SeedPayload
from backend.gateways.bible_provider import (
    BibleProviderError,
    BibleProviderHTTPError,
    BibleProviderParseError,
    BibleProviderTimeoutError,
    BibleProviderTransportError,
)
from backend.http_errors import ProjectArchived, PublicDomainError
from backend.prompts.bible import build_bible_messages
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
    provider_public_value_contains_secret,
)
from backend.services.bibles import BIBLE_POLICY_VERSION, BibleAlreadyConfirmed


BIBLE_GENERATION_POLICY_VERSION = "creation-bible-generation-v1"
BIBLE_GENERATION_LEASE_MS = 240_000
BIBLE_MAX_OUTPUT_TOKENS = 8_192
BIBLE_AUTHOR_INSTRUCTIONS_MAX_LENGTH = 4_000
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_TERMINAL = frozenset({"succeeded", "failed", "outcome_unknown"})


class BibleGenerationNotReady(PublicDomainError):
    status_code = 422
    code = "BibleGenerationNotReady"
    message = "Creation Bible generation prerequisites are unavailable"


class BibleGenerationConflict(PublicDomainError):
    status_code = 409
    code = "BibleGenerationConflict"
    message = "Creation Bible generation inputs changed; refresh and retry"


class BibleGenerationIdempotencyConflict(PublicDomainError):
    status_code = 409
    code = "BibleGenerationIdempotencyConflict"
    message = "Creation Bible generation key was used for another request"


class BibleGenerationProviderFailed(PublicDomainError):
    status_code = 422
    code = "BibleGenerationProviderFailed"
    message = "Creation Bible provider request failed"


class BibleGenerationParseFailed(PublicDomainError):
    status_code = 422
    code = "BibleGenerationParseFailed"
    message = "Creation Bible provider response was invalid"


class BibleGenerationRetryable(PublicDomainError):
    status_code = 503
    code = "BibleGenerationRetryable"
    message = "Creation Bible generation outcome is unknown; use a new key"
    retryable = True


class BibleGenerationAttemptNotFound(PublicDomainError):
    status_code = 404
    code = "BibleGenerationAttemptNotFound"
    message = "Creation Bible generation attempt not found"


@dataclass(frozen=True)
class GenerateBibleDraft:
    project_id: str
    author_instructions: str
    expected_draft_version: int
    expected_head_revision: int
    idempotency_key: str


@dataclass(frozen=True)
class BibleGenerationAttemptResult:
    attempt_id: str
    project_id: str
    status: str
    attempt_version: int
    provider_id: str
    model_name_snapshot: str
    input_manifest_hash: str
    result_hash: str | None
    public_error_code: str | None
    created_at: int
    completed_at: int | None


def _value(source, name, default=None):
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _dump(value) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError("generation input must be a mapping")


def _json_mapping(value) -> dict:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("stored generation input is invalid")
    return value


class BibleGenerationService:
    def __init__(
        self,
        repository,
        *,
        contract_service,
        transaction_factory,
        provider_gateway,
        id_factory=None,
        clock=None,
        failpoint=lambda _stage: None,
    ):
        self.repository = repository
        self.contract_service = contract_service
        self._transaction = transaction_factory
        self._gateway = provider_gateway
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._failpoint = failpoint

    @staticmethod
    def _validate(command: GenerateBibleDraft) -> None:
        if (
            not isinstance(command.project_id, str)
            or not command.project_id
            or not isinstance(command.author_instructions, str)
            or len(command.author_instructions)
            > BIBLE_AUTHOR_INSTRUCTIONS_MAX_LENGTH
            or type(command.expected_draft_version) is not int
            or command.expected_draft_version < 0
            or type(command.expected_head_revision) is not int
            or command.expected_head_revision < 0
            or not isinstance(command.idempotency_key, str)
            or not 1 <= len(command.idempotency_key) <= 64
            or _IDEMPOTENCY_KEY.fullmatch(command.idempotency_key) is None
        ):
            raise BibleGenerationNotReady()
        try:
            command.author_instructions.encode("utf-8")
        except UnicodeError:
            raise BibleGenerationNotReady() from None

    @classmethod
    def request_document(cls, command: GenerateBibleDraft) -> dict:
        return {
            "projectId": command.project_id,
            "authorInstructions": {
                "hash": canonical_hash(command.author_instructions),
                "length": len(command.author_instructions),
            },
            "expectedDraftVersion": command.expected_draft_version,
            "expectedHeadRevision": command.expected_head_revision,
            "policyVersion": BIBLE_GENERATION_POLICY_VERSION,
        }

    @classmethod
    def request_hash(cls, command: GenerateBibleDraft) -> str:
        return canonical_hash(cls.request_document(command))

    @staticmethod
    def _attempt_result(row) -> BibleGenerationAttemptResult:
        return BibleGenerationAttemptResult(
            attempt_id=row["id"],
            project_id=row["project_id"],
            status=row["status"],
            attempt_version=int(row["attempt_version"]),
            provider_id=row["provider_id"],
            model_name_snapshot=row["model_name_snapshot"],
            input_manifest_hash=row["input_manifest_hash"],
            result_hash=row.get("result_hash"),
            public_error_code=row.get("public_error_code"),
            created_at=int(row["created_at"]),
            completed_at=(
                int(row["completed_at"])
                if row.get("completed_at") is not None
                else None
            ),
        )

    @staticmethod
    def _basis(contract) -> dict:
        seed = _value(contract, "seed_ref")
        binding = _value(contract, "binding_ref")
        return {
            "selection_revision": int(
                _value(contract, "selection_revision")
            ),
            "seed_id": _value(seed, "id"),
            "seed_revision_id": _value(seed, "revision_id"),
            "seed_hash": _value(seed, "content_hash"),
            "contract_revision": int(_value(contract, "revision")),
            "creation_contract_id": _value(
                contract, "creation_contract_id"
            ),
            "creation_hash": _value(contract, "creation_hash"),
            "style_contract_id": _value(contract, "style_contract_id"),
            "style_hash": _value(contract, "style_hash"),
            "binding_revision_id": _value(binding, "id"),
            "binding_hash": _value(binding, "content_hash"),
        }

    @staticmethod
    def _draft_fact(draft) -> dict:
        if draft is None:
            return {"exists": False, "version": 0}
        return {
            "exists": True,
            "id": draft["id"],
            "version": int(draft["draft_version"]),
            "hash": draft["content_hash"],
            "baseHeadRevision": int(draft["base_head_revision"]),
            "selectionRevision": int(draft["selection_revision"]),
            "contractRevision": int(draft["contract_revision"]),
            "creationHash": draft["creation_hash"],
            "styleHash": draft["style_hash"],
            "bindingRevisionId": draft.get("binding_revision_id"),
            "bindingHash": draft.get("binding_hash"),
        }

    @classmethod
    def _manifest(
        cls,
        command,
        *,
        basis,
        contract,
        binding,
        draft,
        head,
    ) -> dict:
        style_refs = tuple(_value(contract, "style_refs", ()) or ())
        experience_refs = tuple(
            _value(contract, "experience_card_refs", ()) or ()
        )
        corpus_refs = tuple(
            _value(contract, "corpus_source_refs", ()) or ()
        )
        return {
            "selection": {
                "revision": basis["selection_revision"],
                "seedId": basis["seed_id"],
                "seedRevisionId": basis["seed_revision_id"],
                "seedHash": basis["seed_hash"],
            },
            "contract": {
                "revision": basis["contract_revision"],
                "creationContractId": basis["creation_contract_id"],
                "creationHash": basis["creation_hash"],
                "styleContractId": basis["style_contract_id"],
                "styleHash": basis["style_hash"],
            },
            "styles": [
                {
                    "role": _value(ref, "role"),
                    "id": _value(ref, "id"),
                    "revision": int(_value(ref, "revision")),
                    "hash": _value(
                        ref,
                        "contentHash",
                        _value(ref, "content_hash"),
                    ),
                }
                for ref in style_refs
            ],
            "experienceCards": [
                {
                    "id": _value(ref, "id"),
                    "revision": int(_value(ref, "revision")),
                    "hash": _value(
                        ref,
                        "contentHash",
                        _value(ref, "content_hash"),
                    ),
                }
                for ref in experience_refs
            ],
            "corpus": [
                {
                    "sourceId": _value(ref, "id"),
                    "revisionId": _value(ref, "revisionId"),
                    "revision": int(_value(ref, "revision")),
                    "hash": _value(
                        ref,
                        "contentHash",
                        _value(ref, "content_hash"),
                    ),
                    "fragments": [
                        {
                            "chapterId": _value(fragment, "chapterId"),
                            "fragmentId": _value(fragment, "fragmentId"),
                            "fragmentHash": _value(
                                fragment, "fragmentHash"
                            ),
                            "referenceUse": _value(
                                fragment, "referenceUse"
                            ),
                        }
                        for fragment in (
                            _value(ref, "fragments", ()) or ()
                        )
                    ],
                }
                for ref in corpus_refs
            ],
            "counts": {
                "styles": len(style_refs),
                "experienceCards": len(experience_refs),
                "corpusSources": len(corpus_refs),
                "corpusFragments": sum(
                    len(_value(ref, "fragments", ()) or ())
                    for ref in corpus_refs
                ),
            },
            "binding": {
                "revisionId": basis["binding_revision_id"],
                "hash": basis["binding_hash"],
                "taskKey": "planning",
            },
            "provider": {
                "providerId": binding["id"],
                "modelName": binding["model_name"],
                "profileRevision": int(binding["revision"]),
            },
            "authorInstructions": {
                "hash": canonical_hash(command.author_instructions),
                "length": len(command.author_instructions),
            },
            "draft": cls._draft_fact(draft),
            "head": {"revision": int(head["revision"])},
            "policyVersion": BIBLE_GENERATION_POLICY_VERSION,
        }

    @staticmethod
    def _provider_ready(binding, basis) -> bool:
        return (
            binding is not None
            and binding.get("binding_revision_id")
            == basis["binding_revision_id"]
            and binding.get("binding_hash") == basis["binding_hash"]
            and binding.get("resolution_status") == "bound"
            and binding.get("provider_id") == binding.get("id")
            and binding.get("model_name_snapshot")
            == binding.get("model_name")
            and provider_is_generation_ready(binding)
        )

    @staticmethod
    def _expected_state(command, draft, head) -> bool:
        return (
            head is not None
            and int(head.get("revision", -1))
            == command.expected_head_revision
            and (
                (
                    command.expected_draft_version == 0
                    and draft is None
                )
                or (
                    draft is not None
                    and int(draft.get("draft_version", -1))
                    == command.expected_draft_version
                    and int(draft.get("base_head_revision", -1))
                    == command.expected_head_revision
                )
            )
        )

    async def _load_inputs(self, session, command, *, build_prompt: bool):
        contract = await self.contract_service.get_head(
            command.project_id,
            session=session,
            for_update=True,
        )
        if _value(contract, "contract_ready") is not True:
            raise BibleGenerationNotReady()
        try:
            basis = self._basis(contract)
        except (TypeError, ValueError, KeyError, AttributeError):
            raise BibleGenerationNotReady() from None
        if not all(
            isinstance(basis[key], str) and bool(basis[key])
            for key in (
                "seed_id",
                "seed_revision_id",
                "seed_hash",
                "creation_contract_id",
                "creation_hash",
                "style_contract_id",
                "style_hash",
                "binding_revision_id",
                "binding_hash",
            )
        ):
            raise BibleGenerationNotReady()

        draft = await self.repository.lock_active_draft(
            session, command.project_id
        )
        head = await self.repository.lock_bible_head(
            session, command.project_id
        )
        if not self._expected_state(command, draft, head):
            raise BibleGenerationConflict()

        binding = await self.repository.lock_planning_binding(
            session, command.project_id
        )
        if not self._provider_ready(binding, basis):
            raise BibleGenerationNotReady()

        try:
            seed_row = await self.repository.read_seed_revision(
                session,
                command.project_id,
                basis["seed_revision_id"],
                lock=True,
            )
            if (
                seed_row is None
                or seed_row.get("seed_id") != basis["seed_id"]
                or seed_row.get("seed_hash") != basis["seed_hash"]
            ):
                raise ValueError("seed drift")
            seed = SeedPayload.model_validate(
                _json_mapping(seed_row["payload_json"]),
                strict=True,
            )

            experience_cards = []
            for ref in tuple(
                _value(contract, "experience_card_refs", ()) or ()
            ):
                row = await self.repository.read_experience_revision(
                    session,
                    _value(ref, "id"),
                    lock=True,
                )
                expected_hash = _value(
                    ref,
                    "contentHash",
                    _value(ref, "content_hash"),
                )
                if (
                    row is None
                    or int(row.get("revision") or 0)
                    != int(_value(ref, "revision"))
                    or row.get("content_hash") != expected_hash
                ):
                    raise ValueError("experience drift")
                payload = _json_mapping(row["payload_json"])
                if canonical_hash(payload) != expected_hash:
                    raise ValueError("experience hash mismatch")
                experience_cards.append(
                    {
                        "id": _value(ref, "id"),
                        "revision": int(_value(ref, "revision")),
                        "contentHash": expected_hash,
                        "payload": payload,
                    }
                )

            corpus_fragments = []
            for source in tuple(
                _value(contract, "corpus_source_refs", ()) or ()
            ):
                refs = tuple(_value(source, "fragments", ()) or ())
                rows = await self.repository.read_corpus_fragments(
                    session,
                    _value(source, "id"),
                    _value(source, "revisionId"),
                    tuple(_value(ref, "fragmentId") for ref in refs),
                    lock=True,
                )
                by_id = {row["fragment_id"]: row for row in rows}
                if len(by_id) != len(refs):
                    raise ValueError("corpus fragment drift")
                for ref in refs:
                    row = by_id.get(_value(ref, "fragmentId"))
                    if (
                        row is None
                        or row.get("source_id") != _value(source, "id")
                        or row.get("source_revision_id")
                        != _value(source, "revisionId")
                        or int(row.get("source_revision") or 0)
                        != int(_value(source, "revision"))
                        or row.get("source_hash")
                        != _value(
                            source,
                            "contentHash",
                            _value(source, "content_hash"),
                        )
                        or row.get("chapter_id")
                        != _value(ref, "chapterId")
                        or row.get("fragment_hash")
                        != _value(ref, "fragmentHash")
                    ):
                        raise ValueError("corpus fragment drift")
                    corpus_fragments.append(
                        {
                            "sourceId": _value(source, "id"),
                            "sourceRevisionId": _value(
                                source, "revisionId"
                            ),
                            "fragmentId": _value(ref, "fragmentId"),
                            "fragmentHash": _value(
                                ref, "fragmentHash"
                            ),
                            "referenceUse": _value(
                                ref, "referenceUse"
                            ),
                            "text": row["normalized_text"],
                        }
                    )
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
            UnicodeError,
        ):
            raise BibleGenerationNotReady() from None

        manifest = self._manifest(
            command,
            basis=basis,
            contract=contract,
            binding=binding,
            draft=draft,
            head=head,
        )
        messages = None
        if build_prompt:
            try:
                messages = build_bible_messages(
                    seed=seed.model_dump(mode="json"),
                    creation_contract=_dump(
                        _value(contract, "creation_contract")
                    ),
                    style_contract=_dump(
                        _value(contract, "style_contract")
                    ),
                    experience_cards=tuple(experience_cards),
                    corpus_fragments=tuple(corpus_fragments),
                    author_instructions=command.author_instructions,
                )
            except (TypeError, ValueError):
                raise BibleGenerationNotReady() from None

        try:
            temperature = float(binding["temperature"])
            max_output_tokens = min(
                int(binding["max_output_tokens"]),
                BIBLE_MAX_OUTPUT_TOKENS,
            )
            max_context_tokens = int(binding["max_context_tokens"])
            if (
                not math.isfinite(temperature)
                or temperature < 0
                or max_output_tokens <= 0
                or max_context_tokens <= 0
            ):
                raise ValueError("invalid provider generation budget")
            if messages is not None:
                prompt_bytes = len(canonical_json(messages).encode("utf-8"))
                if prompt_bytes + max_output_tokens > max_context_tokens:
                    raise ValueError("Bible context budget exceeded")
        except (KeyError, TypeError, ValueError, OverflowError):
            raise BibleGenerationNotReady() from None

        provider = dict(binding)
        provider["base_url"] = str(binding["base_url"]).strip()
        provider["api_key"] = str(binding["api_key"]).strip()
        secrets = normalize_provider_secrets(
            (provider["api_key"], provider["base_url"])
        )
        public_provider = {
            "providerId": binding["id"],
            "modelName": binding["model_name"],
            "profileRevision": int(binding["revision"]),
        }
        if (
            provider_public_fields_contain_secret(public_provider, secrets)
            or provider_public_value_contains_secret(manifest, secrets)
            or (
                messages is not None
                and provider_public_value_contains_secret(messages, secrets)
            )
            or provider_public_value_contains_secret(
                command.author_instructions,
                secrets,
            )
        ):
            raise BibleGenerationNotReady()
        return {
            "basis": basis,
            "contract": contract,
            "binding": binding,
            "provider": provider,
            "manifest": manifest,
            "messages": messages,
            "generation_config": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
            "draft": draft,
            "head": head,
        }

    async def _reserve(self, command, identity):
        request_hash = self.request_hash(command)
        async with self._transaction() as session:
            project = await self.repository.lock_project(
                session, command.project_id
            )
            if project is None:
                raise BibleGenerationNotReady()
            head = await self.repository.lock_bible_head(
                session, command.project_id
            )
            if head is not None and int(head.get("revision") or 0) > 0:
                raise BibleAlreadyConfirmed()
            existing = (
                await self.repository.lock_generation_attempt_by_key(
                    session,
                    command.project_id,
                    command.idempotency_key,
                )
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise BibleGenerationIdempotencyConflict()
                if existing["status"] in _TERMINAL:
                    return self._attempt_result(existing), None
                if existing["status"] not in {"reserved", "running"}:
                    raise BibleGenerationConflict()
                if int(existing["lease_expires_at"]) > self._clock():
                    return self._attempt_result(existing), None
                finished = await self.repository.finish_generation_attempt(
                    session,
                    project_id=command.project_id,
                    attempt_id=existing["id"],
                    owner_token=existing["owner_token"],
                    expected_attempt_version=int(
                        existing["attempt_version"]
                    ),
                    status="outcome_unknown",
                    public_error_code=BibleGenerationRetryable.code,
                    completed_at=self._clock(),
                )
                if not finished:
                    raise BibleGenerationConflict()
                terminal = await self.repository.lock_generation_attempt(
                    session,
                    command.project_id,
                    existing["id"],
                )
                return self._attempt_result(terminal), None

            inputs = await self._load_inputs(
                session,
                command,
                build_prompt=True,
            )
            owner_token = self._id()
            attempt_id = self._id()
            identity.update(
                project_id=command.project_id,
                attempt_id=attempt_id,
                owner_token=owner_token,
                attempt_version=1,
            )
            now = self._clock()
            basis = inputs["basis"]
            manifest = inputs["manifest"]
            row = {
                "id": attempt_id,
                "project_id": command.project_id,
                **basis,
                "provider_id": inputs["binding"]["id"],
                "model_name_snapshot": inputs["binding"]["model_name"],
                "policy_version": BIBLE_GENERATION_POLICY_VERSION,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "input_manifest_json": canonical_json(manifest),
                "input_manifest_hash": canonical_hash(manifest),
                "status": "running",
                "owner_token": owner_token,
                "lease_expires_at": now + BIBLE_GENERATION_LEASE_MS,
                "attempt_version": 1,
                "result_json": None,
                "result_hash": None,
                "public_error_code": None,
                "created_at": now,
                "completed_at": None,
            }
            if not await self.repository.insert_generation_attempt(
                session, row
            ):
                raise BibleGenerationConflict()
            return None, {
                **inputs,
                "attempt": row,
                "identity": dict(identity),
            }

    async def _terminalize(self, context, *, status, code):
        identity = context["identity"]
        async with self._transaction() as session:
            row = await self.repository.lock_generation_attempt(
                session,
                identity["project_id"],
                identity["attempt_id"],
            )
            if row is None:
                raise BibleGenerationRetryable()
            if row["status"] in _TERMINAL:
                return self._attempt_result(row)
            changed = await self.repository.finish_generation_attempt(
                session,
                project_id=identity["project_id"],
                attempt_id=identity["attempt_id"],
                owner_token=identity["owner_token"],
                expected_attempt_version=identity["attempt_version"],
                status=status,
                public_error_code=code,
                completed_at=self._clock(),
            )
            if not changed:
                row = await self.repository.lock_generation_attempt(
                    session,
                    identity["project_id"],
                    identity["attempt_id"],
                )
                if row is None or row["status"] not in _TERMINAL:
                    raise BibleGenerationRetryable()
                return self._attempt_result(row)
            row = await self.repository.lock_generation_attempt(
                session,
                identity["project_id"],
                identity["attempt_id"],
            )
            return self._attempt_result(row)

    async def _settle_cancelled_attempt(self, context):
        try:
            await asyncio.shield(
                self._terminalize(
                    context,
                    status="outcome_unknown",
                    code=BibleGenerationRetryable.code,
                )
            )
        except BaseException:
            pass

    @staticmethod
    def _draft_basis_current(draft, basis, head_revision):
        return (
            int(draft.get("base_head_revision", -1)) == head_revision
            and int(draft.get("selection_revision", -1))
            == basis["selection_revision"]
            and draft.get("seed_id") == basis["seed_id"]
            and draft.get("seed_revision_id") == basis["seed_revision_id"]
            and draft.get("seed_hash") == basis["seed_hash"]
            and int(draft.get("contract_revision", -1))
            == basis["contract_revision"]
            and draft.get("creation_contract_id")
            == basis["creation_contract_id"]
            and draft.get("creation_hash") == basis["creation_hash"]
            and draft.get("style_contract_id")
            == basis["style_contract_id"]
            and draft.get("style_hash") == basis["style_hash"]
            and draft.get("policy_version") == BIBLE_POLICY_VERSION
        )

    @staticmethod
    def _draft_row(
        *,
        project_id,
        draft_id,
        payload,
        basis,
        binding_revision_id,
        binding_hash,
        base_head_revision,
        draft_version,
        created_at,
        updated_at,
    ):
        return {
            "id": draft_id,
            "project_id": project_id,
            "active_slot": 1,
            "base_head_revision": base_head_revision,
            **basis,
            "binding_revision_id": binding_revision_id,
            "binding_hash": binding_hash,
            "policy_version": BIBLE_POLICY_VERSION,
            "draft_json": canonical_json(payload),
            "content_hash": canonical_bible_hash(payload),
            "draft_version": draft_version,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    async def _publish(self, command, context, output):
        identity = context["identity"]
        completed_at = self._clock()
        async with self._transaction() as session:
            project = await self.repository.lock_project(
                session, command.project_id
            )
            attempt = await self.repository.lock_generation_attempt(
                session,
                command.project_id,
                identity["attempt_id"],
            )
            if (
                project is None
                or attempt is None
                or attempt.get("status") != "running"
                or attempt.get("owner_token") != identity["owner_token"]
                or int(attempt.get("attempt_version") or 0)
                != identity["attempt_version"]
            ):
                raise BibleGenerationConflict()
            try:
                current = await self._load_inputs(
                    session,
                    command,
                    build_prompt=False,
                )
                if (
                    canonical_hash(current["manifest"])
                    != attempt["input_manifest_hash"]
                    or current["basis"] != context["basis"]
                ):
                    raise BibleGenerationConflict()
            except PublicDomainError:
                changed = await self.repository.finish_generation_attempt(
                    session,
                    project_id=command.project_id,
                    attempt_id=identity["attempt_id"],
                    owner_token=identity["owner_token"],
                    expected_attempt_version=identity["attempt_version"],
                    status="failed",
                    public_error_code=BibleGenerationConflict.code,
                    completed_at=completed_at,
                )
                if not changed:
                    raise BibleGenerationRetryable()
                terminal = await self.repository.lock_generation_attempt(
                    session,
                    command.project_id,
                    identity["attempt_id"],
                )
                return self._attempt_result(terminal)

            basis = current["basis"]
            draft = current["draft"]
            head_revision = int(current["head"]["revision"])
            now = completed_at
            if draft is None:
                row = self._draft_row(
                    project_id=command.project_id,
                    draft_id=self._id(),
                    payload=output,
                    basis=basis,
                    binding_revision_id=basis["binding_revision_id"],
                    binding_hash=basis["binding_hash"],
                    base_head_revision=head_revision,
                    draft_version=1,
                    created_at=now,
                    updated_at=now,
                )
                if not await self.repository.insert_draft(session, row):
                    raise BibleGenerationConflict()
            elif self._draft_basis_current(
                draft, basis, head_revision
            ):
                row = self._draft_row(
                    project_id=command.project_id,
                    draft_id=draft["id"],
                    payload=output,
                    basis=basis,
                    binding_revision_id=basis["binding_revision_id"],
                    binding_hash=basis["binding_hash"],
                    base_head_revision=head_revision,
                    draft_version=int(draft["draft_version"]) + 1,
                    created_at=int(draft["created_at"]),
                    updated_at=now,
                )
                if not await self.repository.cas_update_draft(
                    session,
                    row,
                    int(draft["draft_version"]),
                    update_binding=True,
                ):
                    raise BibleGenerationConflict()
            else:
                if not await self.repository.deactivate_active_draft(
                    session,
                    command.project_id,
                    draft["id"],
                    int(draft["draft_version"]),
                    draft["content_hash"],
                ):
                    raise BibleGenerationConflict()
                row = self._draft_row(
                    project_id=command.project_id,
                    draft_id=self._id(),
                    payload=output,
                    basis=basis,
                    binding_revision_id=basis["binding_revision_id"],
                    binding_hash=basis["binding_hash"],
                    base_head_revision=head_revision,
                    draft_version=1,
                    created_at=now,
                    updated_at=now,
                )
                if not await self.repository.insert_draft(session, row):
                    raise BibleGenerationConflict()

            self._failpoint("after_draft_write")
            result_json = canonical_json(output)
            result_hash = canonical_bible_hash(output)
            if not await self.repository.succeed_generation_attempt(
                session,
                project_id=command.project_id,
                attempt_id=identity["attempt_id"],
                owner_token=identity["owner_token"],
                expected_attempt_version=identity["attempt_version"],
                result_json=result_json,
                result_hash=result_hash,
                completed_at=completed_at,
            ):
                raise BibleGenerationConflict()
            terminal = await self.repository.lock_generation_attempt(
                session,
                command.project_id,
                identity["attempt_id"],
            )
            return self._attempt_result(terminal)

    async def generate(
        self,
        command: GenerateBibleDraft,
    ) -> BibleGenerationAttemptResult:
        self._validate(command)
        identity = {}
        try:
            replay, context = await self._reserve(command, identity)
        except asyncio.CancelledError:
            if identity:
                await self._settle_cancelled_attempt(
                    {"identity": dict(identity)}
                )
            raise
        except PublicDomainError:
            raise
        except Exception:
            if identity:
                try:
                    return await asyncio.shield(
                        self._terminalize(
                            {"identity": dict(identity)},
                            status="outcome_unknown",
                            code=BibleGenerationRetryable.code,
                        )
                    )
                except Exception:
                    pass
            raise BibleGenerationRetryable() from None
        if replay is not None:
            return replay
        assert context is not None

        try:
            output = await self._gateway.generate(
                provider=context["provider"],
                messages=context["messages"],
                generation_config=context["generation_config"],
            )
        except asyncio.CancelledError:
            await self._settle_cancelled_attempt(context)
            raise
        except BibleProviderParseError:
            return await self._terminalize(
                context,
                status="failed",
                code=BibleGenerationParseFailed.code,
            )
        except BibleProviderHTTPError:
            return await self._terminalize(
                context,
                status="failed",
                code=BibleGenerationProviderFailed.code,
            )
        except (BibleProviderTimeoutError, BibleProviderTransportError):
            return await self._terminalize(
                context,
                status="outcome_unknown",
                code=BibleGenerationRetryable.code,
            )
        except BibleProviderError:
            return await self._terminalize(
                context,
                status="outcome_unknown",
                code=BibleGenerationRetryable.code,
            )
        except Exception:
            return await self._terminalize(
                context,
                status="outcome_unknown",
                code=BibleGenerationRetryable.code,
            )
        if not isinstance(output, BiblePayload):
            return await self._terminalize(
                context,
                status="failed",
                code=BibleGenerationParseFailed.code,
            )
        try:
            return await self._publish(command, context, output)
        except asyncio.CancelledError:
            await self._settle_cancelled_attempt(context)
            raise
        except (
            BibleGenerationConflict,
            BibleGenerationNotReady,
            ProjectArchived,
        ):
            return await self._terminalize(
                context,
                status="failed",
                code=BibleGenerationConflict.code,
            )
        except Exception:
            return await self._terminalize(
                context,
                status="outcome_unknown",
                code=BibleGenerationRetryable.code,
            )

    async def get_attempt(
        self,
        project_id: str,
        attempt_id: str,
    ) -> BibleGenerationAttemptResult:
        if (
            not isinstance(project_id, str)
            or not project_id
            or not isinstance(attempt_id, str)
            or not attempt_id
        ):
            raise BibleGenerationAttemptNotFound()
        async with self._transaction() as session:
            project = await self.repository.read_project(session, project_id)
            row = await self.repository.read_generation_attempt(
                session,
                project_id,
                attempt_id,
            )
            if project is None or row is None:
                raise BibleGenerationAttemptNotFound()
            return self._attempt_result(row)


__all__ = (
    "BIBLE_AUTHOR_INSTRUCTIONS_MAX_LENGTH",
    "BIBLE_GENERATION_LEASE_MS",
    "BIBLE_GENERATION_POLICY_VERSION",
    "BIBLE_MAX_OUTPUT_TOKENS",
    "BibleGenerationAttemptNotFound",
    "BibleGenerationAttemptResult",
    "BibleGenerationConflict",
    "BibleGenerationIdempotencyConflict",
    "BibleGenerationNotReady",
    "BibleGenerationParseFailed",
    "BibleGenerationProviderFailed",
    "BibleGenerationRetryable",
    "BibleGenerationService",
    "GenerateBibleDraft",
)
