"""Narrow safe Provider boundaries for quality advice and one extraction."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from hashlib import sha256
import math
from typing import Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from backend.domain.finalization import (
    FinalizationChangeSet,
    PlanningPatch,
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


def _drop_items_with_unusable_evidence(
    value: object,
    prose: str,
) -> object:
    if type(value) is not dict:
        return value
    result = dict(value)
    for collection in (
        "canonEvents",
        "storyProgressEvents",
        "planningPatches",
        "planningSuggestions",
    ):
        items = value.get(collection)
        if type(items) is not list:
            continue
        kept = []
        for item in items:
            evidence = item.get("evidence") if type(item) is dict else None
            if (
                type(evidence) is not dict
                or frozenset(evidence.keys()) != _EVIDENCE_FIELDS
            ):
                kept.append(item)
                continue
            start = evidence["startScalar"]
            end = evidence["endScalar"]
            confidence = evidence["confidence"]
            rationale = evidence["rationale"]
            usable = (
                type(start) is int
                and type(end) is int
                and 0 <= start < end <= len(prose)
                and type(confidence) in (int, float)
                and type(confidence) is not bool
                and math.isfinite(float(confidence))
                and 0 <= float(confidence) <= 1
                and isinstance(rationale, str)
                and bool(rationale.strip())
            )
            if usable:
                kept.append(item)
        result[collection] = kept
    return result


def _drop_planning_patches_with_disallowed_fields(value: object) -> object:
    if type(value) is not dict or type(value.get("planningPatches")) is not list:
        return value
    result = dict(value)
    kept = []
    for item in value["planningPatches"]:
        try:
            PlanningPatch.model_validate(item)
        except ValidationError as error:
            issues = error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
            if (
                len(issues) == 1
                and issues[0].get("loc") == ()
                and issues[0].get("type") == "value_error"
                and issues[0].get("msg") == (
                    "Value error, planning fieldPath is not allowed "
                    "for targetType"
                )
            ):
                continue
        kept.append(item)
    result["planningPatches"] = kept
    return result


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
        filtered = _drop_items_with_unusable_evidence(value, prose)
        hydrated = _hydrate_nested(filtered, prose)
        hydrated = _drop_planning_patches_with_disallowed_fields(hydrated)
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
        runtime_provider = dict(provider)
        runtime_provider["temperature"] = 0.0
        try:
            base_url = provider.get("base_url")
            if isinstance(base_url, str):
                host = (httpx.URL(base_url).host or "").casefold()
                if host == "deepseek.com" or host.endswith(".deepseek.com"):
                    runtime_provider["thinking"] = {"type": "disabled"}
            result = await self._resource.request(
                provider=runtime_provider,
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
            runtime_provider = None
            model_name = None
            messages = None
            result = None
            _raise_cancelled()
        if failed:
            provider = None
            runtime_provider = None
            model_name = None
            messages = None
            result = None
            _raise_safe_error()
        runtime_provider = None
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
