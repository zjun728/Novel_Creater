from __future__ import annotations

import json

import pytest

from backend.domain.planning import DraftPlanningAggregate
from backend.prompts.planning import (
    PLANNING_MAX_PROMPT_BYTES,
    build_planning_messages,
)


def _existing_story_block() -> dict[str, object]:
    return {
        "clientNodeKey": "block-existing",
        "lifecycle": "active",
        "order": 1,
        "title": "旧城封锁",
        "volumeRef": "volume-existing",
        "plotRefs": ["plot-existing"],
        "entrySituation": "城门已经封闭。",
        "blockGoal": "让同伴安全出城。",
        "mainPressure": "追兵逐步缩小包围圈。",
        "expectedChange": "主角开始信任同伴。",
        "openQuestions": ["谁泄露了路线？"],
        "involvedCharacters": ["沈砚", "陆微"],
        "stages": [
            {
                "clientNodeKey": "stage-existing",
                "lifecycle": "active",
                "order": 1,
                "title": "寻找缺口",
                "purpose": "迫使两人共享秘密。",
                "dramaticQuestion": "他们能否赶在封锁完成前找到出口？",
                "sceneTasks": [
                    {
                        "clientNodeKey": "task-existing",
                        "lifecycle": "active",
                        "order": 1,
                        "task": "确认守卫换班规律。",
                        "completionEvidence": "拿到一条可验证的换班记录。",
                    }
                ],
            }
        ],
    }


