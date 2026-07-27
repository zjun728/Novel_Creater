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

    result = await PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    ).generate(
        provider=_provider(),
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
    assert body["temperature"] == 0.25
    assert body["max_tokens"] == 8_192
    assert body["response_format"] == {"type": "json_object"}
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
        await gateway.generate(
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
        await gateway.generate(
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
        await gateway.generate(
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
        await gateway.generate(
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

    result = await PlanningProviderGateway(
        transport=httpx.MockTransport(handler)
    ).generate(
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
            await gateway.generate(
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
        await gateway.generate(
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
        await gateway.generate(
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
        await gateway.generate(
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

    result = await gateway.generate(
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

    with pytest.raises(PlanningProviderError) as caught:
        await PlanningProviderGateway(
            transport=httpx.MockTransport(handler)
        ).generate(
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
    calls = []

    async def fake_transport(**kwargs):
        calls.append(kwargs)
        return shared.OpenAIJSONTransportResult(
            succeeded=True,
            value=_planning_payload(),
        )

    monkeypatch.setattr(module, "request_openai_json", fake_transport)
    result = await PlanningProviderGateway().generate(
        provider=_provider(),
        model_name="planning-model",
        manifest=_manifest(),
        author_instructions="AUTHOR_INSTRUCTION_SENTINEL",
    )

    assert result == _planning_payload()
    assert len(calls) == 1
    assert calls[0]["provider"] == _provider()
    assert calls[0]["model_name"] == "planning-model"
    assert calls[0]["max_response_bytes"] == module.MAX_PROVIDER_RESPONSE_BYTES
    assert calls[0]["timeout_seconds"] == module.PROVIDER_TIMEOUT_SECONDS
    assert [item["role"] for item in calls[0]["messages"]] == [
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

    task = asyncio.create_task(
        PlanningProviderGateway(
            transport=httpx.MockTransport(handler)
        ).generate(
            provider=_provider(),
            model_name="planning-model",
            manifest=_manifest(),
            author_instructions=(
                "AUTHOR_INSTRUCTION_SENTINEL "
                "RAW_CANCELLATION_SENTINEL"
            ),
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


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ("api_key", "base_url"))
async def test_complete_request_body_is_secret_scanned_before_transport(
    collision,
):
    provider = _provider()
    calls = []
    model_name = str(provider[collision])

    with pytest.raises(PlanningProviderError):
        await PlanningProviderGateway(
            transport=httpx.MockTransport(
                lambda request: calls.append(request)
                or _response(_planning_payload(), request=request)
            )
        ).generate(
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

    with pytest.raises(PlanningProviderError):
        await PlanningProviderGateway(
            transport=httpx.MockTransport(handler)
        ).generate(
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

    assert first == _planning_payload()
    assert second == _planning_payload()
    assert transport.calls == 2
    assert transport.close_calls == 0


@pytest.mark.asyncio
async def test_injected_transport_is_borrowed_across_overlapping_calls():
    transport = _CloseAwareTransport(overlap=True)
    gateway = PlanningProviderGateway(transport=transport)

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

    assert first == _planning_payload()
    assert second == _planning_payload()
    assert transport.calls == 2
    assert transport.close_calls == 0
