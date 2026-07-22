from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from backend.domain.assets import StylePromptPayload
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption
from backend.domain.style_trials import (
    STYLE_TRIAL_MAX_SAMPLE_LENGTH,
    StyleTrialProviderOutput,
)
from backend.gateways.style_trial_provider import (
    StyleTrialProviderError,
    StyleTrialProviderGateway,
)
from backend.prompts.style_trial import (
    STYLE_TRIAL_MAX_PROMPT_BYTES,
    build_style_trial_messages,
)


def _seed() -> SeedPayload:
    return SeedPayload(
        title="典镇山河",
        genre="历史穿越",
        logline="守住一部失散的典籍",
        protagonist="沈砚",
        desire="让同伴活着离开",
        coreConflict="知识能救人也会招来争夺",
        worldPressure="战乱正在逼近城门",
        openingHook="典籍残页在火场中显字",
        differentiation="知识的使用总伴随可见代价",
    )


def _engine() -> StoryEngineOption:
    return StoryEngineOption.model_validate(
        {
            "name": "残典求生",
            "storyPromise": "以知识改变处境，但每次改变都会制造新债",
            "protagonistDesire": "保住同伴与残典",
            "sustainedPressure": "官府、豪强与战乱持续收紧生存空间",
            "growthDirection": "从独自判断走向组织可信的人",
            "conflictLoop": "发现线索、争取资源、承担代价、形成新压力",
            "ensembleRoles": ({"role": "抄书匠", "purpose": "质疑知识是否值得牺牲"},),
            "advantageAndCost": "懂典籍旧制，但暴露得越多越危险",
            "satisfactionSources": ("知识落地解决现实难题",),
            "longFormVariation": ("地方生存", "制度博弈"),
            "endingAnchor": "让知识从私藏变成可以传承的秩序",
            "risks": ("避免把知识写成万能答案",),
            "differentiation": "每次解决问题都必须改变人物关系",
        },
        strict=True,
    )


def _style(anchor: str) -> StylePromptPayload:
    return StylePromptPayload.model_validate(
        {
            "schemaVersion": "style-template-v1",
            "reading_experience": "先看人物做选择，再理解规则",
            "applicability": ("历史穿越",),
            "non_applicability": ("纯设定讲解",),
            "standard_scene_example": "这是经过审定的短示例。",
            "complete_application_example": "这是另一段经过审定的完整示例。",
            "narrative_distance": "贴近当下判断",
            "rhythm": "压力、选择、后果",
            "diction_density": "具体动词优先",
            "dialogue": "人物各说各的现实账",
            "subtext": "真正诉求藏在条件里",
            "character_voices": "声音由欲望与关系区分",
            "emotion": "情绪改变行动",
            "interiority": "念头落到决定上",
            "action": "动作改变局面",
            "explanation": "先后果后规则",
            "environment": "环境约束行动",
            "body_response": "疲惫影响判断",
            "preferred_techniques": ("让代价可见",),
            "risks": ("避免任务清单感",),
            "original_anchor": anchor,
        },
        strict=True,
    )


def test_prompt_contains_only_bounded_frozen_story_facts_and_no_provider_config():
    messages = build_style_trial_messages(
        seed=_seed(),
        engine=_engine(),
        primary_style=_style("主风格锚点"),
        secondary_style=_style("辅风格锚点"),
        author_scenario="主角在城门关闭前，必须决定救人还是保住残页。",
    )

    rendered = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    assert len(rendered.encode("utf-8")) <= STYLE_TRIAL_MAX_PROMPT_BYTES
    assert "主角在城门关闭前" in rendered
    assert "主风格锚点" in rendered
    assert "辅风格锚点" in rendered
    assert "apiKey" not in rendered
    assert "baseURL" not in rendered
    assert "providerId" not in rendered
    assert "corpus" not in rendered.lower()
    assert "候选" not in rendered
    assert "Canon" not in rendered


