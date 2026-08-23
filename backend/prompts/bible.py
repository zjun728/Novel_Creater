"""One bounded prompt for a complete future-design creation Bible."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from backend.domain.json_contracts import canonical_json


BIBLE_MAX_PROMPT_BYTES = 96 * 1024
_REQUIRED_FIELDS = (
    "premiseAndPromise",
    "worldRules",
    "powerOrProgressionSystem",
    "protagonist",
    "coreCast",
    "factions",
    "longTermConflicts",
    "relationshipDynamics",
    "toneAndNarrativeBoundaries",
    "continuityGuardrails",
    "openDesignQuestions",
)
_SCALAR_FIELDS = (
    "premiseAndPromise",
    "powerOrProgressionSystem",
    "protagonist",
    "toneAndNarrativeBoundaries",
)
_LIST_FIELDS = tuple(
    field for field in _REQUIRED_FIELDS if field not in _SCALAR_FIELDS
)


def build_bible_messages(
    *,
    seed: Mapping[str, object],
    creation_contract: Mapping[str, object],
    style_contract: Mapping[str, object],
    experience_cards: Sequence[Mapping[str, object]],
    corpus_fragments: Sequence[Mapping[str, object]],
    author_instructions: str,
) -> tuple[dict[str, str], ...]:
    """Build exactly one JSON-only request and fail closed on its byte budget."""

    instruction = {
        "task": "Generate one complete creation Bible",
        "purpose": "为长篇小说设计可持续展开的未来设计，不是既成事实记录。",
        "rules": [
            "综合已确认种子、创作契约、风格契约、选定经验卡、语料片段与作者补充要求。",
            "设计世界规则、人物欲望、群像分工、势力、长期冲突、关系动力与连续性护栏。",
            "所有内容都是未来设计；不得虚构已经发生的事件，也不得把设计写入 Canon。",
            "保留可供后续创作选择的开放问题，不要预写章节、场景或结局事实。",
            "返回严格 JSON 对象，字段必须且只能符合 outputSchema。",
            "列表项使用稳定、简短、互不重复的 ASCII id，并提供具体中文 text。",
            "直接输出 JSON，不要解释、复述输入或展示思考过程。",
            "内容精炼但可执行：每个列表 3 至 6 项，每项 text 40 至 160 个汉字。",
            "每个标量字段 120 至 300 个汉字，整个 JSON 不超过 5000 个汉字。",
        ],
    }
    evidence = {
        "confirmedSeed": dict(seed),
        "creationContract": dict(creation_contract),
        "styleContract": dict(style_contract),
        "experienceCards": [dict(value) for value in experience_cards],
        "corpusFragments": [dict(value) for value in corpus_fragments],
        "authorInstructions": author_instructions,
        "outputSchema": {
            "type": "object",
            "required": list(_REQUIRED_FIELDS),
            "additionalProperties": False,
            "properties": {
                **{
                    field: {
                        "type": "string",
                        "minLength": 120,
                        "maxLength": 300,
                    }
                    for field in _SCALAR_FIELDS
                },
                **{
                    field: {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "required": ["id", "text"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]*$",
                                    "maxLength": 64,
                                },
                                "text": {
                                    "type": "string",
                                    "minLength": 40,
                                    "maxLength": 160,
                                },
                            },
                        },
                    }
                    for field in _LIST_FIELDS
                },
            },
        },
    }
    messages = (
        {"role": "system", "content": canonical_json(instruction)},
        {"role": "user", "content": canonical_json(evidence)},
    )
    rendered = json.dumps(
        messages,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(rendered) > BIBLE_MAX_PROMPT_BYTES:
        raise ValueError("Bible prompt exceeds bounded size")
    return messages


__all__ = ("BIBLE_MAX_PROMPT_BYTES", "build_bible_messages")
