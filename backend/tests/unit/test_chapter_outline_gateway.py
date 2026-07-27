from __future__ import annotations

import asyncio
import importlib
import json
from urllib.parse import quote

import httpx
import pytest

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.tests.unit.test_chapter_outline_prompt import _manifest
from backend.tests.unit.test_provider_response_secret_scanning import (
    _assert_no_sensitive_error_graph,
)


def _gateway_module():
    try:
        return importlib.import_module(
            "backend.gateways.chapter_outline_provider"
        )
    except ModuleNotFoundError:
        pytest.fail("chapter outline Provider gateway is missing")


def _provider() -> dict[str, object]:
    return {
        "id": "provider-1",
        "provider_type": "openai-compatible",
        "base_url": "https://provider.example/v1",
        "api_key": "PRIVATE_API_KEY_SENTINEL",
        "temperature": 0.25,
        "max_output_tokens": 8_192,
    }


def _ref(node) -> dict[str, object]:
    return {
        "id": node.id,
        "revision": node.revision,
        "contentHash": node.content_hash,
    }


def _outline_payload(manifest=None) -> dict[str, object]:
    manifest = manifest or _manifest()
    return {
        "schemaVersion": "chapter-outline-draft-v1",
        "volumeRef": _ref(manifest.volume),
        "storyBlockRef": _ref(manifest.story_block),
        "stageRefs": [_ref(node) for node in manifest.allowed_stages],
        "sceneTaskRefs": [
            _ref(node) for node in manifest.allowed_scene_tasks
        ],
        "chapterGoal": "Find a safe path through the blockade.",
        "expectedCharacters": ["Shen Yan", "Lu Zhao"],
        "continuation": ["Continue the trapped-at-the-gate situation."],
        "plannedTasks": ["Observe the guard change.", "Test the culvert."],
        "scenes": ["Night reconnaissance.", "A costly test of trust."],
        "forbiddenEarlyEvents": ["Do not reveal the traitor."],
    }


def _response(
    payload: object,
    *,
    request: httpx.Request,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False)
                    }
                }
            ]
        },
        request=request,
    )


def test_concrete_gateway_satisfies_the_public_outline_provider_protocol():
    module = _gateway_module()

    assert isinstance(
        module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(
                lambda request: _response(
                    _outline_payload(),
                    request=request,
                )
            )
        ),
        module.ChapterOutlineProvider,
    )


