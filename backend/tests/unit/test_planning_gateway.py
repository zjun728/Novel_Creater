from __future__ import annotations

import asyncio
import importlib
import json

import httpx
import pytest

from backend.domain.planning import DraftPlanningAggregate
from backend.gateways.planning_provider import (
    PlanningProvider,
    PlanningProviderError,
    PlanningProviderGateway,
)
from backend.tests.unit.test_provider_response_secret_scanning import (
    _assert_no_sensitive_error_graph,
)


def _provider() -> dict[str, object]:
    return {
        "provider_type": "openai-compatible",
        "base_url": "https://provider.example/v1",
        "api_key": "PRIVATE_API_KEY_SENTINEL",
        "temperature": 0.25,
        "max_output_tokens": 8_192,
    }


def _manifest() -> dict[str, object]:
    return {
        "basis": {
            "projectId": "project-1",
            "basisHash": "b" * 64,
            "draftRevision": 3,
            "draftHash": "a" * 64,
        },
        "draft": {
            "activeStoryBlockRef": "block-1",
            "volumes": [],
            "plots": [],
            "storyBlocks": [
                {
                    "clientNodeKey": "block-1",
                    "lifecycle": "active",
                    "order": 1,
                    "title": "保留的故事块",
                    "volumeRef": "volume-1",
                    "plotRefs": ["plot-1"],
                    "entrySituation": "旧城封锁。",
                    "blockGoal": "安全出城。",
                    "mainPressure": "追兵逼近。",
                    "expectedChange": "同伴建立信任。",
                    "openQuestions": ["谁泄露了路线？"],
                    "involvedCharacters": ["沈砚", "陆微"],
                    "stages": [
                        {
                            "clientNodeKey": "stage-1",
                            "lifecycle": "active",
                            "order": 1,
                            "title": "寻找缺口",
                            "purpose": "共享秘密。",
                            "dramaticQuestion": "能否找到出口？",
                            "sceneTasks": [
                                {
                                    "clientNodeKey": "task-1",
                                    "lifecycle": "active",
                                    "order": 1,
                                    "task": "确认守卫换班。",
                                    "completionEvidence": "取得换班记录。",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        "storyContext": {
            "premise": "MANIFEST_CONTENT_SENTINEL",
            "seed": {
                "title": "旧城抄录者",
                "genre": "历史奇幻",
                "logline": "抄录者必须在封城前保存会改变现实的地方志。",
                "protagonist": "沈砚，一名谨慎的抄录者。",
                "desire": "让被抹去的人重新留下姓名。",
                "coreConflict": "保存知识会引来追捕并改变既有秩序。",
                "worldPressure": "旧城封锁，朝廷禁止私人抄录。",
                "openingHook": "地方志提前写出了守门人的失踪。",
                "differentiation": "知识传播会真实改写地方秩序。",
            },
            "engine": {
                "name": "地方志改写循环",
                "storyPromise": "每次修复地方志都揭开一层被抹去的秩序。",
                "protagonistDesire": "让被抹去的人重新留下姓名。",
                "sustainedPressure": "封城与朝廷禁令持续收紧。",
                "growthDirection": "从独自抄录走向共同保存。",
                "conflictLoop": "找证据、改旧志、触发追捕、承担关系代价。",
                "ensembleRoles": [
                    {"role": "见证者", "purpose": "验证抄本并挑战主角。"}
                ],
                "advantageAndCost": "抄本能改变现实，但会制造新的关系债。",
                "satisfactionSources": ["旧案翻转"],
                "longFormVariation": ["旧城", "州府", "王朝档案"],
                "endingAnchor": "共同保存的地方志取代唯一权威抄本。",
                "risks": ["旧案结构重复"],
                "differentiation": "知识传播会真实改写地方秩序。",
            },
            "longFormCapacity": {
                "targetTotalWords": 900000,
                "expectedVolumeCount": 8,
                "expectedChapterCount": 300,
                "chapterWordRangePreference": [2800, 3600],
            },
            "protagonist": "沈砚会先验证事实，再决定公开多少真相。",
            "coreCharacters": [
                {"id": "cast-1", "text": "陆微有独立的救人目标。"}
            ],
            "relationshipDynamics": [
                {"id": "relation-1", "text": "信任依赖双方共享风险。"}
            ],
            "worldRules": [
                {"id": "world-1", "text": "被验证的抄本才能改变现实。"}
            ],
            "powerOrProgressionSystem": "修复地方志需要证据、见证人与代价。",
            "longTermConflicts": [
                {"id": "conflict-1", "text": "公开真相与维持秩序长期冲突。"}
            ],
            "toneAndNarrativeBoundaries": "克制解释，让选择承担后果。",
            "prohibitedDirections": ["不写无代价知识升级"],
            "continuityGuardrails": [
                {"id": "guard-1", "text": "不得提前揭示内应身份。"}
            ],
            "authorNotes": "人物关系优先。",
        },
    }


def _planning_payload() -> dict[str, object]:
    return {
        "activeStoryBlockRef": "block-1",
        "volumes": [
            {
                "clientNodeKey": "volume-1",
                "lifecycle": "active",
                "order": 1,
                "title": "第一卷",
                "coreChange": "从独行转向结盟。",
                "mainPressure": "旧城封锁。",
                "ensembleFocus": ["沈砚", "陆微"],
                "forbiddenEvents": ["提前揭示内应身份"],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "plot-1",
                "lifecycle": "active",
                "order": 1,
                "title": "失落典籍",
                "plotType": "main",
                "storyQuestion": "典籍能否安全传承？",
                "futureDirection": "寻找可信的抄录者。",
                "expectedPayoff": "知识被更多普通人掌握。",
                "relatedCharacters": ["沈砚", "陆微"],
            }
        ],
        "storyBlocks": _manifest()["draft"]["storyBlocks"],
    }


def _response(payload: object, *, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "completion-1",
            "object": "chat.completion",
            "created": 1,
            "model": "planning-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
            },
        },
        request=request,
    )


async def _generate_once(
    gateway: PlanningProviderGateway,
    **kwargs,
):
    await gateway.start()
    try:
        return await gateway.generate(**kwargs)
    finally:
        await gateway.aclose()


class _StaticRawStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self.content = content

    async def __aiter__(self):
        yield self.content

    async def aclose(self) -> None:
        return None


class _CloseAwareTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, overlap: bool = False):
        self.calls = 0
        self.close_calls = 0
        self.overlap = overlap
        self._both_entered = asyncio.Event()

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        if self.close_calls:
            raise RuntimeError("borrowed transport was already closed")
        self.calls += 1
        if self.overlap:
            if self.calls == 2:
                self._both_entered.set()
            await self._both_entered.wait()
        prepared = _response(_planning_payload(), request=request)
        return httpx.Response(
            prepared.status_code,
            headers=prepared.headers,
            stream=_StaticRawStream(prepared.content),
            request=request,
        )

    async def aclose(self) -> None:
        self.close_calls += 1


class _NeverReadCompressedStream(httpx.AsyncByteStream):
    def __init__(self):
        self.iterated = False
        self.closed = False

    async def __aiter__(self):
        self.iterated = True
        raise AssertionError("compressed response body must not be read")
        yield b"unreachable"

    async def aclose(self) -> None:
        self.closed = True


def test_concrete_gateway_satisfies_the_public_planning_provider_protocol():
    assert isinstance(
        PlanningProviderGateway(
            transport=httpx.MockTransport(
                lambda request: _response(
                    _planning_payload(), request=request
                )
            )
        ),
        PlanningProvider,
    )


@pytest.mark.asyncio
async def test_gateway_makes_one_bounded_json_call_and_returns_only_closed_payload(
    caplog,
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(_planning_payload(), request=request)

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    result = await _generate_once(
        gateway,
        provider={**_provider(), "temperature": 0.8},
        model_name="planning-model",
        manifest=_manifest(),
        author_instructions="扩展卷级变化。",
    )

    assert result == _planning_payload()
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://provider.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer PRIVATE_API_KEY_SENTINEL"
    body = json.loads(request.content)
    assert body["model"] == "planning-model"
    assert body["temperature"] == 0.4
    assert body["max_tokens"] == 8_192
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["stream"] is False
    assert [message["role"] for message in body["messages"]] == [
        "system",
        "user",
    ]
    assert "MANIFEST_CONTENT_SENTINEL" not in json.dumps(
        result, ensure_ascii=False
    )
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_gateway_assigns_internal_keys_when_generated_editable_nodes_omit_identity():
    payload = _planning_payload_without_generated_identities()
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: _response(payload, request=request)
        )
    )

    result = await _generate_once(
        gateway,
        provider=_provider(),
        model_name="planning-model",
        manifest=_manifest(),
        author_instructions="扩展卷级变化。",
    )

    assert result["volumes"][0]["clientNodeKey"] == "generated-volume-001"
    assert result["plots"][0]["clientNodeKey"] == "generated-plot-001"
    assert result["storyBlocks"] == _manifest()["draft"]["storyBlocks"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: {**value, "providerExtra": "RAW_OUTPUT_SENTINEL"},
        lambda value: {
            **value,
            "volumes": [
                {
                    **value["volumes"][0],
                    "providerExtra": "RAW_OUTPUT_SENTINEL",
                }
            ],
        },
        lambda value: {
            **value,
            "storyBlocks": [
                {
                    **value["storyBlocks"][0],
                    "stages": [
                        {
                            **value["storyBlocks"][0]["stages"][0],
                            "sceneTasks": [
                                {
                                    **value["storyBlocks"][0]["stages"][0][
                                        "sceneTasks"
                                    ][0],
                                    "providerExtra": "RAW_OUTPUT_SENTINEL",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    ),
)
async def test_gateway_rejects_extra_top_level_and_nested_provider_fields(
    mutate, caplog
):
    payload = mutate(_planning_payload())

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: _response(payload, request=request)
        )
    )
    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="扩展卷级变化。",
        )

    assert type(caught.value) is PlanningProviderError
    assert str(caught.value) == "Planning provider failed"
    assert "RAW_OUTPUT_SENTINEL" not in repr(caught.value)
    assert "RAW_OUTPUT_SENTINEL" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_body",
    (
        b"RAW_RESPONSE_SENTINEL",
        b'{"choices":[],"raw":"RAW_RESPONSE_SENTINEL"}',
        b'{"choices":[{"message":{"content":"RAW_RESPONSE_SENTINEL"}}]}',
        b'{"choices":[{"message":{"content":"[]"}}]}',
    ),
)
async def test_gateway_maps_every_malformed_response_to_one_fixed_safe_error(
    raw_body, caplog
):
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=raw_body,
                request=request,
            )
        )
    )

    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="AUTHOR_PROMPT_SENTINEL",
        )

    assert type(caught.value) is PlanningProviderError
    assert str(caught.value) == "Planning provider failed"
    exposed = repr(caught.value) + caplog.text
    assert all(
        marker not in exposed
        for marker in (
            "RAW_RESPONSE_SENTINEL",
            "MANIFEST_CONTENT_SENTINEL",
            "AUTHOR_PROMPT_SENTINEL",
            "PRIVATE_API_KEY_SENTINEL",
        )
    )


@pytest.mark.asyncio
async def test_gateway_rejects_provider_secret_echo_without_returning_or_logging_it(
    caplog,
):
    payload = _planning_payload()
    payload["volumes"][0]["title"] = (
        "prefix PRIVATE_API_KEY_SENTINEL suffix"
    )
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: _response(payload, request=request)
        )
    )

    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="扩展卷级变化。",
        )

    exposed = repr(caught.value) + caplog.text
    assert str(caught.value) == "Planning provider failed"
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
async def test_gateway_rejects_rewritten_frozen_story_block_content(caplog):
    payload = _planning_payload()
    payload["storyBlocks"][0]["stages"][0]["sceneTasks"][0]["task"] = (
        "RAW_REWRITE_SENTINEL"
    )
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: _response(payload, request=request)
        )
    )

    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="扩展卷级变化。",
        )

    exposed = repr(caught.value) + caplog.text
    assert str(caught.value) == "Planning provider failed"
    assert "RAW_REWRITE_SENTINEL" not in exposed


