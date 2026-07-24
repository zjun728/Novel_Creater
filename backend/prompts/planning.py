"""Closed, bounded prompt construction for Planning generation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re

from backend.domain.json_contracts import canonical_json
from backend.domain.planning import DraftPlanningAggregate


PLANNING_MAX_PROMPT_BYTES = 96 * 1024
_SAFE_ERROR = "Planning prompt input invalid"
_PRIVATE_INSTRUCTION = re.compile(
    r"(?:api[\s_-]*key|authorization|password|dsn)\s*[:=]"
    r"|(?:mysql|postgres(?:ql)?|mariadb)://",
    re.IGNORECASE,
)


def _is_private_manifest_key(value: object) -> bool:
    if not isinstance(value, str):
        return True
    normalized = "".join(
        character
        for character in value.casefold()
        if character.isalnum()
    )
    return (
        normalized in {"apikey", "authorization", "password", "dsn"}
        or "corpus" in normalized
        or normalized in {"rawtext", "sourcetext", "documenttext"}
    )


def _validate_safe_manifest(value: Mapping[str, object]) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 10_000 or depth > 32:
            raise ValueError(_SAFE_ERROR)
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if _is_private_manifest_key(key):
                    raise ValueError(_SAFE_ERROR)
                pending.append((nested, depth + 1))
        elif isinstance(item, (list, tuple)):
            pending.extend((nested, depth + 1) for nested in item)
        elif item is not None and not isinstance(
            item, (str, int, float, bool)
        ):
            raise ValueError(_SAFE_ERROR)


def build_planning_messages(
    *,
    manifest: Mapping[str, object],
    author_instructions: str,
) -> tuple[dict[str, str], ...]:
    """Build one JSON-only Planning request from a frozen, secret-free manifest."""

    try:
        if not isinstance(manifest, Mapping):
            raise ValueError(_SAFE_ERROR)
        if not isinstance(author_instructions, str):
            raise ValueError(_SAFE_ERROR)
        author_instructions.encode("utf-8")
        if _PRIVATE_INSTRUCTION.search(author_instructions):
            raise ValueError(_SAFE_ERROR)
        _validate_safe_manifest(manifest)
        manifest_snapshot = json.loads(
            json.dumps(
                dict(manifest),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        instruction = {
            "task": "Generate one complete Planning draft",
            "editableScope": ["volumes", "plots"],
            "preserveScope": [
                "activeStoryBlockRef",
                "storyBlocks",
                "storyBlocks[].stages",
                "storyBlocks[].stages[].sceneTasks",
            ],
            "rules": [
                "Return exactly one JSON object matching outputContract.",
                "Create or revise Volume narrative direction and continuing "
                "Plot lines.",
                "Copy supplied StoryBlock, Stage, and SceneTask identities, "
                "order, references, and content unchanged.",
                "Do not add, remove, summarize, or rewrite supplied preserved content.",
                "Keep every relation inside the returned Planning draft.",
                "Do not return commentary, markdown, prompt text, or evidence.",
            ],
        }
        evidence = {
            "manifest": manifest_snapshot,
            "authorInstructions": author_instructions,
            "outputContract": DraftPlanningAggregate.model_json_schema(
                by_alias=True
            ),
        }
        messages = (
            {"role": "system", "content": canonical_json(instruction)},
            {"role": "user", "content": canonical_json(evidence)},
        )
        rendered = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(rendered) > PLANNING_MAX_PROMPT_BYTES:
            raise ValueError(_SAFE_ERROR)
        return messages
    except (
        UnicodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        raise ValueError(_SAFE_ERROR) from None


__all__ = ("PLANNING_MAX_PROMPT_BYTES", "build_planning_messages")
