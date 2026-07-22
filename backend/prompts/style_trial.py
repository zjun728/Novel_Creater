"""Bounded style-trial prompt from frozen, author-selected inputs."""

from __future__ import annotations

import json

from backend.domain.assets import StylePromptPayload
from backend.domain.json_contracts import canonical_json
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption


STYLE_TRIAL_MAX_PROMPT_BYTES = 96 * 1024


def build_style_trial_messages(
    *,
    seed: SeedPayload,
    engine: StoryEngineOption,
    primary_style: StylePromptPayload,
    secondary_style: StylePromptPayload | None,
    author_scenario: str,
) -> tuple[dict[str, str], ...]:
    """Build one JSON-only request without Provider or corpus configuration."""

    instruction = {
        "task": "Write one original style-trial scene for the supplied scenario.",
        "rules": [
            "Tell a concrete story rather than explaining the writing rules.",
            "Keep plot, character voices, dialogue, emotion, and action alive.",
            "Use the primary style as the base and secondary style only as flavor.",
            "Return strict JSON with exactly one key: sample.",
            "The sample must be original Chinese fiction of about 800-1200 characters.",
            "Do not add a title, critique, score, selection, contract, or factual-authority claim.",
        ],
    }
    evidence = {
        "seed": seed.model_dump(mode="json"),
        "storyEngine": engine.model_dump(mode="json"),
        "primaryStyle": primary_style.model_dump(mode="json"),
        "secondaryStyle": (
            secondary_style.model_dump(mode="json")
            if secondary_style is not None
            else None
        ),
        "authorScenario": author_scenario,
        "outputSchema": {"sample": "原创正文"},
    }
    messages = (
        {"role": "system", "content": canonical_json(instruction)},
        {"role": "user", "content": canonical_json(evidence)},
    )
    rendered = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if len(rendered.encode("utf-8")) > STYLE_TRIAL_MAX_PROMPT_BYTES:
        raise ValueError("style trial prompt exceeds bounded size")
    return messages


__all__ = ("STYLE_TRIAL_MAX_PROMPT_BYTES", "build_style_trial_messages")