def _manifest() -> dict[str, object]:
    return {
        "basis": {
            "projectId": "project-1",
            "basisHash": "a" * 64,
            "draftRevision": 7,
            "draftHash": "b" * 64,
        },
        "draft": {
            "activeStoryBlockRef": "block-existing",
            "volumes": [
                {
                    "clientNodeKey": "volume-existing",
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
                    "clientNodeKey": "plot-existing",
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
            "storyBlocks": [_existing_story_block()],
        },
        "storyContext": {
            "premise": "知识带来解决办法，也带来新的关系债。",
            "continuityGuardrails": ["不得提前揭示内应身份"],
        },
    }


def test_prompt_requests_exact_closed_draft_shape_and_preserves_frozen_structure():
    messages = build_planning_messages(
        manifest=_manifest(),
        author_instructions="扩展为三卷，并让两条长期线逐步交叉。",
    )

    assert tuple(message["role"] for message in messages) == ("system", "user")
    system = json.loads(messages[0]["content"])
    user = json.loads(messages[1]["content"])
    assert system["task"] == "Generate one complete Planning draft"
    assert system["editableScope"] == ["volumes", "plots"]
    assert system["preserveScope"] == [
        "activeStoryBlockRef",
        "storyBlocks",
        "storyBlocks[].stages",
        "storyBlocks[].stages[].sceneTasks",
    ]
    assert user == {
        "manifest": _manifest(),
        "authorInstructions": "扩展为三卷，并让两条长期线逐步交叉。",
        "outputContract": DraftPlanningAggregate.model_json_schema(
            by_alias=True
        ),
    }
    contract = user["outputContract"]
    assert contract["additionalProperties"] is False
    assert contract["required"] == [
        "activeStoryBlockRef",
        "volumes",
        "plots",
        "storyBlocks",
    ]
    for definition in contract["$defs"].values():
        assert definition["additionalProperties"] is False
    assert (
        user["manifest"]["draft"]["storyBlocks"][0]
        == _existing_story_block()
    )
    assert len(
        json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ) <= PLANNING_MAX_PROMPT_BYTES


@pytest.mark.parametrize(
    ("manifest", "instructions"),
    (
        ({"apiKey": "PRIVATE_API_KEY_SENTINEL"}, "安全要求"),
        ({"api key": "PRIVATE_SPACED_API_KEY_SENTINEL"}, "安全要求"),
        ({"api   key": "PRIVATE_WIDE_API_KEY_SENTINEL"}, "安全要求"),
        ({"Authorization": "Bearer PRIVATE_AUTH_SENTINEL"}, "安全要求"),
        ({"database": {"password": "PRIVATE_PASSWORD_SENTINEL"}}, "安全要求"),
        ({"dsn": "mysql://PRIVATE_DSN_SENTINEL"}, "安全要求"),
        (
            {"runtime": {"baseURL": "PRIVATE_BASE_URL_SENTINEL"}},
            "安全要求",
        ),
        (
            {"runtime": {"base_url": "PRIVATE_BASE_URL_SNAKE_SENTINEL"}},
            "安全要求",
        ),
        (
            {"runtime": {"base url": "PRIVATE_SPACED_BASE_URL_SENTINEL"}},
            "安全要求",
        ),
        ({"credentials": {"token": "PRIVATE_TOKEN_SENTINEL"}}, "安全要求"),
        (
            {"credentials": {"accessToken": "PRIVATE_ACCESS_TOKEN_SENTINEL"}},
            "安全要求",
        ),
        (
            {
                "credentials": {
                    "bearer_token": "PRIVATE_BEARER_TOKEN_SENTINEL"
                }
            },
            "安全要求",
        ),
        (
            {
                "corpusFragments": [
                    {"text": "PRIVATE_RAW_CORPUS_SENTINEL"}
                ]
            },
            "安全要求",
        ),
        (
            {
                "sources": {
                    "sourceDocumentText": "PRIVATE_SOURCE_TEXT_SENTINEL"
                }
            },
            "安全要求",
        ),
        (
            {
                "sources": {
                    "source_document_text": (
                        "PRIVATE_SOURCE_TEXT_SNAKE_SENTINEL"
                    )
                }
            },
            "安全要求",
        ),
        (
            {
                "notes": (
                    "Authorization: Bearer "
                    "PRIVATE_MANIFEST_BEARER_SENTINEL"
                )
            },
            "安全要求",
        ),
        (
            {
                "notes": (
                    "Authorization :  Basic "
                    "PRIVATE_MANIFEST_BASIC_SENTINEL"
                )
            },
            "安全要求",
        ),
        (
            {
                "notes": (
                    "sourceDocumentText="
                    "PRIVATE_EMBEDDED_SOURCE_TEXT_SENTINEL"
                )
            },
            "安全要求",
        ),
        (_manifest(), "password=PRIVATE_INSTRUCTION_SENTINEL"),
        (
            _manifest(),
            "Authorization Bearer PRIVATE_INSTRUCTION_BEARER_SENTINEL",
        ),
        (
            _manifest(),
            "Authorization: Basic PRIVATE_INSTRUCTION_BASIC_SENTINEL",
        ),
        (
            _manifest(),
            "bearer token=PRIVATE_INSTRUCTION_TOKEN_SENTINEL",
        ),
        (
            _manifest(),
            "Bearer PRIVATE_STANDALONE_BEARER_SENTINEL",
        ),
    ),
)
def test_prompt_rejects_private_or_raw_material_with_one_safe_error(
    manifest, instructions, caplog
):
    with pytest.raises(ValueError) as caught:
        build_planning_messages(
            manifest=manifest,
            author_instructions=instructions,
        )

    assert str(caught.value) == "Planning prompt input invalid"
    rendered = repr(caught.value) + caplog.text
    assert all(
        marker not in rendered
        for marker in (
            "PRIVATE_API_KEY_SENTINEL",
            "PRIVATE_SPACED_API_KEY_SENTINEL",
            "PRIVATE_WIDE_API_KEY_SENTINEL",
            "PRIVATE_AUTH_SENTINEL",
            "PRIVATE_PASSWORD_SENTINEL",
            "PRIVATE_DSN_SENTINEL",
            "PRIVATE_RAW_CORPUS_SENTINEL",
            "PRIVATE_INSTRUCTION_SENTINEL",
            "PRIVATE_BASE_URL_SENTINEL",
            "PRIVATE_BASE_URL_SNAKE_SENTINEL",
            "PRIVATE_SPACED_BASE_URL_SENTINEL",
            "PRIVATE_TOKEN_SENTINEL",
            "PRIVATE_ACCESS_TOKEN_SENTINEL",
            "PRIVATE_BEARER_TOKEN_SENTINEL",
            "PRIVATE_SOURCE_TEXT_SENTINEL",
            "PRIVATE_SOURCE_TEXT_SNAKE_SENTINEL",
            "PRIVATE_MANIFEST_BEARER_SENTINEL",
            "PRIVATE_MANIFEST_BASIC_SENTINEL",
            "PRIVATE_EMBEDDED_SOURCE_TEXT_SENTINEL",
            "PRIVATE_INSTRUCTION_BEARER_SENTINEL",
            "PRIVATE_INSTRUCTION_BASIC_SENTINEL",
            "PRIVATE_INSTRUCTION_TOKEN_SENTINEL",
            "PRIVATE_STANDALONE_BEARER_SENTINEL",
        )
    )


def test_prompt_rejects_oversized_manifest_without_echo():
    manifest = _manifest()
    manifest["storyContext"]["premise"] = (
        "私" * PLANNING_MAX_PROMPT_BYTES
    )
    with pytest.raises(ValueError) as caught:
        build_planning_messages(
            manifest=manifest,
            author_instructions="扩展长期线。",
        )

    assert str(caught.value) == "Planning prompt input invalid"
    assert "私" not in str(caught.value)


@pytest.mark.parametrize(
    "case",
    (
        "non_mapping",
        "draft_list",
        "missing_draft",
        "extra_top",
        "extra_basis",
        "extra_story_context",
    ),
)
def test_prompt_requires_one_closed_strict_manifest(case, caplog):
    manifest = _manifest()
    if case == "non_mapping":
        manifest = []
    elif case == "draft_list":
        manifest["draft"] = []
    elif case == "missing_draft":
        manifest.pop("draft")
    elif case == "extra_top":
        manifest["unknown"] = "UNKNOWN_MANIFEST_SENTINEL"
    elif case == "extra_basis":
        manifest["basis"]["unknown"] = "UNKNOWN_MANIFEST_SENTINEL"
    else:
        manifest["storyContext"]["unknown"] = "UNKNOWN_MANIFEST_SENTINEL"

    with pytest.raises(ValueError) as caught:
        build_planning_messages(
            manifest=manifest,
            author_instructions="扩展长期线。",
        )

    assert str(caught.value) == "Planning prompt input invalid"
    exposed = repr(caught.value) + caplog.text
    assert "UNKNOWN_MANIFEST_SENTINEL" not in exposed
