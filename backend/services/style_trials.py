"""Backend-only, non-contract style-trial attempt orchestration."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import math
import time
from uuid import uuid4

from pydantic import ValidationError

from backend.domain.assets import StylePromptPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.provider_policy import provider_is_generation_ready
from backend.domain.seeds import decode_seed_revision
from backend.domain.story_engines import StoryEngineOption
from backend.domain.style_trials import (
    GenerateStyleTrial,
    SafeProviderIdentity,
    StyleTrialFailure,
    StyleTrialProviderOutput,
    StyleTrialResult,
    style_trial_value_contains_secret,
)
from backend.gateways.style_trial_provider import StyleTrialProviderError
from backend.prompts.style_trial import build_style_trial_messages
from backend.repositories.style_trials import input_facts_hash
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
    provider_public_value_contains_secret,
)


STYLE_TRIAL_POLICY_VERSION = "style-trial-policy-v1"
STYLE_TRIAL_MAX_OUTPUT_TOKENS = 4_096
STYLE_TRIAL_RUNNING_STALE_MS = 240_000
_OUTCOME_UNKNOWN = "STYLE_TRIAL_OUTCOME_UNKNOWN"


def _json_mapping(value: object) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("stored JSON is invalid")
    return value


def _parse_engine(value: object) -> StoryEngineOption:
    document = _json_mapping(value)
    normalized = dict(document)
    for field in (
        "ensembleRoles",
        "satisfactionSources",
        "longFormVariation",
        "risks",
    ):
        if isinstance(normalized.get(field), list):
            normalized[field] = tuple(normalized[field])
    return StoryEngineOption.model_validate(normalized, strict=True)


def _parse_style(value: object) -> StylePromptPayload:
    document = _json_mapping(value)
    normalized = dict(document)
    for field in (
        "applicability",
        "non_applicability",
        "preferred_techniques",
        "risks",
    ):
        if isinstance(normalized.get(field), list):
            normalized[field] = tuple(normalized[field])
    return StylePromptPayload.model_validate(normalized, strict=True)


class StyleTrialService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        provider_gateway,
        id_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self._transaction = transaction_factory
        self._gateway = provider_gateway
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    @staticmethod
    def request_document(command: GenerateStyleTrial) -> dict:
        return {
            "projectId": command.project_id,
            "selectionRevision": command.selection_revision,
            "engineOptionId": command.engine_option_id,
            "engineHash": command.engine_hash,
            "primaryStyleRevisionId": command.primary_style_revision_id,
            "primaryStyleHash": command.primary_style_hash,
            "secondaryStyleRevisionId": command.secondary_style_revision_id,
            "secondaryStyleHash": command.secondary_style_hash,
            "authorScenario": command.author_scenario,
            "policyVersion": STYLE_TRIAL_POLICY_VERSION,
        }

    @classmethod
    def request_hash(cls, command: GenerateStyleTrial) -> str:
        return canonical_hash(cls.request_document(command))

    @staticmethod
    def _style_rows_match(command: GenerateStyleTrial, rows: tuple[dict, ...]) -> bool:
        expected = [
            ("primary", command.primary_style_revision_id, command.primary_style_hash),
            *((
                (
                    "secondary",
                    command.secondary_style_revision_id,
                    command.secondary_style_hash,
                ),
            ) if command.secondary_style_revision_id is not None else ()),
        ]
        if len(rows) != len(expected):
            return False
        for row, (role, revision_id, content_hash) in zip(rows, expected, strict=True):
            if (
                row.get("role") != role
                or row.get("id") != revision_id
                or row.get("content_hash") != content_hash
                or row.get("status") != "active"
                or row.get("head_id") != revision_id
                or row.get("head_revision") != row.get("revision")
                or row.get("head_hash") != content_hash
            ):
                return False
        return True

    @classmethod
    def _validate_inputs(cls, command: GenerateStyleTrial, inputs: dict) -> None:
        project = inputs.get("project")
        selection = inputs.get("selection")
        engine = inputs.get("engine")
        provider = inputs.get("provider")
        styles = tuple(inputs.get("styles") or ())
        if project is None or project.get("archived_at") is not None:
            raise StyleTrialFailure("STYLE_TRIAL_NOT_FOUND")
        if not isinstance(selection, dict) or not isinstance(engine, dict):
            raise StyleTrialFailure("STYLE_TRIAL_NOT_READY")
        if (
            selection.get("selection_revision") != command.selection_revision
            or not selection.get("seed_id")
            or not selection.get("seed_revision_id")
            or not selection.get("seed_hash")
            or engine.get("id") != command.engine_option_id
            or engine.get("content_hash") != command.engine_hash
            or engine.get("status") != "succeeded"
            or engine.get("selection_revision") != command.selection_revision
            or engine.get("seed_revision_id") != selection.get("seed_revision_id")
            or engine.get("seed_hash") != selection.get("seed_hash")
            or not cls._style_rows_match(command, styles)
        ):
            raise StyleTrialFailure("STYLE_TRIAL_INPUT_CHANGED")
        if (
            not isinstance(provider, dict)
            or inputs.get("resolution_status") != "bound"
            or inputs.get("provider_id") != provider.get("id")
            or inputs.get("model_name_snapshot") != provider.get("model_name")
            or not inputs.get("binding_revision_id")
            or not inputs.get("binding_hash")
            or type(provider.get("revision")) is not int
            or provider["revision"] < 0
            or not provider_is_generation_ready(provider)
        ):
            raise StyleTrialFailure("STYLE_TRIAL_NOT_READY")
        secrets = normalize_provider_secrets(
            (provider.get("api_key"), provider.get("base_url"))
        )
        public_identity = {
            "providerId": provider.get("id"),
            "providerType": provider.get("provider_type"),
            "modelName": provider.get("model_name"),
            "profileRevision": provider.get("revision"),
        }
        if provider_public_fields_contain_secret(public_identity, secrets):
            raise StyleTrialFailure("STYLE_TRIAL_NOT_READY")
        try:
            decode_seed_revision(selection["payload_json"])
            _parse_engine(engine["payload_json"])
            for row in styles:
                _parse_style(row["payload_json"])
        except (KeyError, TypeError, ValueError, ValidationError, RecursionError):
            raise StyleTrialFailure("STYLE_TRIAL_NOT_READY") from None

    @staticmethod
    def _generation_config(provider: dict) -> dict:
        try:
            temperature = float(provider["temperature"])
            max_tokens = int(provider["max_output_tokens"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise StyleTrialFailure("STYLE_TRIAL_NOT_READY") from None
        if not math.isfinite(temperature) or temperature < 0 or max_tokens <= 0:
            raise StyleTrialFailure("STYLE_TRIAL_NOT_READY")
        return {
            "temperature": temperature,
            "maxOutputTokens": min(max_tokens, STYLE_TRIAL_MAX_OUTPUT_TOKENS),
        }

    @staticmethod
    def _safe_provider(inputs: dict) -> SafeProviderIdentity:
        provider = inputs["provider"]
        return SafeProviderIdentity(
            provider_id=provider["id"],
            provider_type=provider["provider_type"],
            model_name=provider["model_name"],
            profile_revision=int(provider["revision"]),
        )

    @classmethod
    def _manifest(cls, command: GenerateStyleTrial, inputs: dict) -> dict:
        selection = inputs["selection"]
        engine = inputs["engine"]
        return {
            "selection": {
                "revision": int(selection["selection_revision"]),
                "seedId": selection["seed_id"],
                "seedRevisionId": selection["seed_revision_id"],
                "seedHash": selection["seed_hash"],
            },
            "engine": {
                "optionId": engine["id"],
                "hash": engine["content_hash"],
                "batchId": engine["batch_id"],
            },
            "styles": [
                {
                    "role": row["role"],
                    "revisionId": row["id"],
                    "stableKey": row["stable_key"],
                    "revision": int(row["revision"]),
                    "hash": row["content_hash"],
                }
                for row in inputs["styles"]
            ],
            "binding": {
                "revisionId": inputs["binding_revision_id"],
                "hash": inputs["binding_hash"],
                "taskKey": "seed",
            },
            "provider": {
                "providerId": inputs["provider"]["id"],
                "providerType": inputs["provider"]["provider_type"],
                "modelName": inputs["provider"]["model_name"],
                "profileRevision": int(inputs["provider"]["revision"]),
            },
            "scenarioHash": sha256(
                command.author_scenario.encode("utf-8")
            ).hexdigest(),
            "scenarioLength": len(command.author_scenario),
            "policyVersion": STYLE_TRIAL_POLICY_VERSION,
        }

    @staticmethod
    def _public_provider_from_manifest(manifest: dict) -> SafeProviderIdentity:
        value = manifest["provider"]
        return SafeProviderIdentity(
            provider_id=value["providerId"],
            provider_type=value["providerType"],
            model_name=value["modelName"],
            profile_revision=int(value["profileRevision"]),
        )

    @classmethod
    def _result_from_rows(cls, request: dict, attempt: dict) -> StyleTrialResult:
        manifest = _json_mapping(attempt["input_manifest_json"])
        output = None
        if request["status"] == "succeeded":
            output = StyleTrialProviderOutput.model_validate(
                _json_mapping(attempt["result_json"]), strict=True
            )
        return StyleTrialResult(
            attempt_id=attempt["id"],
            status=request["status"],
            sample=output.sample if output is not None else None,
            result_hash=request.get("result_hash"),
            public_error_code=request.get("public_error_code"),
            provider=cls._public_provider_from_manifest(manifest),
            created_at=int(attempt["created_at"]),
            completed_at=int(attempt["completed_at"]),
        )

    async def _reserve(
        self,
        command: GenerateStyleTrial,
        reservation_identity: dict[str, str],
    ):
        request_hash = self.request_hash(command)
        async with self._transaction() as session:
            project = await self.repository.lock_project(session, command.project_id)
            if project is None or project.get("archived_at") is not None:
                raise StyleTrialFailure("STYLE_TRIAL_NOT_FOUND")
            existing = await self.repository.lock_request(
                session, command.project_id, command.idempotency_key
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise StyleTrialFailure("STYLE_TRIAL_IDEMPOTENCY_CONFLICT")
                if not existing.get("attempt_id"):
                    raise RuntimeError("style trial request lost its attempt")
                attempt = await self.repository.read_attempt(
                    session, command.project_id, existing["attempt_id"]
                )
                if attempt is None:
                    raise RuntimeError("style trial attempt is missing")
                if existing["status"] == "running":
                    if attempt["status"] != "running":
                        raise RuntimeError("style trial running state diverged")
                    if (
                        self._clock() - int(attempt["created_at"])
                        < STYLE_TRIAL_RUNNING_STALE_MS
                    ):
                        raise StyleTrialFailure("STYLE_TRIAL_IN_PROGRESS")
                    await self.repository.cleanup_interrupted(
                        session,
                        project_id=command.project_id,
                        idempotency_key=command.idempotency_key,
                        request_hash=request_hash,
                        request_id=existing["id"],
                        attempt_id=attempt["id"],
                        public_error_code=_OUTCOME_UNKNOWN,
                        completed_at=self._clock(),
                    )
                    existing = await self.repository.lock_request(
                        session, command.project_id, command.idempotency_key
                    )
                    attempt = await self.repository.read_attempt(
                        session, command.project_id, existing["attempt_id"]
                    )
                if existing["status"] not in {
                    "succeeded", "failed", "outcome_unknown"
                }:
                    raise RuntimeError("style trial request state is invalid")
                return self._result_from_rows(existing, attempt), None

            inputs = await self.repository.lock_inputs(session, command)
            self._validate_inputs(command, inputs)
            provider = dict(inputs["provider"])
            provider["base_url"] = str(provider["base_url"]).strip()
            provider["api_key"] = str(provider["api_key"]).strip()
            styles = tuple(inputs["styles"])
            try:
                seed, _provenance = decode_seed_revision(
                    inputs["selection"]["payload_json"]
                )
                messages = build_style_trial_messages(
                    seed=seed,
                    engine=_parse_engine(inputs["engine"]["payload_json"]),
                    primary_style=_parse_style(styles[0]["payload_json"]),
                    secondary_style=(
                        _parse_style(styles[1]["payload_json"])
                        if len(styles) == 2
                        else None
                    ),
                    author_scenario=command.author_scenario,
                )
            except ValueError:
                raise StyleTrialFailure("STYLE_TRIAL_NOT_READY") from None
            generation_config = self._generation_config(provider)
            manifest = self._manifest(command, inputs)
            secrets = normalize_provider_secrets(
                (provider.get("api_key"), provider.get("base_url"))
            )
            if (
                style_trial_value_contains_secret(
                    {
                        "authorScenario": command.author_scenario,
                        "messages": messages,
                        "manifest": manifest,
                    },
                    secrets,
                )
                or provider_public_value_contains_secret(manifest, secrets)
                or provider_public_value_contains_secret(
                    {
                        "authorScenario": command.author_scenario,
                        "messages": messages,
                    },
                    secrets,
                )
            ):
                raise StyleTrialFailure("STYLE_TRIAL_NOT_READY")
            request_id = self._id()
            attempt_id = self._id()
            reservation_identity.update(
                request_id=request_id,
                attempt_id=attempt_id,
            )
            now = self._clock()
            request = {
                "id": request_id,
                "project_id": command.project_id,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "status": "running",
                "attempt_id": attempt_id,
                "result_hash": None,
                "public_error_code": None,
                "created_at": now,
                "completed_at": None,
            }
            attempt = {
                "id": attempt_id,
                "project_id": command.project_id,
                "selection_revision": command.selection_revision,
                "binding_revision_id": inputs["binding_revision_id"],
                "binding_hash": inputs["binding_hash"],
                "input_manifest_json": canonical_json(manifest),
                "input_manifest_hash": canonical_hash(manifest),
                "status": "running",
                "result_json": None,
                "result_hash": None,
                "public_error_code": None,
                "created_at": now,
                "completed_at": None,
            }
            await self.repository.insert_attempt(session, attempt)
            await self.repository.insert_request(session, request)
            return None, {
                "inputs": inputs,
                "provider": provider,
                "messages": messages,
                "generation_config": generation_config,
                "request": request,
                "attempt": attempt,
                "input_facts_hash": input_facts_hash(inputs),
            }

    async def _fail(self, command: GenerateStyleTrial, context: dict, code: str):
        completed_at = self._clock()
        async with self._transaction() as session:
            await self.repository.fail(
                session,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
                attempt_id=context["attempt"]["id"],
                attempt_status="failed",
                request_status="failed",
                public_error_code=code,
                completed_at=completed_at,
            )
        return StyleTrialResult(
            attempt_id=context["attempt"]["id"],
            status="failed",
            sample=None,
            result_hash=None,
            public_error_code=code,
            provider=self._safe_provider(context["inputs"]),
            created_at=int(context["attempt"]["created_at"]),
            completed_at=completed_at,
        )

    async def _cleanup_interrupted(
        self,
        command: GenerateStyleTrial,
        request_hash: str,
        reservation_identity: dict[str, str],
    ) -> bool:
        async with self._transaction() as session:
            return await self.repository.cleanup_interrupted(
                session,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                request_id=reservation_identity["request_id"],
                attempt_id=reservation_identity["attempt_id"],
                public_error_code=_OUTCOME_UNKNOWN,
                completed_at=self._clock(),
            )

    @staticmethod
    async def _wait_for_cleanup(task: asyncio.Task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    continue
        return task.result()

    async def _finish_interruption(
        self,
        command: GenerateStyleTrial,
        request_hash: str,
        reservation_identity: dict[str, str],
        interruption: BaseException,
    ) -> None:
        cleanup_task = asyncio.create_task(
            self._cleanup_interrupted(
                command,
                request_hash,
                reservation_identity,
            )
        )
        try:
            await self._wait_for_cleanup(cleanup_task)
        except BaseException as cleanup_error:
            raise BaseExceptionGroup(
                "style trial interruption cleanup also failed",
                [interruption, cleanup_error],
            ) from interruption
        raise interruption

    async def generate(self, command: GenerateStyleTrial) -> StyleTrialResult:
        request_hash = self.request_hash(command)
        reservation_identity: dict[str, str] = {}
        try:
            replay, context = await self._reserve(command, reservation_identity)
            if replay is not None:
                return replay
            assert context is not None
            try:
                output = await self._gateway.generate(
                    provider=context["provider"],
                    messages=context["messages"],
                    generation_config=context["generation_config"],
                )
            except StyleTrialProviderError:
                return await self._fail(
                    command, context, "STYLE_TRIAL_PROVIDER_FAILED"
                )
            if not isinstance(output, StyleTrialProviderOutput):
                return await self._fail(
                    command, context, "STYLE_TRIAL_PROVIDER_FAILED"
                )
            result_json = canonical_json(output)
            result_hash = canonical_hash(output)
            completed_at = self._clock()
            async with self._transaction() as session:
                published = await self.repository.publish(
                    session,
                    command=command,
                    project_id=command.project_id,
                    idempotency_key=command.idempotency_key,
                    request_hash=context["request"]["request_hash"],
                    attempt_id=context["attempt"]["id"],
                    expected_input_facts_hash=context["input_facts_hash"],
                    result_json=result_json,
                    result_hash=result_hash,
                    completed_at=completed_at,
                )
            if not published:
                return StyleTrialResult(
                    attempt_id=context["attempt"]["id"],
                    status="failed",
                    sample=None,
                    result_hash=None,
                    public_error_code="STYLE_TRIAL_INPUT_CHANGED",
                    provider=self._safe_provider(context["inputs"]),
                    created_at=int(context["attempt"]["created_at"]),
                    completed_at=completed_at,
                )
            return StyleTrialResult(
                attempt_id=context["attempt"]["id"],
                status="succeeded",
                sample=output.sample,
                result_hash=result_hash,
                public_error_code=None,
                provider=self._safe_provider(context["inputs"]),
                created_at=int(context["attempt"]["created_at"]),
                completed_at=completed_at,
            )
        except StyleTrialFailure:
            raise
        except BaseException as interruption:
            if not reservation_identity:
                raise
            await self._finish_interruption(
                command,
                request_hash,
                reservation_identity,
                interruption,
            )
            raise AssertionError("interruption cleanup must re-raise")


__all__ = (
    "GenerateStyleTrial",
    "STYLE_TRIAL_POLICY_VERSION",
    "STYLE_TRIAL_RUNNING_STALE_MS",
    "StyleTrialService",
)
