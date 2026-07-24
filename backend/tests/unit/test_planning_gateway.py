from __future__ import annotations

import json

import httpx
import pytest

from backend.gateways.planning_provider import (
    PlanningProvider,
    PlanningProviderError,
    PlanningProviderGateway,
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
        "storyContext": {"premise": "MANIFEST_CONTENT_SENTINEL"},
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
