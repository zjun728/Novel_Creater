"""One strict OpenAI-compatible outbound boundary for Planning generation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Protocol, TypeAlias, runtime_checkable

import httpx
from pydantic import ValidationError

from backend.domain.planning import DraftPlanningAggregate
from backend.gateways.openai_json_transport import (
    OpenAIJSONTransport,
    openai_chat_completions_endpoint,
)
from backend.prompts.planning import (
    PlanningGenerationManifest,
    build_planning_messages,
)


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 128 * 1024
PLANNING_TEMPERATURE_CAP = 0.4
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


def _raise_safe_provider_error() -> None:
    raise PlanningProviderError(_SAFE_ERROR)


def _raise_clean_cancelled_error() -> None:
    raise asyncio.CancelledError()


def _assign_missing_editable_node_identities(value: object) -> object:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    for section, prefix in (("volumes", "volume"), ("plots", "plot")):
        nodes = value.get(section)
        if not isinstance(nodes, list):
            continue
        normalized_nodes = []
        for index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict) or any(
                node.get(key) is not None
                for key in ("clientNodeKey", "id", "revision", "contentHash")
            ):
                normalized_nodes.append(node)
                continue
            normalized_node = dict(node)
            for key in ("clientNodeKey", "id", "revision", "contentHash"):
                normalized_node.pop(key, None)
            normalized_node["clientNodeKey"] = f"generated-{prefix}-{index:03d}"
            normalized_nodes.append(normalized_node)
        normalized[section] = normalized_nodes
    return normalized


class PlanningProviderGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._resource = OpenAIJSONTransport(
            transport=transport,
            timeout_seconds=PROVIDER_TIMEOUT_SECONDS,
            response_byte_limit=MAX_PROVIDER_RESPONSE_BYTES,
        )

    @staticmethod
    def _endpoint(base_url: str) -> str:
        return openai_chat_completions_endpoint(base_url)

    async def start(self) -> None:
        cancelled = False
        resource = self._resource
        try:
            await resource.start()
        except asyncio.CancelledError:
            cancelled = True
        resource = None
        self = None
        if cancelled:
            _raise_clean_cancelled_error()

    async def aclose(self) -> None:
        await self._resource.aclose()

    async def generate(
        self,
        *,
        provider: PublicProviderRuntime,
        model_name: str,
        manifest: PlanningGenerationManifest,
        author_instructions: str,
    ) -> dict[str, object]:
        failed = False
        cancelled = False
        frozen_manifest = None
        frozen_draft = None
        messages = None
        transport_result = None
        runtime_provider = None
        value = None
        draft = None
        result = None

        try:
            frozen_manifest = PlanningGenerationManifest.model_validate(
                manifest,
                strict=True,
            )
            messages = build_planning_messages(
                manifest=frozen_manifest,
                author_instructions=author_instructions,
            )
            frozen_draft = frozen_manifest.draft
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            UnicodeError,
        ):
            failed = True

        if not failed:
            try:
                runtime_provider = dict(provider)
                runtime_provider["temperature"] = min(
                    float(provider["temperature"]),
                    PLANNING_TEMPERATURE_CAP,
                )
                runtime_provider["thinking"] = {"type": "disabled"}
                transport_result = await self._resource.request(
                    provider=runtime_provider,
                    model_name=model_name,
                    messages=messages,
                )
                if transport_result.cancelled:
                    cancelled = True
                elif not transport_result.succeeded:
                    failed = True
                else:
                    value = _assign_missing_editable_node_identities(
                        transport_result.value
                    )
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failed = True

        if not failed and not cancelled:
            try:
                if not isinstance(value, dict):
                    raise TypeError(_SAFE_ERROR)
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
                result["activeStoryBlockRef"] = (
                    draft.active_story_block_ref
                )
            except (
                UnicodeError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
                ValidationError,
                RecursionError,
            ):
                failed = True

        if failed or cancelled:
            provider = None
            runtime_provider = None
            model_name = None
            manifest = None
            author_instructions = None
            frozen_manifest = None
            frozen_draft = None
            messages = None
            transport_result = None
            value = None
            draft = None
            result = None
            self = None
            if cancelled:
                _raise_clean_cancelled_error()
            _raise_safe_provider_error()

        assert result is not None
        return result


__all__ = (
    "MAX_PROVIDER_RESPONSE_BYTES",
    "PROVIDER_TIMEOUT_SECONDS",
    "PlanningGenerationManifest",
    "PlanningProvider",
    "PlanningProviderError",
    "PlanningProviderGateway",
    "PublicProviderRuntime",
)