@pytest.mark.asyncio
async def test_gateway_holds_the_initial_manifest_snapshot_across_the_await():
    manifest = _manifest()

    def handler(request: httpx.Request) -> httpx.Response:
        manifest["draft"]["storyBlocks"][0]["title"] = "later mutation"
        return _response(_planning_payload(), request=request)

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    result = await _generate_once(
        gateway,
        provider=_provider(),
        model_name="planning-model",
        manifest=manifest,
        author_instructions="扩展卷级变化。",
    )

    assert result == _planning_payload()


@pytest.mark.asyncio
async def test_gateway_maps_http_and_runtime_configuration_failures_to_same_error(
    caplog,
):
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                503,
                text="RAW_HTTP_SENTINEL",
                request=request,
            )
        )
    )
    invalid_runtime = {
        **_provider(),
        "provider_type": "unsupported",
        "base_url": "https://PRIVATE_URL_SENTINEL/v1",
    }

    for provider in (_provider(), invalid_runtime):
        with pytest.raises(PlanningProviderError) as caught:
            await _generate_once(
                gateway,
                provider=provider,
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions="扩展卷级变化。",
            )
        assert type(caught.value) is PlanningProviderError
        assert str(caught.value) == "Planning provider failed"

    exposed = caplog.text
    assert all(
        marker not in exposed
        for marker in (
            "RAW_HTTP_SENTINEL",
            "PRIVATE_URL_SENTINEL",
            "PRIVATE_API_KEY_SENTINEL",
        )
    )


