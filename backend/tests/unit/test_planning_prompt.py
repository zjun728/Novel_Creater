from __future__ import annotations

import json

import pytest

from backend.domain.planning import DraftPlanningAggregate
from backend.prompts.planning import (
    PLANNING_MAX_PROMPT_BYTES,
    build_planning_messages,
    planning_text_contains_private_material,
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
    rendered_rules = "\n".join(system["rules"])
    assert "clientNodeKey" in rendered_rules
    assert "omit id, revision, and contentHash" in rendered_rules
    assert "return null and [] exactly" in rendered_rules
    assert "Never create a StoryBlock" in rendered_rules
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


@pytest.mark.parametrize(
    "normal_novel_text",
    (
        "门锁协议被角色称作 PK-challenge，不是任何访问凭据。",
        "草稿中的 sk-placeholder 只是尚未命名的技能占位符。",
        "最终门锁状态叫 PK-challenge-mode-final，仍是剧情术语。",
        "角色把绝招暂命名为 sk-placeholder-character-skill。",
        "技能标签 sk-placeholder-character-skill-v2-final 是普通占位名。",
        "编码标签 sk%2Dplaceholder%2Dcharacter%2Dskill%2Dv2%2Dfinal 也不是密钥。",
    ),
)
def test_prompt_allows_normal_novel_text_that_resembles_short_key_prefixes(
    normal_novel_text,
):
    messages = build_planning_messages(
        manifest=_manifest(),
        author_instructions=normal_novel_text,
    )

    assert normal_novel_text in messages[1]["content"]


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("sk-placeholder-character-skill-v2-final", False),
        (
            "sk%2dplaceholder%2dcharacter%2dskill%2dv2%2dfinal",
            False,
        ),
        ("pk%5Fplaceholder%5Fcharacter%5Fskill%5Fv2%5Ffinal", False),
        ("sk-" + ("aB3D" * 7) + "aB3", False),
        (
            "sk-proj-aB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW2xY4zA6bC8dE0fG2hJ4",
            True,
        ),
        (
            "rk%2dlive%2dZ9yX8wV7uT6sR5qP4nM3kJ2hG1fD0cB9aA8",
            True,
        ),
        (
            "pk%5Fprod%5F9Z8Y7X6W5V4U3T2S1R0Q9P8N7M6L5K4J",
            True,
        ),
    ),
)
def test_private_material_token_helper_has_randomness_boundary(
    text,
    expected,
):
    assert planning_text_contains_private_material(text) is expected


@pytest.mark.parametrize("prefix", ("sk", "rk", "pk"))
@pytest.mark.parametrize("separator", ("-", "%2D", "%5F"))
def test_prompt_rejects_high_entropy_letter_only_provider_token_matrix(
    prefix,
    separator,
):
    token = (
        prefix
        + separator
        + "proj"
        + separator
        + "FlkQlhJbcBrpGhaMgrFwuPncZuvZoxTeyOemJwtDvkXdsIaiNqyS"
    )

    assert planning_text_contains_private_material(token) is True
    with pytest.raises(ValueError) as caught:
        build_planning_messages(
            manifest=_manifest(),
            author_instructions=f"沿用凭据 {token}",
        )

    assert str(caught.value) == "Planning prompt input invalid"
    assert token not in str(caught.value)


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
