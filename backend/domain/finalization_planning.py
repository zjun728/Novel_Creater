"""Planning nodes protected by current and previously finalized chapter outlines."""

from collections.abc import Iterable, Mapping
import json

from backend.domain.chapter_outlines import ChapterOutline
from backend.domain.canon import thaw_json
from backend.domain.finalization import PlanningPatch, PlanningTargetType
from backend.domain.planning import (
    DraftPlanningAggregate, PlanningAggregate, PlanningDomainError, normalize_planning_aggregate,
)


def protected_outline_node_ids(outline_values: Iterable[object]) -> frozenset[str]:
    result: set[str] = set()
    for value in outline_values:
        try:
            content = json.loads(value) if isinstance(value, str) else value
            if not isinstance(content, Mapping):
                raise ValueError('invalid outline')
            outline = ChapterOutline.model_validate(dict(content), strict=True)
        except (TypeError, ValueError):
            raise ValueError('chapter outline is invalid') from None
        result.add(outline.volume_ref.id)
        result.add(outline.story_block_ref.id)
        result.update(item.id for item in outline.stage_refs)
        result.update(item.id for item in outline.scene_task_refs)
    return frozenset(result)


def frozen_protected_node_ids(planning_context: Mapping) -> frozenset[str]:
    values = planning_context.get('protectedNodeIds') if isinstance(planning_context, Mapping) else None
    if (
        type(values) is not list
        or any(type(value) is not str or not value or len(value) > 100 for value in values)
        or values != sorted(set(values))
    ):
        raise ValueError('protected planning context is invalid')
    return frozenset(values)


def _editable_payload(value: PlanningAggregate) -> dict[str, object]:
    payload = value.model_dump(mode="json", by_alias=True)
    payload["activeStoryBlockRef"] = payload.pop("activeStoryBlockId")
    payload.pop("schemaVersion")
    payload.pop("contentHash")
    for block in payload["storyBlocks"]:
        block["volumeRef"] = block.pop("volumeId")
        block["plotRefs"] = block.pop("plotIds")
        for stage in block["stages"]:
            stage.pop("storyBlockId")
            for task in stage["sceneTasks"]:
                task.pop("stageId")
    return payload


def _nodes_by_type(payload: dict[str, object]):
    nodes: dict[tuple[PlanningTargetType, str], dict[str, object]] = {}
    for item in payload["volumes"]:
        nodes[(PlanningTargetType.VOLUME, item["id"])] = item
    for item in payload["plots"]:
        nodes[(PlanningTargetType.PLOT, item["id"])] = item
    for block in payload["storyBlocks"]:
        nodes[(PlanningTargetType.STORY_BLOCK, block["id"])] = block
        for stage in block["stages"]:
            nodes[(PlanningTargetType.STAGE, stage["id"])] = stage
            for task in stage["sceneTasks"]:
                nodes[(PlanningTargetType.SCENE_TASK, task["id"])] = task
    return nodes


def apply_planning_patches(
    planning: PlanningAggregate,
    patches: Iterable[PlanningPatch],
    *,
    implemented_ids: frozenset[str],
) -> PlanningAggregate:
    """Apply confirmed, whitelisted patches only to unimplemented nodes."""

    patches = tuple(patches)
    if not patches:
        return planning
    payload = _editable_payload(planning)
    nodes = _nodes_by_type(payload)
    for patch in patches:
        if patch.target_id in implemented_ids:
            raise ValueError(
                "planning patch targets an implemented node"
            )
        node = nodes.get((patch.target_type, patch.target_id))
        if node is None:
            raise ValueError("planning patch target is missing")
        if (
            node["revision"] != patch.expected_revision
            or node["contentHash"] != patch.expected_hash
        ):
            raise ValueError("planning patch target is stale")
        node[patch.field_path] = thaw_json(patch.replacement)

    try:
        draft = DraftPlanningAggregate.model_validate(payload, strict=True)
        return normalize_planning_aggregate(
            draft,
            previous_confirmed=planning,
            previous_draft=None,
            id_factory=lambda: _unexpected_id_allocation(),
        )
    except PlanningDomainError as exc:
        raise ValueError("planning patch is invalid") from exc


def _unexpected_id_allocation() -> str:
    raise ValueError("planning patch cannot create nodes")