def test_provider_output_is_strict_and_sample_is_bounded():
    assert StyleTrialProviderOutput(sample="一段原创正文").sample == "一段原创正文"
    with pytest.raises(ValidationError):
        StyleTrialProviderOutput.model_validate(
            {"sample": "x" * (STYLE_TRIAL_MAX_SAMPLE_LENGTH + 1)}, strict=True
        )
    with pytest.raises(ValidationError):
        StyleTrialProviderOutput.model_validate(
            {"sample": "正文", "selected": True}, strict=True
        )


@pytest.mark.asyncio
async def test_gateway_makes_one_bounded_call_and_returns_validated_output():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"sample":"原创试写"}'}}]},
        )

    gateway = StyleTrialProviderGateway(transport=httpx.MockTransport(handler))
    result = await gateway.generate(
        provider={
            "model_name": "safe-model",
            "base_url": "https://provider.test/v1",
            "api_key": "unit-test-secret",
        },
        messages=({"role": "user", "content": "bounded"},),
        generation_config={"temperature": 0.7, "maxOutputTokens": 2048},
    )

    assert result == StyleTrialProviderOutput(sample="原创试写")
    assert len(calls) == 1
    assert calls[0].url == httpx.URL("https://provider.test/v1/chat/completions")


@pytest.mark.asyncio
async def test_gateway_rejects_invalid_or_secret_bearing_output_without_repair():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"sample":"unit-test-secret"}'}}
                ]
            },
        )

    gateway = StyleTrialProviderGateway(transport=httpx.MockTransport(handler))
    with pytest.raises(StyleTrialProviderError):
        await gateway.generate(
            provider={
                "model_name": "safe-model",
                "base_url": "https://provider.test/v1",
                "api_key": "unit-test-secret",
            },
            messages=({"role": "user", "content": "bounded"},),
            generation_config={"temperature": 0.7, "maxOutputTokens": 2048},
        )
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("secret_field", "secret"),
    (("api_key", "abc"), ("base_url", "url7")),
)
async def test_gateway_rejects_short_secret_substrings_in_output_without_repair(
    secret_field, secret,
):
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": f'{{"sample":"x{secret}x"}}'}}
                ]
            },
        )

    provider = {
        "model_name": "safe-model",
        "base_url": "https://provider.test/v1",
        "api_key": "unit-test-secret",
    }
    provider[secret_field] = secret
    gateway = StyleTrialProviderGateway(transport=httpx.MockTransport(handler))
    if secret_field == "base_url":
        gateway._endpoint = lambda _base_url: "https://provider.test/chat/completions"

    with pytest.raises(StyleTrialProviderError):
        await gateway.generate(
            provider=provider,
            messages=({"role": "user", "content": "bounded"},),
            generation_config={"temperature": 0.7, "maxOutputTokens": 2048},
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_gateway_rejects_short_secret_hidden_outside_safe_content():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "providerLeak": "xabcx",
                "choices": [
                    {"message": {"content": '{"sample":"安全正文"}'}}
                ],
            },
        )

    gateway = StyleTrialProviderGateway(transport=httpx.MockTransport(handler))

    with pytest.raises(StyleTrialProviderError):
        await gateway.generate(
            provider={
                "model_name": "safe-model",
                "base_url": "https://provider.test/v1",
                "api_key": "abc",
            },
            messages=({"role": "user", "content": "bounded"},),
            generation_config={"temperature": 0.7, "maxOutputTokens": 2048},
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_gateway_rejects_redirect_even_when_body_looks_valid():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            json={"choices": [{"message": {"content": '{"sample":"正文"}'}}]},
        )

    gateway = StyleTrialProviderGateway(transport=httpx.MockTransport(handler))
    with pytest.raises(StyleTrialProviderError):
        await gateway.generate(
            provider={
                "model_name": "safe-model",
                "base_url": "https://provider.test/v1",
                "api_key": "unit-test-secret",
            },
            messages=({"role": "user", "content": "bounded"},),
            generation_config={"temperature": 0.7, "maxOutputTokens": 2048},
        )

    assert calls == 1
