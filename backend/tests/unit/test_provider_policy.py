from __future__ import annotations

import importlib

import pytest

from backend.serializers.provider import provider_public_profile
from backend.services.model_bindings import provider_is_available
from backend.services.story_engines import StoryEngineService


def provider_row(**changes):
    row = {
        "id": "provider-1",
        "name": "Provider One",
        "provider_type": "openai-compatible",
        "model_name": "model-one",
        "base_url": "x",
        "api_key": "short",
        "enabled": 1,
        "sort_order": 1,
        "stream": 1,
        "max_context_tokens": 8_192,
        "max_output_tokens": 1_024,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": "",
        "thinking": None,
        "lifecycle_status": "active",
        "revision": 1,
        "deleted_at": None,
        "created_at": 1,
        "updated_at": 1,
    }
    row.update(changes)
    return row


def test_canonical_policy_module_defines_one_generation_type():
    try:
        policy = importlib.import_module("backend.domain.provider_policy")
    except ModuleNotFoundError:
        pytest.fail("canonical Provider policy module is missing")

    assert policy.GENERATION_PROVIDER_TYPE == "openai-compatible"
    assert policy.SUPPORTED_PROVIDER_TYPES == frozenset(
        {"openai-compatible"}
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({}, True),
        ({"api_key": " "}, False),
        ({"base_url": " "}, False),
        ({"model_name": " "}, False),
        ({"provider_type": "openai"}, False),
        ({"enabled": 0}, False),
        ({"lifecycle_status": "deleted"}, False),
    ),
)
def test_public_binding_and_story_callability_agree(changes, expected):
    row = provider_row(**changes)

    public_ready = provider_public_profile(row).ready
    binding_ready = provider_is_available(row)
    story_ready = StoryEngineService._provider_is_callable(
        row,
        row["model_name"],
        {"temperature": 0.8, "maxOutputTokens": 1_024},
    )

    assert public_ready is expected
    assert binding_ready is expected
    assert story_ready is expected
