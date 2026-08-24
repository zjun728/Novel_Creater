from __future__ import annotations

import asyncio
from hashlib import sha256
import json

import httpx
import pytest

from backend.domain.finalization import FinalizationChangeSet, QualityFinding
from backend.gateways.finalization_provider import (
    FinalizationExtractionGateway,
    FinalizationExtractionProvider,
    FinalizationProviderError,
    FinalizationQualityGateway,
    FinalizationQualityProvider,
)
from backend.tests.unit.test_finalization_prompt import _manifest
from backend.tests.unit.test_provider_response_secret_scanning import (
    _assert_no_sensitive_error_graph,
)


def _provider():
    return {
        "id": "provider-1",
        "provider_type": "openai-compatible",
        "base_url": "https://provider.example/v1",
        "api_key": "PRIVATE_API_KEY_SENTINEL",
        "temperature": 0.2,
        "max_output_tokens": 16_384,
    }


def _response(payload, request):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
    }, request=request)


def _evidence():
    return {
        "startScalar": 0,
        "endScalar": 2,
        "confidence": 0.8,
        "rationale": "开篇动作",
    }


def _quality_payload():
    return {"findings": [{
        "id": "finding-1",
        "dimension": "pacing",
        "reason": "推进略快",
        "suggestedAction": "增加行动后的反应",
        "evidence": _evidence(),
    }]}


def _extraction_payload():
    return {
        "schemaVersion": "finalization-changeset-v1",
        "title": "第一章",
        "summary": "沈砚进入山门。",
        "existingEntityIds": [],
        "entities": [],
        "aliases": [],
        "canonEvents": [],
        "storyProgressEvents": [],
        "planningPatches": [],
        "planningSuggestions": [{
            "id": "suggestion-1",
            "targetId": None,
            "message": "后续可放慢节奏。",
            "evidence": _evidence(),
        }],
    }


async def _call(gateway, method, **kwargs):
    await gateway.start()
    try:
        return await getattr(gateway, method)(**kwargs)
    finally:
        await gateway.aclose()