@pytest.mark.asyncio
async def test_gateway_makes_one_bounded_structured_call_and_returns_domain_value(
    caplog,
    monkeypatch,
):
    module = _gateway_module()
    manifest = _manifest()
    requests: list[httpx.Request] = []
    parse_calls = 0
    original_validate = EditableChapterOutlineContent.model_validate

    def counted_validate(value, *, strict):
        nonlocal parse_calls
        parse_calls += 1
        return original_validate(value, strict=strict)

    monkeypatch.setattr(
        EditableChapterOutlineContent,
        "model_validate",
        counted_validate,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(_outline_payload(manifest), request=request)

    result = await module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(handler)
    ).generate(
        provider=_provider(),
        model_name="outline-model",
        manifest=manifest,
    )

    assert type(result) is EditableChapterOutlineContent
    assert result.chapter_goal == "Find a safe path through the blockade."
    assert parse_calls == 1
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://provider.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer PRIVATE_API_KEY_SENTINEL"
    body = json.loads(request.content)
    assert body["model"] == "outline-model"
    assert body["temperature"] == 0.25
    assert body["max_tokens"] == 8_192
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    assert caplog.text == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ("provider", "model"))
async def test_gateway_rejects_non_planning_binding_identity_before_call(
    drift,
    caplog,
):
    module = _gateway_module()
    requests = []
    provider = _provider()
    model_name = "outline-model"
    if drift == "provider":
        provider["id"] = "provider-2"
    else:
        model_name = "different-model"

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(
                lambda request: requests.append(request)
                or _response(_outline_payload(), request=request)
            )
        ).generate(
            provider=provider,
            model_name=model_name,
            manifest=_manifest(),
        )

    assert requests == []
    assert type(caught.value) is module.ChapterOutlineProviderError
    assert str(caught.value) == "Chapter outline provider failed"
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_gateway_scans_prompt_for_runtime_secret_before_provider_call(
    caplog,
):
    module = _gateway_module()
    requests = []
    manifest = _manifest(
        author_instructions="Repeat PRIVATE_API_KEY_SENTINEL in the answer."
    )

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(
                lambda request: requests.append(request)
                or _response(_outline_payload(), request=request)
            )
        ).generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=manifest,
        )

    assert requests == []
    exposed = repr(caught.value) + caplog.text
    assert str(caught.value) == "Chapter outline provider failed"
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
async def test_gateway_scans_raw_response_before_json_or_structured_parse(
    monkeypatch,
    caplog,
):
    module = _gateway_module()
    raw_secret = quote(str(_provider()["base_url"]), safe="")

    def fail_json_parse(_value):
        pytest.fail("secret-bearing raw response reached JSON parsing")

    shared = importlib.import_module(
        "backend.gateways.openai_json_transport"
    )
    monkeypatch.setattr(shared.json, "loads", fail_json_parse)
    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=f'{{"echo":"{raw_secret}"}}'.encode(),
                request=request,
            )
        )
    )

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await gateway.generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        )

    assert str(caught.value) == "Chapter outline provider failed"
    exposed = repr(caught.value) + caplog.text
    assert raw_secret not in exposed
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: {**value, "providerExtra": "RAW_OUTPUT_SENTINEL"},
        lambda value: {
            **value,
            "stageRefs": [
                {**value["stageRefs"][0], "id": "invented-stage-id"}
            ],
        },
        lambda value: {
            **value,
            "sceneTaskRefs": list(reversed(value["sceneTaskRefs"])),
        },
    ),
)
async def test_gateway_rejects_extra_or_non_exact_allowed_refs_without_logging(
    mutate,
    caplog,
):
    module = _gateway_module()
    payload = mutate(_outline_payload())

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(
                lambda request: _response(payload, request=request)
            )
        ).generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        )

    assert str(caught.value) == "Chapter outline provider failed"
    exposed = repr(caught.value) + caplog.text
    assert "RAW_OUTPUT_SENTINEL" not in exposed
    assert "invented-stage-id" not in exposed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_body",
    (
        b"RAW_RESPONSE_SENTINEL",
        b'{"choices":[],"raw":"RAW_RESPONSE_SENTINEL"}',
        b'{"choices":[{"message":{"content":"[]"}}]}',
    ),
)
async def test_gateway_maps_malformed_response_to_fixed_safe_category(
    raw_body,
    caplog,
):
    module = _gateway_module()
    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=raw_body,
                request=request,
            )
        )
    )

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await gateway.generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        )

    assert type(caught.value) is module.ChapterOutlineProviderError
    assert str(caught.value) == "Chapter outline provider failed"
    exposed = repr(caught.value) + caplog.text
    assert "RAW_RESPONSE_SENTINEL" not in exposed
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
async def test_gateway_rejects_oversized_or_http_error_responses_safely(caplog):
    module = _gateway_module()
    responses = (
        lambda request: httpx.Response(
            200,
            headers={
                "content-length": str(module.MAX_PROVIDER_RESPONSE_BYTES + 1)
            },
            request=request,
        ),
        lambda request: httpx.Response(
            503,
            text="RAW_HTTP_SENTINEL",
            request=request,
        ),
    )

    for response in responses:
        with pytest.raises(module.ChapterOutlineProviderError) as caught:
            await module.ChapterOutlineProviderGateway(
                transport=httpx.MockTransport(response)
            ).generate(
                provider=_provider(),
                model_name="outline-model",
                manifest=_manifest(),
            )
        assert str(caught.value) == "Chapter outline provider failed"

    assert "RAW_HTTP_SENTINEL" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ("transport", "http", "json", "envelope", "domain"),
)
async def test_safe_error_releases_all_sensitive_exception_references(
    failure,
    caplog,
):
    module = _gateway_module()
    manifest = _manifest(
        author_instructions="AUTHOR_INSTRUCTION_SENTINEL"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "transport":
            raise httpx.ConnectError(
                "REMOTE_FAILURE_SENTINEL",
                request=request,
            )
        if failure == "http":
            return httpx.Response(
                503,
                content=b"RAW_HTTP_BODY_SENTINEL",
                request=request,
            )
        if failure == "json":
            return httpx.Response(
                200,
                content=b'{"RAW_RESPONSE_SENTINEL":',
                request=request,
            )
        if failure == "envelope":
            return httpx.Response(
                200,
                json={
                    "choices": [],
                    "raw": "DECODED_ENVELOPE_SENTINEL",
                },
                request=request,
            )
        payload = {
            **_outline_payload(manifest),
            "providerExtra": "DECODED_VALUE_SENTINEL",
        }
        return _response(payload, request=request)

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(handler)
        ).generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=manifest,
        )

    _assert_no_sensitive_error_graph(
        caught.value,
        (
            "PRIVATE_API_KEY_SENTINEL",
            "AUTHOR_INSTRUCTION_SENTINEL",
            "REMOTE_FAILURE_SENTINEL",
            "RAW_HTTP_BODY_SENTINEL",
            "RAW_RESPONSE_SENTINEL",
            "DECODED_ENVELOPE_SENTINEL",
            "DECODED_VALUE_SENTINEL",
            "Authorization",
        ),
    )
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_gateway_uses_the_shared_bounded_json_transport(monkeypatch):
    module = _gateway_module()
    try:
        shared = importlib.import_module(
            "backend.gateways.openai_json_transport"
        )
    except ModuleNotFoundError:
        pytest.fail("shared OpenAI JSON transport is missing")
    calls = []

    async def fake_transport(**kwargs):
        calls.append(kwargs)
        return shared.OpenAIJSONTransportResult(
            succeeded=True,
            value=_outline_payload(),
        )

    monkeypatch.setattr(module, "request_openai_json", fake_transport)
    result = await module.ChapterOutlineProviderGateway().generate(
        provider=_provider(),
        model_name="outline-model",
        manifest=_manifest(),
    )

    assert type(result) is EditableChapterOutlineContent
    assert len(calls) == 1
    assert calls[0]["provider"] == _provider()
    assert calls[0]["model_name"] == "outline-model"
    assert calls[0]["max_response_bytes"] == module.MAX_PROVIDER_RESPONSE_BYTES
    assert calls[0]["timeout_seconds"] == module.PROVIDER_TIMEOUT_SECONDS
    assert [item["role"] for item in calls[0]["messages"]] == [
        "system",
        "user",
    ]


@pytest.mark.asyncio
async def test_cancellation_returns_a_fresh_secret_free_cancelled_error():
    module = _gateway_module()
    entered = asyncio.Event()
    release = asyncio.Event()
    manifest = _manifest(
        author_instructions=(
            "AUTHOR_INSTRUCTION_SENTINEL "
            "RAW_CANCELLATION_SENTINEL"
        )
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return _response(_outline_payload(manifest), request=request)

    task = asyncio.create_task(
        module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(handler)
        ).generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=manifest,
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError) as caught:
        await task

    assert task.cancelled() is True
    _assert_no_sensitive_error_graph(
        caught.value,
        (
            "PRIVATE_API_KEY_SENTINEL",
            "https://provider.example/v1",
            "AUTHOR_INSTRUCTION_SENTINEL",
            "RAW_CANCELLATION_SENTINEL",
            "authorization",
        ),
    )
