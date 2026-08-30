"""One strict, bounded Provider boundary for Topic Center discussion."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import json

import httpx
from pydantic import ValidationError

from backend.domain.topics import TopicAssistantResult
from backend.gateways.openai_json_transport import OpenAIJSONTransport
from backend.prompts.planning import planning_text_contains_private_material


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024
_SAFE_PROVIDER_ERROR = "Topic discussion provider failed"
_SAFE_RESPONSE_ERROR = "Topic discussion response was invalid"
_RESULT_KEYS = {"reply", "directionSuggestions", "candidateSuggestions"}
_PRIVATE_KEYS = {
    "apikey",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}


def _contains_private_key(value: object) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, Mapping):
            for key, nested in item.items():
                normalized = "".join(
                    character
                    for character in str(key).casefold()
                    if character.isalnum()
                )
                if normalized in _PRIVATE_KEYS:
                    return True
                pending.append(nested)
        elif isinstance(item, (tuple, list)):
            pending.extend(item)
    return False


def _message_contains_private_material(content: str) -> bool:
    if planning_text_contains_private_material(content):
        return True
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return False
    return _contains_private_key(value)


class TopicDiscussionProviderError(RuntimeError):
    """Fixed failure category without Provider or prompt details."""


class TopicDiscussionInvalidResponse(TopicDiscussionProviderError):
    """The Provider returned a value outside the strict public contract."""


class TopicDiscussionProviderGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._resource = OpenAIJSONTransport(
            transport=transport,
            timeout_seconds=PROVIDER_TIMEOUT_SECONDS,
            response_byte_limit=MAX_PROVIDER_RESPONSE_BYTES,
        )

    async def start(self) -> None:
        try:
            await self._resource.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise TopicDiscussionProviderError(_SAFE_PROVIDER_ERROR) from exc

    async def aclose(self) -> None:
        await self._resource.aclose()

    async def generate(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        messages: Sequence[Mapping[str, str]],
    ) -> TopicAssistantResult:
        if any(
            _message_contains_private_material(str(item.get("content", "")))
            for item in messages
        ):
            raise TopicDiscussionProviderError(_SAFE_PROVIDER_ERROR)
        try:
            transport_result = await self._resource.request(
                provider=provider,
                model_name=model_name,
                messages=messages,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise TopicDiscussionProviderError(_SAFE_PROVIDER_ERROR) from exc

        if transport_result.cancelled:
            raise asyncio.CancelledError()
        if not transport_result.succeeded:
            raise TopicDiscussionProviderError(_SAFE_PROVIDER_ERROR)
        value = transport_result.value
        if not isinstance(value, dict) or set(value) != _RESULT_KEYS:
            raise TopicDiscussionInvalidResponse(_SAFE_RESPONSE_ERROR)
        try:
            return TopicAssistantResult.model_validate(value, strict=True)
        except (ValidationError, TypeError, ValueError) as exc:
            raise TopicDiscussionInvalidResponse(_SAFE_RESPONSE_ERROR) from exc


topic_discussion_provider_gateway = TopicDiscussionProviderGateway()


__all__ = (
    "MAX_PROVIDER_RESPONSE_BYTES",
    "PROVIDER_TIMEOUT_SECONDS",
    "TopicDiscussionInvalidResponse",
    "TopicDiscussionProviderError",
    "TopicDiscussionProviderGateway",
    "topic_discussion_provider_gateway",
)