def test_concrete_gateways_satisfy_narrow_protocols():
    transport = httpx.MockTransport(lambda request: _response({}, request))
    assert isinstance(FinalizationQualityGateway(transport=transport), FinalizationQualityProvider)
    assert isinstance(FinalizationExtractionGateway(transport=transport), FinalizationExtractionProvider)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway_type", "method", "payload", "result_type"),
    [
        (FinalizationQualityGateway, "audit", _quality_payload, tuple),
        (FinalizationExtractionGateway, "extract", _extraction_payload, FinalizationChangeSet),
    ],
)
async def test_gateway_makes_one_bounded_call_and_returns_closed_domain_value(
    gateway_type, method, payload, result_type, caplog,
):
    requests = []

    def handler(request):
        requests.append(request)
        return _response(payload(), request)

    manifest = _manifest()
    result = await _call(
        gateway_type(transport=httpx.MockTransport(handler)),
        method,
        provider=_provider(),
        model_name="finalization-model",
        manifest=manifest,
    )

    assert type(result) is result_type
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["model"] == "finalization-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert "thinking" not in body
    assert str(requests[0].url) == "https://provider.example/v1/chat/completions"
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_deepseek_finalization_explicitly_disables_reasoning_mode():
    requests = []

    def handler(request):
        requests.append(request)
        return _response(_extraction_payload(), request)

    provider = _provider()
    provider["base_url"] = "https://api.deepseek.com/v1"
    result = await _call(
        FinalizationExtractionGateway(transport=httpx.MockTransport(handler)),
        "extract",
        provider=provider,
        model_name="finalization-model",
        manifest=_manifest(),
    )

    assert type(result) is FinalizationChangeSet
    assert json.loads(requests[0].content)["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_evidence_hash_is_computed_from_candidate_and_provider_cannot_supply_it():
    manifest = _manifest()
    gateway = FinalizationQualityGateway(transport=httpx.MockTransport(
        lambda request: _response(_quality_payload(), request)
    ))

    result = await _call(
        gateway, "audit", provider=_provider(), model_name="finalization-model",
        manifest=manifest,
    )

    assert type(result[0]) is QualityFinding
    assert result[0].evidence.excerpt_hash == sha256(
        manifest.candidate_prose[0:2].encode("utf-8")
    ).hexdigest()

    bad = _quality_payload()
    bad["findings"][0]["evidence"]["excerptHash"] = "a" * 64
    bad_gateway = FinalizationQualityGateway(transport=httpx.MockTransport(
        lambda request: _response(bad, request)
    ))
    with pytest.raises(FinalizationProviderError, match="Finalization provider failed"):
        await _call(
            bad_gateway, "audit", provider=_provider(),
            model_name="finalization-model", manifest=manifest,
        )


@pytest.mark.asyncio
async def test_extraction_drops_only_items_with_empty_evidence_ranges():
    payload = _extraction_payload()
    payload["canonEvents"] = [{
        "id": "event-1",
        "entityId": None,
        "factKind": "dynamic_event",
        "fieldPath": "chapter.event",
        "value": "进入山门",
        "evidence": _evidence(),
        "effectiveStartChapter": 1,
        "effectiveEndChapter": 1,
        "assertionOperator": "equals",
        "valueCardinality": "single",
    }]
    payload["planningSuggestions"].append({
        "id": "suggestion-empty-evidence",
        "targetId": None,
        "message": "没有可定位证据的建议。",
        "evidence": {
            "startScalar": 2,
            "endScalar": 2,
            "confidence": 0.5,
            "rationale": "空区间",
        },
    })
    gateway = FinalizationExtractionGateway(transport=httpx.MockTransport(
        lambda request: _response(payload, request)
    ))

    result = await _call(
        gateway, "extract", provider=_provider(),
        model_name="finalization-model", manifest=_manifest(),
    )

    assert [item.id for item in result.canon_events] == ["event-1"]
    assert [item.id for item in result.planning_suggestions] == ["suggestion-1"]


@pytest.mark.asyncio
async def test_extraction_drops_planning_patches_with_disallowed_fields():
    payload = _extraction_payload()
    payload["planningPatches"] = [
        {
            "id": "patch-valid",
            "targetType": "volume",
            "targetId": "volume-1",
            "expectedRevision": 1,
            "expectedHash": "a" * 64,
            "fieldPath": "title",
            "replacement": "新卷名",
            "evidence": _evidence(),
        },
        {
            "id": "patch-invalid",
            "targetType": "volume",
            "targetId": "volume-1",
            "expectedRevision": 1,
            "expectedHash": "a" * 64,
            "fieldPath": "purpose",
            "replacement": "不属于卷的字段",
            "evidence": _evidence(),
        },
    ]
    gateway = FinalizationExtractionGateway(transport=httpx.MockTransport(
        lambda request: _response(payload, request)
    ))

    result = await _call(
        gateway, "extract", provider=_provider(),
        model_name="finalization-model", manifest=_manifest(),
    )

    assert [item.id for item in result.planning_patches] == ["patch-valid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ("provider", "model"))
async def test_binding_drift_is_rejected_before_network(drift):
    requests = []
    provider = _provider()
    model_name = "finalization-model"
    if drift == "provider":
        provider["id"] = "other"
    else:
        model_name = "other"
    gateway = FinalizationExtractionGateway(transport=httpx.MockTransport(
        lambda request: requests.append(request) or _response(_extraction_payload(), request)
    ))

    with pytest.raises(FinalizationProviderError):
        await _call(
            gateway, "extract", provider=provider, model_name=model_name,
            manifest=_manifest(),
        )

    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, {}, {"findings": "bad"}])
async def test_invalid_quality_output_has_one_fixed_safe_error(payload, caplog):
    sentinel = "RAW_PROVIDER_SENTINEL"
    gateway = FinalizationQualityGateway(transport=httpx.MockTransport(
        lambda request: _response(payload if payload is not None else {"raw": sentinel}, request)
    ))

    with pytest.raises(FinalizationProviderError) as raised:
        await _call(
            gateway, "audit", provider=_provider(),
            model_name="finalization-model", manifest=_manifest(),
        )

    assert str(raised.value) == "Finalization provider failed"
    _assert_no_sensitive_error_graph(raised.value, (sentinel, "PRIVATE_API_KEY_SENTINEL"))
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_cancellation_is_propagated_as_clean_cancelled_error():
    async def handler(request):
        raise asyncio.CancelledError()

    gateway = FinalizationExtractionGateway(transport=httpx.MockTransport(handler))
    task = asyncio.create_task(_call(
        gateway, "extract", provider=_provider(),
        model_name="finalization-model", manifest=_manifest(),
    ))
    with pytest.raises(asyncio.CancelledError):
        await task
