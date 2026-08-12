"""Narrow safe Provider boundaries for quality advice and one extraction."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from hashlib import sha256
from typing import Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from backend.domain.finalization import (
    FinalizationChangeSet,
    QualityFinding,
    QualityReportPayload,
)
from backend.gateways.openai_json_transport import OpenAIJSONTransport
from backend.prompts.finalization import (
    FinalizationProviderManifest,
    build_extraction_messages,
    build_quality_messages,
)


PROVIDER_TIMEOUT_SECONDS = 600
MAX_PROVIDER_RESPONSE_BYTES = 512 * 1024
_SAFE_ERROR = "Finalization provider failed"
_EVIDENCE_FIELDS = frozenset({
    "startScalar", "endScalar", "confidence", "rationale",
})


class FinalizationProviderError(RuntimeError):
    """One fixed content-free failure category."""


def _raise_safe_error() -> None:
    raise FinalizationProviderError(_SAFE_ERROR) from None


def _raise_cancelled() -> None:
    raise asyncio.CancelledError()


@runtime_checkable
class FinalizationQualityProvider(Protocol):
    async def audit(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> tuple[QualityFinding, ...]: ...


@runtime_checkable
class FinalizationExtractionProvider(Protocol):
    async def extract(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> FinalizationChangeSet: ...


def _hydrate_evidence(value: object, prose: str) -> dict[str, object]:
    if type(value) is not dict or frozenset(value.keys()) != _EVIDENCE_FIELDS:
        raise ValueError(_SAFE_ERROR)
    start = value["startScalar"]
    end = value["endScalar"]
    confidence = value["confidence"]
    if (
        type(start) is not int
        or type(end) is not int
        or start < 0
        or end <= start
        or end > len(prose)
        or type(confidence) not in (int, float)
        or type(confidence) is bool
    ):
        raise ValueError(_SAFE_ERROR)
    excerpt_hash = sha256(prose[start:end].encode("utf-8")).hexdigest()
    return {
        "startScalar": start,
        "endScalar": end,
        "excerptHash": excerpt_hash,
        "confidence": float(confidence),
        "rationale": value["rationale"],
    }


def _hydrate_nested(value: object, prose: str) -> object:
    if type(value) is list:
        return [_hydrate_nested(item, prose) for item in value]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            result[key] = (
                _hydrate_evidence(item, prose)
                if key == "evidence"
                else _hydrate_nested(item, prose)
            )
        return result
    return value


def _parse_quality(value: object, prose: str) -> tuple[QualityFinding, ...] | None:
    try:
        if type(value) is not dict or frozenset(value.keys()) != {"findings"}:
            raise ValueError(_SAFE_ERROR)
        if type(value["findings"]) is not list:
            raise ValueError(_SAFE_ERROR)
        hydrated = _hydrate_nested(value["findings"], prose)
        report = QualityReportPayload.model_validate({
            "status": "completed",
            "deterministicBlocks": [],
            "findings": hydrated,
        })
        return report.findings
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError):
        return None


def _parse_extraction(value: object, prose: str) -> FinalizationChangeSet | None:
    try:
        hydrated = _hydrate_nested(value, prose)
        return FinalizationChangeSet.model_validate(hydrated)
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError):
        return None


class _FinalizationGateway:
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
            _raise_cancelled()
        except Exception:
            _raise_safe_error()

    async def aclose(self) -> None:
        try:
            await self._resource.aclose()
        except asyncio.CancelledError:
            _raise_cancelled()
        except Exception:
            _raise_safe_error()

    @staticmethod
    def _validated_manifest(
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> FinalizationProviderManifest:
        value = FinalizationProviderManifest.model_validate(manifest, strict=True)
        provider_id = provider.get("id") if isinstance(provider, Mapping) else None
        if (
            not isinstance(provider_id, str)
            or not isinstance(model_name, str)
            or provider_id.strip() != value.binding.provider_id
            or model_name.strip() != value.binding.model_name
        ):
            raise ValueError(_SAFE_ERROR)
        return value

    async def _request(self, *, provider, model_name, messages):
        failed = False
        cancelled = False
        result = None
        try:
            result = await self._resource.request(
                provider=provider,
                model_name=model_name,
                messages=messages,
            )
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if result is not None and result.cancelled:
            cancelled = True
        if result is None or not result.succeeded:
            failed = True
        if cancelled:
            provider = None
            model_name = None
            messages = None
            result = None
            _raise_cancelled()
        if failed:
            provider = None
            model_name = None
            messages = None
            result = None
            _raise_safe_error()
        return result.value


class FinalizationQualityGateway(_FinalizationGateway):
    async def audit(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> tuple[QualityFinding, ...]:
        failed = False
        frozen = None
        messages = None
        try:
            frozen = self._validated_manifest(provider, model_name, manifest)
            messages = build_quality_messages(manifest=frozen)
        except asyncio.CancelledError:
            _raise_cancelled()
        except Exception:
            failed = True
        if failed:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        value = await self._request(
            provider=provider, model_name=model_name, messages=messages,
        )
        parsed = _parse_quality(value, frozen.candidate_prose)
        value = None
        if parsed is None:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        return parsed


class FinalizationExtractionGateway(_FinalizationGateway):
    async def extract(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> FinalizationChangeSet:
        failed = False
        frozen = None
        messages = None
        try:
            frozen = self._validated_manifest(provider, model_name, manifest)
            messages = build_extraction_messages(manifest=frozen)
        except asyncio.CancelledError:
            _raise_cancelled()
        except Exception:
            failed = True
        if failed:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        value = await self._request(
            provider=provider, model_name=model_name, messages=messages,
        )
        parsed = _parse_extraction(value, frozen.candidate_prose)
        value = None
        if parsed is None:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        return parsed


__all__ = [
    "FinalizationExtractionGateway",
    "FinalizationExtractionProvider",
    "FinalizationProviderError",
    "FinalizationQualityGateway",
    "FinalizationQualityProvider",
]