@pytest.mark.asyncio
async def test_gateway_rejects_runtime_secret_in_allowed_manifest_field_before_request(
    caplog,
):
    requests = []
    manifest = _manifest()
    manifest["storyContext"]["premise"] = (
        "prefix PRIVATE_API_KEY_SENTINEL suffix"
    )
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or _response(_planning_payload(), request=request)
        )
    )

    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=manifest,
            author_instructions="扩展卷级变化。",
        )

    assert requests == []
    assert str(caught.value) == "Planning provider failed"
    exposed = repr(caught.value) + caplog.text
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ("non_mapping", "draft_list", "missing_draft", "extra_manifest"),
)
async def test_gateway_rejects_invalid_manifest_before_provider_call(
    case, caplog
):
    requests = []
    manifest = _manifest()
    if case == "non_mapping":
        manifest = []
    elif case == "draft_list":
        manifest["draft"] = []
    elif case == "missing_draft":
        manifest.pop("draft")
    else:
        manifest["unknown"] = "UNKNOWN_MANIFEST_SENTINEL"
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or _response(_planning_payload(), request=request)
        )
    )

    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=manifest,
            author_instructions="扩展卷级变化。",
        )

    assert requests == []
    assert str(caught.value) == "Planning provider failed"
    assert "UNKNOWN_MANIFEST_SENTINEL" not in (
        repr(caught.value) + caplog.text
    )


