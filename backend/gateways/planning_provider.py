"""One strict OpenAI-compatible outbound boundary for Planning generation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import math
from typing import Protocol, TypeAlias, runtime_checkable

import httpx
from pydantic import ValidationError

from backend.domain.planning import DraftPlanningAggregate
from backend.domain.provider_policy import provider_type_is_supported
from backend.prompts.planning import (
    PlanningGenerationManifest,
    build_planning_messages,
)
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 128 * 1024
_SAFE_ERROR = "Planning provider failed"

# Retain the repository's Mapping-based Provider runtime convention instead of
# introducing a second Provider DTO.
PublicProviderRuntime: TypeAlias = Mapping[str, object]


@runtime_checkable
class PlanningProvider(Protocol):
    async def generate(
        self,
        *,
        provider: PublicProviderRuntime,
        model_name: str,
        manifest: PlanningGenerationManifest,
        author_instructions: str,
    ) -> dict[str, object]: ...


class PlanningProviderError(RuntimeError):
    """Fixed failure category; no prompt or Provider detail crosses it."""


class PlanningProviderGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    @staticmethod
    def _endpoint(base_url: str) -> str:
        parsed = httpx.URL(base_url)
        path = parsed.path.rstrip("/")
        if not path.endswith("/chat/completions"):
            path += "/chat/completions"
        return str(parsed.copy_with(path=path))

    async def generate(
        self,
        *,
        provider: PublicProviderRuntime,
        model_name: str,
        manifest: PlanningGenerationManifest,
        author_instructions: str,
    ) -> dict[str, object]:
        try:
            if not provider_type_is_supported(provider.get("provider_type")):
                raise ValueError(_SAFE_ERROR)
            if not isinstance(model_name, str) or not model_name.strip():
                raise ValueError(_SAFE_ERROR)
            base_url = provider["base_url"]
            api_key = provider["api_key"]
            if not isinstance(base_url, str) or not base_url.strip():
                raise ValueError(_SAFE_ERROR)
            if not isinstance(api_key, str) or not api_key.strip():
                raise ValueError(_SAFE_ERROR)
            temperature = float(provider["temperature"])
            max_output_value = provider.get("max_output_tokens")
            if max_output_value is None:
                max_output_value = provider["maxOutputTokens"]
            max_output_tokens = int(max_output_value)
            if (
                not math.isfinite(temperature)
                or temperature < 0
                or max_output_tokens <= 0
            ):
                raise ValueError(_SAFE_ERROR)
            frozen_manifest = PlanningGenerationManifest.model_validate(
                manifest,
                strict=True,
            )
            messages = build_planning_messages(
                manifest=frozen_manifest,
                author_instructions=author_instructions,
            )
            frozen_draft = frozen_manifest.draft
            secrets = normalize_provider_secrets((api_key, base_url))
            rendered_messages = json.dumps(
                messages,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            if (
                provider_response_text_contains_secret(
                    rendered_messages,
                    secrets,
                )
                or provider_response_value_contains_secret(
                    messages,
                    secrets,
                )
            ):
                raise ValueError(_SAFE_ERROR)
            endpoint = self._endpoint(base_url.strip())
            authorization = f"Bearer {api_key.strip()}"
            body = {
                "model": model_name.strip(),
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_output_tokens,
                "response_format": {"type": "json_object"},
                "stream": False,
            }
        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            UnicodeError,
            httpx.InvalidURL,
        ):
            raise PlanningProviderError(_SAFE_ERROR) from None

        try:
            async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(
                        connect=15,
                        read=180,
                        write=30,
                        pool=15,
                    ),
                ) as client:
                    async with client.stream(
                        "POST",
                        endpoint,
                        headers={"Authorization": authorization},
                        json=body,
                    ) as response:
                        if not response.is_success:
                            raise PlanningProviderError(_SAFE_ERROR)
                        declared = response.headers.get("content-length")
                        if declared is not None:
                            try:
                                declared_size = int(declared)
                            except ValueError:
                                raise PlanningProviderError(
                                    _SAFE_ERROR
                                ) from None
                            if (
                                declared_size < 0
                                or declared_size > MAX_PROVIDER_RESPONSE_BYTES
                            ):
                                raise PlanningProviderError(_SAFE_ERROR)
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            remaining = (
                                MAX_PROVIDER_RESPONSE_BYTES + 1 - len(raw)
                            )
                            if remaining > 0:
                                raw.extend(chunk[:remaining])
                            if (
                                len(raw) > MAX_PROVIDER_RESPONSE_BYTES
                                or len(chunk) > remaining
                            ):
                                raise PlanningProviderError(_SAFE_ERROR)
        except PlanningProviderError:
            raise
        except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
            raise PlanningProviderError(_SAFE_ERROR) from None

        try:
            secrets = normalize_provider_secrets((api_key, base_url))
            raw_text = bytes(raw).decode("utf-8")
            if provider_response_text_contains_secret(raw_text, secrets):
                raise ValueError(_SAFE_ERROR)
            envelope = json.loads(raw_text)
            if provider_response_value_contains_secret(envelope, secrets):
                raise ValueError(_SAFE_ERROR)
            content = validate_provider_response_text(
                envelope["choices"][0]["message"]["content"],
                strip=True,
            )
            if provider_response_text_contains_secret(content, secrets):
                raise ValueError(_SAFE_ERROR)
            value = json.loads(content)
            if not isinstance(value, dict):
                raise TypeError(_SAFE_ERROR)
            if provider_response_value_contains_secret(value, secrets):
                raise ValueError(_SAFE_ERROR)
            draft = DraftPlanningAggregate.model_validate(
                value,
                strict=True,
            )
            if (
                draft.active_story_block_ref
                != frozen_draft.active_story_block_ref
                or draft.story_blocks != frozen_draft.story_blocks
            ):
                raise ValueError(_SAFE_ERROR)
            result = draft.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
            result["activeStoryBlockRef"] = draft.active_story_block_ref
            return result
        except (
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            ValidationError,
            RecursionError,
        ):
            raise PlanningProviderError(_SAFE_ERROR) from None


__all__ = (
    "MAX_PROVIDER_RESPONSE_BYTES",
    "PROVIDER_TIMEOUT_SECONDS",
    "PlanningGenerationManifest",
    "PlanningProvider",
    "PlanningProviderError",
    "PlanningProviderGateway",
    "PublicProviderRuntime",
)
