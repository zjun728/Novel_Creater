"""One strict OpenAI-compatible boundary for ChapterOutline generation."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.gateways.openai_json_transport import (
    openai_chat_completions_endpoint,
    request_openai_json,
)
from backend.gateways.planning_provider import PublicProviderRuntime
from backend.prompts.chapter_outline import (
    ChapterOutlineGenerationManifest,
    build_chapter_outline_messages,
)


PROVIDER_TIMEOUT_SECONDS = 180
MAX_PROVIDER_RESPONSE_BYTES = 128 * 1024
_SAFE_ERROR = "Chapter outline provider failed"


@runtime_checkable
class ChapterOutlineProvider(Protocol):
    async def generate(
        self,
        *,
        provider: PublicProviderRuntime,
        model_name: str,
        manifest: ChapterOutlineGenerationManifest,
    ) -> EditableChapterOutlineContent: ...


class ChapterOutlineProviderError(RuntimeError):
    """Fixed safe category; no prompt or Provider detail crosses it."""


def _raise_safe_provider_error() -> None:
    raise ChapterOutlineProviderError(_SAFE_ERROR)


def _raise_clean_cancelled_error() -> None:
    raise asyncio.CancelledError()


class ChapterOutlineProviderGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    @staticmethod
    def _endpoint(base_url: str) -> str:
        return openai_chat_completions_endpoint(base_url)

    async def generate(
        self,
        *,
        provider: PublicProviderRuntime,
        model_name: str,
        manifest: ChapterOutlineGenerationManifest,
    ) -> EditableChapterOutlineContent:
        failed = False
        cancelled = False
        frozen_manifest = None
        messages = None
        provider_id = None
        transport_result = None
        value = None
        result = None

        try:
            frozen_manifest = (
                ChapterOutlineGenerationManifest.model_validate(
                    manifest,
                    strict=True,
                )
            )
            provider_id = provider.get("id")
            if (
                not isinstance(provider_id, str)
                or not provider_id.strip()
                or not isinstance(model_name, str)
                or frozen_manifest.binding.provider_id
                != provider_id.strip()
                or frozen_manifest.binding.model_name != model_name.strip()
            ):
                raise ValueError(_SAFE_ERROR)
            messages = build_chapter_outline_messages(
                manifest=frozen_manifest
            )
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
                transport_result = await request_openai_json(
                    provider=provider,
                    model_name=model_name,
                    messages=messages,
                    transport=self._transport,
                    timeout_seconds=PROVIDER_TIMEOUT_SECONDS,
                    max_response_bytes=MAX_PROVIDER_RESPONSE_BYTES,
                )
                if transport_result.cancelled:
                    cancelled = True
                elif not transport_result.succeeded:
                    failed = True
                else:
                    value = transport_result.value
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failed = True

        if not failed and not cancelled:
            try:
                if not isinstance(value, dict):
                    raise TypeError(_SAFE_ERROR)
                result = EditableChapterOutlineContent.model_validate(
                    value,
                    strict=True,
                )
                if not self._has_exact_refs(result, frozen_manifest):
                    raise ValueError(_SAFE_ERROR)
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
            model_name = None
            manifest = None
            frozen_manifest = None
            messages = None
            provider_id = None
            transport_result = None
            value = None
            result = None
            self = None
            if cancelled:
                _raise_clean_cancelled_error()
            _raise_safe_provider_error()

        assert result is not None
        return result

    @staticmethod
    def _has_exact_refs(
        result: EditableChapterOutlineContent,
        manifest: ChapterOutlineGenerationManifest,
    ) -> bool:
        def matches(ref, node) -> bool:
            return (
                ref is not None
                and ref.id == node.id
                and ref.revision == node.revision
                and ref.content_hash == node.content_hash
            )

        return (
            matches(result.volume_ref, manifest.volume)
            and matches(result.story_block_ref, manifest.story_block)
            and len(result.stage_refs) == len(manifest.allowed_stages)
            and all(
                matches(ref, node)
                for ref, node in zip(
                    result.stage_refs,
                    manifest.allowed_stages,
                    strict=True,
                )
            )
            and len(result.scene_task_refs)
            == len(manifest.allowed_scene_tasks)
            and all(
                matches(ref, node)
                for ref, node in zip(
                    result.scene_task_refs,
                    manifest.allowed_scene_tasks,
                    strict=True,
                )
            )
        )


__all__ = (
    "MAX_PROVIDER_RESPONSE_BYTES",
    "PROVIDER_TIMEOUT_SECONDS",
    "ChapterOutlineGenerationManifest",
    "ChapterOutlineProvider",
    "ChapterOutlineProviderError",
    "ChapterOutlineProviderGateway",
    "PublicProviderRuntime",
)