@pytest.mark.asyncio
async def test_gateway_maps_malformed_url_to_fixed_error_without_echo(caplog):
    requests = []
    provider = {
        **_provider(),
        "base_url": "https://provider.example:PRIVATE_URL_SENTINEL/v1",
    }
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or _response(_planning_payload(), request=request)
        )
    )

    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=provider,
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="扩展卷级变化。",
        )

    assert requests == []
    assert str(caught.value) == "Planning provider failed"
    assert "PRIVATE_URL_SENTINEL" not in (
        repr(caught.value) + caplog.text
    )


@pytest.mark.asyncio
async def test_gateway_retains_required_nullable_active_story_block_ref():
    manifest = _manifest()
    manifest["draft"]["activeStoryBlockRef"] = None
    payload = _planning_payload()
    payload["activeStoryBlockRef"] = None
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: _response(payload, request=request)
        )
    )

    result = await _generate_once(
        gateway,
        provider=_provider(),
        model_name="planning-model",
        manifest=manifest,
        author_instructions="扩展卷级变化。",
    )

    assert "activeStoryBlockRef" in result
    assert result["activeStoryBlockRef"] is None
    assert DraftPlanningAggregate.model_validate(result, strict=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ("transport", "http", "json", "envelope", "domain"),
)
async def test_planning_safe_error_releases_all_sensitive_exception_references(
    failure,
    caplog,
):
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
            **_planning_payload(),
            "providerExtra": "DECODED_VALUE_SENTINEL",
        }
        return _response(payload, request=request)

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(PlanningProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="AUTHOR_INSTRUCTION_SENTINEL",
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
async def test_planning_gateway_uses_the_shared_bounded_json_transport(
    monkeypatch,
):
    module = importlib.import_module("backend.gateways.planning_provider")
    try:
        shared = importlib.import_module(
            "backend.gateways.openai_json_transport"
        )
    except ModuleNotFoundError:
        pytest.fail("shared OpenAI JSON transport is missing")
    instances = []

    class RecordingResource:
        def __init__(
            self,
            *,
            transport,
            timeout_seconds,
            response_byte_limit,
        ):
            self.transport = transport
            self.timeout_seconds = timeout_seconds
            self.response_byte_limit = response_byte_limit
            self.start_calls = 0
            self.close_calls = 0
            self.requests = []
            instances.append(self)

        async def start(self):
            self.start_calls += 1

        async def aclose(self):
            self.close_calls += 1

        async def request(self, **kwargs):
            self.requests.append(kwargs)
            return shared.OpenAIJSONTransportResult(
                succeeded=True,
                value=_planning_payload(),
            )

    monkeypatch.setattr(module, "OpenAIJSONTransport", RecordingResource)
    borrowed = httpx.MockTransport(
        lambda request: _response(_planning_payload(), request=request)
    )
    gateway = PlanningProviderGateway(transport=borrowed)
    await gateway.start()
    result = await gateway.generate(
        provider=_provider(),
        model_name="planning-model",
        manifest=_manifest(),
        author_instructions="AUTHOR_INSTRUCTION_SENTINEL",
    )
    second = await gateway.generate(
        provider=_provider(),
        model_name="planning-model",
        manifest=_manifest(),
        author_instructions="second",
    )
    await gateway.aclose()

    assert result == _planning_payload()
    assert second == _planning_payload()
    assert len(instances) == 1
    resource = instances[0]
    assert resource.transport is borrowed
    assert resource.timeout_seconds == module.PROVIDER_TIMEOUT_SECONDS
    assert resource.response_byte_limit == module.MAX_PROVIDER_RESPONSE_BYTES
    assert resource.start_calls == 1
    assert resource.close_calls == 1
    assert len(resource.requests) == 2
    assert resource.requests[0]["provider"] == {
        **_provider(),
        "thinking": {"type": "disabled"},
    }


def _planning_payload_without_generated_identities() -> dict[str, object]:
    payload = _planning_payload()
    for section in ("volumes", "plots"):
        for node in payload[section]:
            node.pop("clientNodeKey")
    return payload
    assert resource.requests[0]["model_name"] == "planning-model"
    assert [item["role"] for item in resource.requests[0]["messages"]] == [
        "system",
        "user",
    ]


@pytest.mark.asyncio
async def test_planning_cancellation_returns_fresh_secret_free_cancelled_error():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return _response(_planning_payload(), request=request)

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    await gateway.start()
    task = asyncio.create_task(
        gateway.generate(
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions=(
                "AUTHOR_INSTRUCTION_SENTINEL "
                "RAW_CANCELLATION_SENTINEL"
            ),
        )
    )
    try:
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
    finally:
        release.set()
        await gateway.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ("api_key", "base_url"))
