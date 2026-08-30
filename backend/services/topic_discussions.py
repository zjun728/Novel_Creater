"""Crash-safe orchestration for global Topic Center conversations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from hashlib import sha256
import time
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.topics import (
    MAX_TOPIC_MESSAGE_LENGTH,
    TopicAssistantResult,
    TopicEvidenceRef,
    TopicFailure,
    TopicMessage,
    TopicSubjectRef,
)
from backend.gateways.topic_discussion_provider import (
    TopicDiscussionInvalidResponse,
    TopicDiscussionProviderError,
)
from backend.prompts.topic_discussion import (
    MAX_TOPIC_TRANSCRIPT_MESSAGES,
    build_topic_discussion_messages,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return str(uuid4())


def _text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class DiscussTopic(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    discussion_id: str = Field(alias="discussionId", min_length=1, max_length=36)
    content: str = Field(min_length=1, max_length=MAX_TOPIC_MESSAGE_LENGTH)
    idempotency_key: str = Field(
        alias="idempotencyKey",
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )
    evidence: tuple[TopicEvidenceRef, ...] = Field(default=(), max_length=4)
    subject: TopicSubjectRef | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return TopicMessage(role="user", content=value).content

    @field_validator("evidence", mode="before")
    @classmethod
    def freeze_evidence(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evidence")
    @classmethod
    def unique_evidence(
        cls,
        value: tuple[TopicEvidenceRef, ...],
    ) -> tuple[TopicEvidenceRef, ...]:
        identities = tuple(item.snapshot_id for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("topic evidence IDs must be unique")
        return value


class TopicDiscussionService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        provider_gateway,
        id_factory: Callable[[], str] = _new_id,
        clock: Callable[[], int] = _now_ms,
    ) -> None:
        self._repository = repository
        self._transaction = transaction_factory
        self._connection = connection_factory
        self._gateway = provider_gateway
        self._id = id_factory
        self._clock = clock

    async def create(self, title: str) -> dict[str, Any]:
        clean_title = TopicMessage(role="user", content=title).content
        if len(clean_title) > 300:
            raise ValueError("topic discussion title is too long")
        now = self._clock()
        row = {
            "id": self._id(),
            "title": clean_title,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        async with self._transaction() as session:
            await self._repository.insert_discussion(session, row)
        return dict(row)

    @staticmethod
    def _request_hash(command: DiscussTopic) -> str:
        return canonical_hash(
            command.model_dump(mode="json", by_alias=True)
        )

    @staticmethod
    def _provider_ready(value: object) -> bool:
        if not isinstance(value, Mapping):
            return False
        runtime = value.get("runtime")
        return bool(
            isinstance(runtime, Mapping)
            and runtime.get("enabled")
            and runtime.get("lifecycle_status") == "active"
            and runtime.get("supports_json")
            and str(runtime.get("provider_type") or "").strip()
            and str(runtime.get("model_name") or "").strip()
            and str(runtime.get("base_url") or "").strip()
            and str(runtime.get("api_key") or "").strip()
        )

    async def _locked_subject(self, session, subject: TopicSubjectRef | None):
        if subject is None:
            return None
        if subject.kind == "direction":
            identity = await self._repository.lock_direction(session, subject.id)
            version = await self._repository.lock_direction_version(
                session,
                direction_id=subject.id,
                version=subject.version,
                content_hash=subject.content_hash,
            )
        else:
            identity = await self._repository.lock_candidate(session, subject.id)
            version = await self._repository.lock_candidate_version(
                session,
                candidate_id=subject.id,
                version=subject.version,
                content_hash=subject.content_hash,
            )
        if identity is None or version is None:
            raise TopicFailure("TOPIC_NOT_FOUND")
        return {
            "kind": subject.kind,
            "id": subject.id,
            "version": subject.version,
            "content_hash": subject.content_hash,
            "payload": version["payload"],
        }

    @staticmethod
    def _replay(existing: Mapping, request_hash: str):
        if existing.get("request_hash") != request_hash:
            raise TopicFailure("TOPIC_REQUEST_CONFLICT")
        status = existing.get("status")
        if status == "succeeded":
            result = TopicAssistantResult.model_validate(
                existing.get("result"),
                strict=True,
            )
            return {
                "status": "succeeded",
                "requestId": existing["id"],
                "result": result,
            }
        if status in {"reserved", "running"}:
            raise TopicFailure("TOPIC_REQUEST_IN_PROGRESS")
        if status == "outcome_unknown":
            raise TopicFailure("TOPIC_OUTCOME_UNKNOWN")
        code = existing.get("public_error_code")
        if isinstance(code, str):
            raise TopicFailure(code)
        raise TopicFailure("TOPIC_PROVIDER_FAILED")

    async def _reserve(self, command: DiscussTopic, request_hash: str):
        async with self._transaction() as session:
            discussion = await self._repository.lock_discussion(
                session,
                command.discussion_id,
            )
            if discussion is None:
                raise TopicFailure("TOPIC_NOT_FOUND")
            existing = await self._repository.lock_request_by_key(
                session,
                discussion_id=command.discussion_id,
                idempotency_key=command.idempotency_key,
            )
            if existing is not None:
                return {"replay": self._replay(existing, request_hash)}

            evidence = await self._repository.lock_snapshot_evidence(
                session,
                command.evidence,
            )
            subject = await self._locked_subject(session, command.subject)
            generation = await self._repository.lock_generation_inputs(session)
            if not self._provider_ready(generation):
                raise TopicFailure("TOPIC_PROVIDER_NOT_READY")

            prior_rows = await self._repository.list_messages_for_prompt(
                session,
                command.discussion_id,
                limit=MAX_TOPIC_TRANSCRIPT_MESSAGES - 1,
            )
            transcript = [
                {
                    "role": row["role"],
                    "content": row.get("content", row.get("content_text")),
                }
                for row in prior_rows
            ]
            transcript.append({"role": "user", "content": command.content})
            messages = build_topic_discussion_messages(
                transcript=transcript,
                evidence=evidence,
                subject=subject,
            )

            now = self._clock()
            user_message_id = self._id()
            request_id = self._id()
            sequence = await self._repository.next_message_sequence(
                session,
                command.discussion_id,
            )
            manifest = {
                "evidence": [
                    {
                        "snapshotId": item["id"],
                        "contentHash": item["content_hash"],
                    }
                    for item in evidence
                ],
                "subject": (
                    None
                    if subject is None
                    else {
                        "kind": subject["kind"],
                        "id": subject["id"],
                        "version": subject["version"],
                        "contentHash": subject["content_hash"],
                    }
                ),
                "provider": dict(generation["manifest"]),
            }
            await self._repository.insert_message(
                session,
                {
                    "id": user_message_id,
                    "discussion_id": command.discussion_id,
                    "sequence_number": sequence,
                    "role": "user",
                    "content_text": command.content,
                    "content_hash": _text_hash(command.content),
                    "created_at": now,
                },
            )
            provider_manifest = generation["manifest"]
            await self._repository.insert_request(
                session,
                {
                    "id": request_id,
                    "discussion_id": command.discussion_id,
                    "idempotency_key": command.idempotency_key,
                    "request_hash": request_hash,
                    "input_manifest": manifest,
                    "input_manifest_json": canonical_json(manifest),
                    "input_manifest_hash": canonical_hash(manifest),
                    "provider_id": provider_manifest["providerId"],
                    "provider_name_snapshot": provider_manifest["providerName"],
                    "model_name_snapshot": provider_manifest["modelName"],
                    "provider_config_hash": provider_manifest["providerConfigHash"],
                    "status": "running",
                    "user_message_id": user_message_id,
                    "created_at": now,
                },
            )
            await self._repository.touch_discussion(
                session,
                discussion_id=command.discussion_id,
                updated_at=now,
            )
            runtime = dict(generation["runtime"])
            provider = {
                "provider_type": runtime["provider_type"],
                "base_url": runtime["base_url"],
                "api_key": runtime["api_key"],
                "temperature": float(runtime["temperature"]),
                "max_output_tokens": int(runtime["max_output_tokens"]),
            }
            return {
                "request_id": request_id,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "provider": provider,
                "model_name": runtime["model_name"],
                "messages": messages,
                "discussion_id": command.discussion_id,
            }

    async def _terminal_failure(self, request_id: str, status: str, code: str):
        async with self._transaction() as session:
            changed = await self._repository.fail_request(
                session,
                request_id=request_id,
                status=status,
                public_error_code=code,
                completed_at=self._clock(),
            )
            if not changed:
                raise TopicFailure("TOPIC_OUTCOME_UNKNOWN")

    async def _publish(self, reservation: Mapping, result: TopicAssistantResult):
        now = self._clock()
        assistant_id = self._id()
        result_json = canonical_json(
            result.model_dump(mode="json", by_alias=True)
        )
        result_hash = canonical_hash(
            result.model_dump(mode="json", by_alias=True)
        )
        async with self._transaction() as session:
            discussion = await self._repository.lock_discussion(
                session,
                reservation["discussion_id"],
            )
            if discussion is None:
                raise TopicFailure("TOPIC_OUTCOME_UNKNOWN")
            request = await self._repository.lock_request_by_key(
                session,
                discussion_id=reservation["discussion_id"],
                idempotency_key=reservation["idempotency_key"],
            )
            if (
                request is None
                or request.get("id") != reservation["request_id"]
                or request.get("request_hash") != reservation["request_hash"]
                or request.get("status") != "running"
            ):
                raise TopicFailure("TOPIC_OUTCOME_UNKNOWN")
            sequence = await self._repository.next_message_sequence(
                session,
                reservation["discussion_id"],
            )
            await self._repository.insert_message(
                session,
                {
                    "id": assistant_id,
                    "discussion_id": reservation["discussion_id"],
                    "sequence_number": sequence,
                    "role": "assistant",
                    "content_text": result.reply,
                    "content_hash": _text_hash(result.reply),
                    "created_at": now,
                },
            )
            changed = await self._repository.complete_request(
                session,
                request_id=reservation["request_id"],
                assistant_message_id=assistant_id,
                result_json=result_json,
                result_hash=result_hash,
                completed_at=now,
            )
            if not changed:
                raise TopicFailure("TOPIC_OUTCOME_UNKNOWN")
            await self._repository.touch_discussion(
                session,
                discussion_id=reservation["discussion_id"],
                updated_at=now,
            )
        return assistant_id

    async def send(self, command: DiscussTopic) -> dict[str, Any]:
        request_hash = self._request_hash(command)
        reservation = await self._reserve(command, request_hash)
        if "replay" in reservation:
            return reservation["replay"]
        try:
            result = await self._gateway.generate(
                provider=reservation["provider"],
                model_name=reservation["model_name"],
                messages=reservation["messages"],
            )
        except asyncio.CancelledError:
            await self._terminal_failure(
                reservation["request_id"],
                "failed",
                "TOPIC_PROVIDER_FAILED",
            )
            raise
        except TopicDiscussionInvalidResponse as exc:
            await self._terminal_failure(
                reservation["request_id"],
                "failed",
                "TOPIC_INVALID_RESPONSE",
            )
            raise TopicFailure("TOPIC_INVALID_RESPONSE") from exc
        except TopicDiscussionProviderError as exc:
            await self._terminal_failure(
                reservation["request_id"],
                "failed",
                "TOPIC_PROVIDER_FAILED",
            )
            raise TopicFailure("TOPIC_PROVIDER_FAILED") from exc

        try:
            assistant_id = await self._publish(reservation, result)
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            await self._terminal_failure(
                reservation["request_id"],
                "outcome_unknown",
                "TOPIC_OUTCOME_UNKNOWN",
            )
            raise TopicFailure("TOPIC_OUTCOME_UNKNOWN") from exc
        return {
            "status": "succeeded",
            "requestId": reservation["request_id"],
            "assistantMessageId": assistant_id,
            "result": result,
        }


__all__ = ("DiscussTopic", "TopicDiscussionService")
