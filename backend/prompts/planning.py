"""Closed, bounded prompt construction for Planning generation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain.json_contracts import canonical_json
from backend.domain.planning import DraftPlanningAggregate
from backend.security.provider_secrets import is_provider_secret_key


PLANNING_MAX_PROMPT_BYTES = 96 * 1024
_SAFE_ERROR = "Planning prompt input invalid"
_PRIVATE_TEXT = re.compile(
    r"(?:api[\s_-]*key|base[\s_-]*url|access[\s_-]*token"
    r"|bearer[\s_-]*token|token|password|dsn)\s*[:=]\s*\S+"
    r"|(?:source[\s_.-]*document[\s_.-]*text"
    r"|raw[\s_.-]*source(?:[\s_.-]*(?:text|content|payload))?"
    r"|corpus(?:[\s_.-]*(?:text|content|payload|fragment))?)"
    r"\s*[:=]\s*\S+"
    r"|\bauthorization\s*:\s*[A-Za-z][A-Za-z0-9_-]*\s+\S+"
    r"|\bauthorization\s*:?\s*bearer\s+\S+"
    r"|\bbearer\s+[A-Za-z0-9][A-Za-z0-9._~+/=-]{7,}"
    r"|(?:mysql|postgres(?:ql)?|mariadb)://\S+",
    re.IGNORECASE,
)
_STRICT_MANIFEST = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    hide_input_in_errors=True,
)


class PlanningGenerationBasis(BaseModel):
    model_config = _STRICT_MANIFEST

    project_id: str = Field(alias="projectId", min_length=1)
    basis_hash: str = Field(
        alias="basisHash",
        pattern=r"^[0-9a-f]{64}$",
    )
    draft_revision: int = Field(alias="draftRevision", ge=1)
    draft_hash: str = Field(
        alias="draftHash",
        pattern=r"^[0-9a-f]{64}$",
    )


class PlanningStoryContext(BaseModel):
    model_config = _STRICT_MANIFEST

    premise: str = Field(min_length=1)
    continuity_guardrails: tuple[str, ...] = Field(
        default=(),
        alias="continuityGuardrails",
    )

    @field_validator("continuity_guardrails", mode="before")
    @classmethod
    def accept_json_array(cls, value):
        return tuple(value) if isinstance(value, list) else value


class PlanningGenerationManifest(BaseModel):
    model_config = _STRICT_MANIFEST

    basis: PlanningGenerationBasis
    draft: DraftPlanningAggregate
    story_context: PlanningStoryContext = Field(alias="storyContext")


def _is_private_manifest_key(value: object) -> bool:
    if not isinstance(value, str):
        return True
    normalized = "".join(
        character
        for character in value.casefold()
        if character.isalnum()
    )
    return (
        is_provider_secret_key(value)
        or is_provider_secret_key(normalized)
        or normalized in {"accesstoken", "bearertoken"}
        or "corpus" in normalized
        or "rawsource" in normalized
        or (
            "sourcedocument" in normalized
            and any(
                marker in normalized
                for marker in ("text", "content", "payload")
            )
        )
        or normalized in {
            "rawtext",
            "sourcetext",
            "documenttext",
            "sourcedocument",
            "sourcedocumenttext",
        }
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
        elif isinstance(item, str):
            if _PRIVATE_TEXT.search(item):
                raise ValueError(_SAFE_ERROR)
        elif item is not None and not isinstance(
            item, (int, float, bool)
        ):
            raise ValueError(_SAFE_ERROR)


def build_planning_messages(
    *,
    manifest: PlanningGenerationManifest | Mapping[str, object],
    author_instructions: str,
) -> tuple[dict[str, str], ...]:
    """Build one JSON-only Planning request from a frozen, secret-free manifest."""

    try:
        if not isinstance(author_instructions, str):
            raise ValueError(_SAFE_ERROR)
        author_instructions.encode("utf-8")
        if _PRIVATE_TEXT.search(author_instructions):
            raise ValueError(_SAFE_ERROR)
        manifest_value = PlanningGenerationManifest.model_validate(
            manifest,
            strict=True,
        )
        manifest_snapshot = manifest_value.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        manifest_snapshot["draft"]["activeStoryBlockRef"] = (
            manifest_value.draft.active_story_block_ref
        )
        _validate_safe_manifest(manifest_snapshot)
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


__all__ = (
    "PLANNING_MAX_PROMPT_BYTES",
    "PlanningGenerationBasis",
    "PlanningGenerationManifest",
    "PlanningStoryContext",
    "build_planning_messages",
)