async def test_complete_request_body_is_secret_scanned_before_transport(
    collision,
):
    provider = _provider()
    calls = []
    model_name = str(provider[collision])

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: calls.append(request)
            or _response(_planning_payload(), request=request)
        )
    )
    with pytest.raises(PlanningProviderError):
        await _generate_once(
            gateway,
            provider=provider,
            model_name=model_name,
            manifest=_manifest(),
            author_instructions="ordinary",
        )

    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("content_encoding", ("gzip", "br"))
async def test_nonidentity_content_encoding_is_rejected_without_body_read(
    content_encoding,
):
    stream = _NeverReadCompressedStream()
    accept_encoding = []

    def handler(request: httpx.Request) -> httpx.Response:
        accept_encoding.append(request.headers.get("accept-encoding"))
        return httpx.Response(
            200,
            headers={
                "content-encoding": content_encoding,
                "content-length": "64",
            },
            stream=stream,
            request=request,
        )

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(PlanningProviderError):
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="ordinary",
        )

    assert accept_encoding == ["identity"]
    assert stream.iterated is False
    assert stream.closed is True


@pytest.mark.asyncio
async def test_injected_transport_is_borrowed_across_sequential_calls():
    transport = _CloseAwareTransport()
    gateway = PlanningProviderGateway(transport=transport)

    await gateway.start()
    try:
        first = await gateway.generate(
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="first",
        )
        second = await gateway.generate(
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions="second",
        )
    finally:
        await gateway.aclose()

    assert first == _planning_payload()
    assert second == _planning_payload()
    assert transport.calls == 2
    assert transport.close_calls == 0


