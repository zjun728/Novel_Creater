"""Minimal prompt contract for story-engine generation."""

from __future__ import annotations

import json
from collections.abc import Mapping

from backend.domain.story_engines import StoryEngineOption


_SYSTEM_MESSAGE = "故事具体、人物有欲望和代价、冲突能够长期变化。"


def build_story_engine_messages(
    seed_snapshot: Mapping[str, object],
    channel_profile: Mapping[str, object],
    genre_profile: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build messages exclusively from the three frozen generation inputs."""

    user_payload = {
        "seedSnapshot": dict(seed_snapshot),
        "channelProfile": dict(channel_profile),
        "genreProfile": dict(genre_profile),
        "outputContract": {
            "type": "object",
            "onlyField": "options",
            "options": {
                "type": "array",
                "exactItems": 3,
                "item": {
                    "type": "object",
                    "fields": list(StoryEngineOption.model_fields),
                    "additionalFields": False,
                },
            },
        },
    }
    return (
        {"role": "system", "content": _SYSTEM_MESSAGE},
        {
            "role": "user",
            "content": json.dumps(
                user_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )
