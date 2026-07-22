from __future__ import annotations

import json

import httpx
import pytest


API_KEY = "PRIVATE_API_KEY_123456789"
BASE_URL = "https://private-provider.example/v1"


def _provider():
    return {
        "model_name": "ranker-model",
        "base_url": BASE_URL,
        "api_key": API_KEY,
    }


def _response(content):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
        },
    )


@pytest.mark.asyncio
async def test_gateway_makes_one_call_and_strictly_parses_unforced_ranking():
    from backend.gateways.asset_recommendation_provider import (
        AssetRecommendationProviderGateway,
    )

    requests = []

    async def handler(request):
        requests.append(request)
        return _response(json.dumps({
            "assetRecommendations": [{
                "assetRevisionId": "style-1",
                "reason": "契合当前叙事距离",
                "confidence": 0.91,
            }],
            "corpusRecommendations": [],
        }, ensure_ascii=False))

    gateway = AssetRecommendationProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    result = await gateway.rank(
        provider=_provider(),
        messages=({"role": "user", "content": "bounded"},),
        generation_config={"temperature": 0.2, "maxOutputTokens": 800},
    )

    assert len(requests) == 1
    assert requests[0].url == BASE_URL + "/chat/completions"
    assert requests[0].headers["authorization"] == f"Bearer {API_KEY}"
    assert tuple(item.asset_revision_id for item in result.asset_recommendations) == (
        "style-1",
    )
    assert result.corpus_recommendations == ()


@pytest.mark.parametrize(
    "content",
    (
        "not-json",
        '{"assetRecommendations":[],"corpusRecommendations":[],"selected":true}',
        '{"assetRecommendations":[{"assetRevisionId":"a","reason":"ok","confidence":0.9},{"assetRevisionId":"a","reason":"again","confidence":0.9}],"corpusRecommendations":[]}',
        '{"assetRecommendations":[],"corpusRecommendations":[],"note":"' + API_KEY + '"}',
    ),
)
@pytest.mark.asyncio
async def test_gateway_invalid_or_secret_output_fails_once_without_repair(content):
    from backend.gateways.asset_recommendation_provider import (
        AssetRecommendationProviderError,
        AssetRecommendationProviderGateway,
    )

    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return _response(content)

    gateway = AssetRecommendationProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AssetRecommendationProviderError):
        await gateway.rank(
            provider=_provider(),
            messages=({"role": "user", "content": "bounded"},),
            generation_config={"temperature": 0.2, "maxOutputTokens": 800},
        )
    assert calls == 1


def test_prompt_is_bounded_allowlisted_and_contains_no_provider_configuration():
    from backend.domain.asset_recommendations import AssetCandidateSummary
    from backend.domain.corpus_recommendations import CorpusCandidate
    from backend.prompts.asset_recommendation import (
        MAX_ASSET_RECOMMENDATION_PROMPT_BYTES,
        build_asset_recommendation_messages,
    )

    style_candidate = AssetCandidateSummary(
        asset_revision_id="style-1",
        asset_type="style",
        stable_key="direct-propulsive",
        revision=1,
        content_hash="d" * 64,
        status="active",
        label="直接推进",
        facts="有界事实",
    )
    messages = build_asset_recommendation_messages(
        selection={
            "selectionRevision": 3,
            "seedRevisionId": "seed-revision-1",
            "seedHash": "a" * 64,
            "seed": {"title": "边城", "logline": "制度在压力中反复修正"},
            "storagePath": "C:/private/seed.json",
        },
        engine={
            "id": "engine-1",
            "hash": "b" * 64,
            "payload": {"name": "边城制度", "storyPromise": "共同守城"},
            "rawProviderOutput": "PRIVATE_RAW",
        },
        selected_styles=(style_candidate,),
        asset_candidates=(style_candidate,),
        corpus_candidates=(CorpusCandidate(
            source_id="source-1",
            source_revision_id="source-revision-1",
            source_revision=2,
            source_hash="e" * 64,
            chapter_id="chapter-1",
            fragment_id="fragment-1",
            fragment_hash="f" * 64,
            window_start=100,
            window_end=104,
            excerpt="边城制度",
        ),),
    )

    rendered = json.dumps(messages, ensure_ascii=False)
    evidence = json.loads(messages[1]["content"])
    assert len(rendered.encode("utf-8")) <= MAX_ASSET_RECOMMENDATION_PROMPT_BYTES
    assert "style-1" in rendered and "fragment-1" in rendered
    assert "scope" not in evidence and "taxonomy" not in evidence
    assert set(evidence) == {
        "selection", "engine", "selectedStyles",
        "assetCandidates", "corpusCandidates",
    }
    assert evidence["selection"]["seed"]["title"] == "边城"
    assert evidence["engine"]["id"] == "engine-1"
    assert evidence["selectedStyles"][0]["assetRevisionId"] == "style-1"
    assert not any(value in rendered for value in (
        API_KEY, BASE_URL, "C:/private/seed.json", "PRIVATE_RAW"
    ))
    assert not any(token in rendered.casefold() for token in (
        "storagepath", "rawprovideroutput", "apikey", "baseurl"
    ))