@pytest.mark.asyncio
async def test_injected_transport_is_borrowed_across_overlapping_calls():
    transport = _CloseAwareTransport(overlap=True)
    gateway = PlanningProviderGateway(transport=transport)

    await gateway.start()
    try:
        first, second = await asyncio.gather(
            gateway.generate(
                provider=_provider(),
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions="first",
            ),
            gateway.generate(
                provider=_provider(),
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions="second",
            ),
        )
    finally:
        await gateway.aclose()

    assert first == _planning_payload()
    assert second == _planning_payload()
    assert transport.calls == 2
    assert transport.close_calls == 0


class _DrainGateStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self._content = content
        self.read_started = asyncio.Event()
        self.read_release = asyncio.Event()
        self.close_calls = 0

    async def __aiter__(self):
        self.read_started.set()
        await self.read_release.wait()
        yield self._content

    async def aclose(self) -> None:
        self.close_calls += 1
        self._content = b""


class _DrainAwareTransport(httpx.AsyncBaseTransport):
    def __init__(self, stream: _DrainGateStream):
        self._stream = stream
        self.calls = 0
        self.requests: list[httpx.Request] = []
        self.close_calls = 0

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        self.calls += 1
        self.requests.append(request)
        return httpx.Response(
            200,
            stream=self._stream,
            request=request,
        )

    async def aclose(self) -> None:
        self.close_calls += 1


async def _wait_for_resource_state(resource, state: str) -> None:
    async with asyncio.timeout(1):
        while resource.state != state:
            next_turn = asyncio.Event()
            asyncio.get_running_loop().call_soon(next_turn.set)
            await next_turn.wait()


async def _next_event_loop_turn() -> None:
    next_turn = asyncio.Event()
    asyncio.get_running_loop().call_soon(next_turn.set)
    await asyncio.wait_for(next_turn.wait(), timeout=1)


def _traceback_reaches_any(error: BaseException, targets: tuple[object, ...]):
    target_ids = {id(target) for target in targets}
    pending = []
    traceback = error.__traceback__
    while traceback is not None:
        filename = traceback.tb_frame.f_code.co_filename.replace("\\", "/")
        if "/backend/tests/" not in filename:
            pending.extend(traceback.tb_frame.f_locals.values())
        traceback = traceback.tb_next

    seen = set()
    while pending:
        value = pending.pop()
        if value is None or id(value) in seen:
            continue
        if id(value) in target_ids:
            return True
        seen.add(id(value))
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif type(value).__module__.startswith(("backend.", "httpx.")):
            try:
                pending.extend(vars(value).values())
            except TypeError:
                pass
    return False


