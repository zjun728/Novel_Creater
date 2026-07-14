from __future__ import annotations

import json
from pathlib import Path

from backend.domain.story_engines import StoryEngineOption
from backend.prompts.story_engine import build_story_engine_messages


def _seed_snapshot():
    return {
        "title": "冻结标题",
        "genre": "冻结类型",
        "logline": "冻结梗概",
        "protagonist": "冻结主角",
        "desire": "冻结欲望",
        "coreConflict": "冻结冲突",
        "worldPressure": "冻结压力",
        "openingHook": "冻结钩子",
        "differentiation": "冻结差异",
    }


def test_prompt_contains_only_frozen_inputs_and_exact_output_contract():
    seed = _seed_snapshot()
    channel = {"format": "long-form-serial", "targetWords": 900_000}
    genre = {"genre": "eastern-fantasy", "readerPromise": "升级与抉择"}

    messages = build_story_engine_messages(seed, channel, genre)

    assert messages[0] == {
        "role": "system",
        "content": "故事具体、人物有欲望和代价、冲突能够长期变化。",
    }
    assert messages[1]["role"] == "user"
    user = json.loads(messages[1]["content"])
    assert set(user) == {
        "seedSnapshot",
        "channelProfile",
        "genreProfile",
        "outputContract",
    }
    assert user["seedSnapshot"] == seed
    assert user["channelProfile"] == channel
    assert user["genreProfile"] == genre
    contract = user["outputContract"]
    assert contract["type"] == "object"
    assert contract["required"] == ["options"]
    assert contract["additionalProperties"] is False
    options_schema = contract["properties"]["options"]
    assert options_schema["type"] == "array"
    assert options_schema["minItems"] == options_schema["maxItems"] == 3
    item_schema = options_schema["items"]
    assert item_schema["type"] == "object"
    assert item_schema["required"] == list(StoryEngineOption.model_fields)
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["properties"]) == set(StoryEngineOption.model_fields)
    assert item_schema["properties"]["name"]["type"] == "string"
    assert item_schema["properties"]["satisfactionSources"]["type"] == "array"
    assert item_schema["properties"]["longFormVariation"]["type"] == "array"
    assert item_schema["properties"]["risks"]["type"] == "array"
    role_ref = item_schema["properties"]["ensembleRoles"]["items"]["$ref"]
    assert role_ref == "#/$defs/EnsembleRole"
    role_schema = contract["$defs"]["EnsembleRole"]
    assert role_schema["type"] == "object"
    assert role_schema["required"] == ["role", "purpose"]
    assert role_schema["additionalProperties"] is False
    assert set(role_schema["properties"]) == {"role", "purpose"}


def test_prompt_does_not_import_or_embed_forbidden_prompt_material():
    module_path = Path(__file__).parents[2] / "prompts" / "story_engine.py"
    source = module_path.read_text(encoding="utf-8")
    lowered = source.lower()
    forbidden = (
        "frontend",
        "style examples",
        "quality rubric",
        "anti-ai",
        "api_key",
        "base_url",
        "provider configuration",
        "corpus",
    )
    assert all(item not in lowered for item in forbidden)