@pytest.mark.asyncio
async def test_planning_close_drains_active_generate_and_rejects_late_generate(
):
    prepared = _response(
        _planning_payload(),
        request=httpx.Request(
            "POST",
            "https://provider.example/v1/chat/completions",
        ),
    )
    stream = _DrainGateStream(prepared.content)
    transport = _DrainAwareTransport(stream)
    gateway = PlanningProviderGateway(transport=transport)
    resource = gateway._resource
    generate_task = None
    close_task = None
    late_task = None
    lock_held = False
    close_entered = asyncio.Event()

    async def close_gateway() -> None:
        close_entered.set()
        await gateway.aclose()

    await asyncio.wait_for(gateway.start(), timeout=1)
    try:
        generate_task = asyncio.create_task(
            gateway.generate(
                provider=_provider(),
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions="original",
            )
        )
        await asyncio.wait_for(stream.read_started.wait(), timeout=1)

        await asyncio.wait_for(resource._lock.acquire(), timeout=1)
        lock_held = True
        close_task = asyncio.create_task(close_gateway())
        await asyncio.wait_for(close_entered.wait(), timeout=1)
        late_task = asyncio.create_task(
            gateway.generate(
                provider=_provider(),
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions="late",
            )
        )
        resource._lock.release()
        lock_held = False

        with pytest.raises(PlanningProviderError) as caught:
            await asyncio.wait_for(late_task, timeout=1)
        assert str(caught.value) == "Planning provider failed"
        assert transport.calls == 1
        assert resource.state == "draining"
        assert close_task.done() is False

        stream.read_release.set()
        assert await asyncio.wait_for(generate_task, timeout=1) == (
            _planning_payload()
        )
        await asyncio.wait_for(close_task, timeout=1)

        assert stream.close_calls == 1
        assert transport.close_calls == 0
        assert resource.active_calls == 0
        assert resource.cleanup_task_count == 0
        assert resource.state == "closed"
        assert resource._start_task is None
        assert resource._close_task is None
        assert generate_task.done() is True
        assert late_task.done() is True
        assert close_task.done() is True
    finally:
        if lock_held:
            resource._lock.release()
        stream.read_release.set()
        for task in (generate_task, late_task, close_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1)
                except BaseException:
                    pass
        await asyncio.wait_for(gateway.aclose(), timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_planning_cancelled_late_start_has_clean_traceback_and_keeps_close(
    cancel_count,
):
    prompt_sentinel = "LATE_START_PROMPT_SENTINEL"
    prepared = _response(
        _planning_payload(),
        request=httpx.Request(
            "POST",
            "https://provider.example/v1/chat/completions",
        ),
    )
    stream = _DrainGateStream(prepared.content)
    transport = _DrainAwareTransport(stream)
    gateway = PlanningProviderGateway(transport=transport)
    resource = gateway._resource
    generate_task = None
    close_task = None
    start_task = None

    await asyncio.wait_for(gateway.start(), timeout=1)
    try:
        generate_task = asyncio.create_task(
            gateway.generate(
                provider=_provider(),
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions=prompt_sentinel,
            )
        )
        await asyncio.wait_for(stream.read_started.wait(), timeout=1)
        assert transport.calls == 1
        request = transport.requests[0]
        assert prompt_sentinel in request.content.decode("utf-8")

        close_task = asyncio.create_task(gateway.aclose())
        await _wait_for_resource_state(resource, "draining")
        shared_close = resource._close_task
        assert shared_close is not None
        assert shared_close.done() is False

        start_task = asyncio.create_task(gateway.start())
        await _next_event_loop_turn()
        assert start_task.done() is False
        for _ in range(cancel_count):
            start_task.cancel()

        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(start_task, timeout=1)

        assert caught.value.args == ()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert start_task.cancelling() == cancel_count
        assert _traceback_reaches_any(
            caught.value,
            (gateway, resource, transport, request),
        ) is False
        _assert_no_sensitive_error_graph(
            caught.value,
            (
                "PRIVATE_API_KEY_SENTINEL",
                "https://provider.example/v1",
                prompt_sentinel,
                "MANIFEST_CONTENT_SENTINEL",
                "authorization",
            ),
        )
        assert resource._close_task is shared_close
        assert shared_close.cancelled() is False
        assert shared_close.done() is False

        stream.read_release.set()
        assert await asyncio.wait_for(generate_task, timeout=1) == (
            _planning_payload()
        )
        await asyncio.wait_for(close_task, timeout=1)

        assert stream.close_calls == 1
        assert transport.calls == 1
        assert transport.close_calls == 0
        assert resource.state == "closed"
        assert resource.active_calls == 0
        assert resource.cleanup_task_count == 0
        assert resource._close_task is None
        assert shared_close.done() is True
        assert shared_close.cancelled() is False
    finally:
        stream.read_release.set()
        for task in (generate_task, start_task, close_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1)
                except BaseException:
                    pass
        await asyncio.wait_for(gateway.aclose(), timeout=1)


class _OwnedPlanningClient:
    def __init__(self):
        self.calls = 0
        self.close_calls = 0

    def build_request(
        self,
        method,
        url,
        *,
        headers,
        content,
    ) -> httpx.Request:
        return httpx.Request(
            method,
            url,
            headers=headers,
            content=content,
        )

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool,
    ) -> httpx.Response:
        assert stream is True
        self.calls += 1
        prepared = _response(_planning_payload(), request=request)
        return httpx.Response(
            200,
            headers=prepared.headers,
            stream=_StaticRawStream(prepared.content),
            request=request,
        )

    async def aclose(self) -> None:
        self.close_calls += 1


class _OwnedPlanningClientFactory:
    def __init__(self):
        self.clients: list[_OwnedPlanningClient] = []

    def __call__(self, **_kwargs):
        client = _OwnedPlanningClient()
        self.clients.append(client)
        return client


@pytest.mark.asyncio
async def test_planning_explicit_restart_keeps_resource_and_uses_new_owned_client(
    monkeypatch,
):
    shared = importlib.import_module(
        "backend.gateways.openai_json_transport"
    )
    factory = _OwnedPlanningClientFactory()
    monkeypatch.setattr(shared.httpx, "AsyncClient", factory)
    gateway = PlanningProviderGateway()
    resource = gateway._resource

    try:
        await asyncio.wait_for(gateway.start(), timeout=1)
        first = await asyncio.wait_for(
            gateway.generate(
                provider=_provider(),
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions="first lifecycle",
            ),
            timeout=1,
        )
        await asyncio.wait_for(gateway.aclose(), timeout=1)
        await asyncio.wait_for(gateway.start(), timeout=1)
        second = await asyncio.wait_for(
            gateway.generate(
                provider=_provider(),
                model_name="planning-model",
                manifest=_manifest(),
                author_instructions="second lifecycle",
            ),
            timeout=1,
        )
        await asyncio.wait_for(gateway.aclose(), timeout=1)
    finally:
        await asyncio.wait_for(gateway.aclose(), timeout=1)

    assert gateway._resource is resource
    assert first == _planning_payload()
    assert second == _planning_payload()
    assert len(factory.clients) == 2
    assert [client.calls for client in factory.clients] == [1, 1]
    assert [client.close_calls for client in factory.clients] == [1, 1]
    assert resource.active_calls == 0
    assert resource.cleanup_task_count == 0
    assert resource.state == "closed"


class _CancellationProbeStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes, *, block_read: bool):
        self._content = content
        self._block_read = block_read
        self.read_started = asyncio.Event()
        self.read_release = asyncio.Event()
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_completed = asyncio.Event()
        self.close_calls = 0

    async def __aiter__(self):
        self.read_started.set()
        if self._block_read:
            await self.read_release.wait()
        yield self._content

    async def aclose(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await self.close_release.wait()
        self._content = b""
        self.close_completed.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during", ("body-read", "response-close"))
async def test_planning_gateway_repeated_cancellation_waits_for_clean_response_close(
    cancel_during,
):
    payload = _planning_payload()
    payload["volumes"][0]["title"] = "DECODED_CANCELLED_SENTINEL"
    prepared = _response(
        payload,
        request=httpx.Request(
            "POST",
            "https://provider.example/v1/chat/completions",
        ),
    )
    stream = _CancellationProbeStream(
        prepared.content,
        block_read=cancel_during == "body-read",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=stream,
            request=request,
        )

    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    await gateway.start()
    task = asyncio.create_task(
        gateway.generate(
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions=(
                "AUTHOR_INSTRUCTION_SENTINEL "
                "RAW_CANCELLATION_SENTINEL"
            ),
        )
    )
    try:
        if cancel_during == "body-read":
            await asyncio.wait_for(stream.read_started.wait(), timeout=1)
            task.cancel()
            await asyncio.wait_for(stream.close_started.wait(), timeout=1)
            task.cancel()
            task.cancel()
        else:
            await asyncio.wait_for(stream.close_started.wait(), timeout=1)
            task.cancel()
            task.cancel()
            task.cancel()

        assert task.done() is False
        stream.close_release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=1)

        assert caught.value.args == ()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert task.cancelling() == 3
        assert stream.close_calls == 1
        assert stream.close_completed.is_set()
        _assert_no_sensitive_error_graph(
            caught.value,
            (
                "PRIVATE_API_KEY_SENTINEL",
                "https://provider.example/v1",
                "AUTHOR_INSTRUCTION_SENTINEL",
                "RAW_CANCELLATION_SENTINEL",
                "DECODED_CANCELLED_SENTINEL",
                "MANIFEST_CONTENT_SENTINEL",
                "authorization",
            ),
        )
    finally:
        stream.read_release.set()
        stream.close_release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(gateway.aclose(), timeout=1)
