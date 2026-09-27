"""Closed output contract for opt-in full planning and continuation."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

from backend.domain.planning import DraftPlanningAggregate, DraftVolume, DraftStoryBlock

GenerationMode = Literal["volumes_plots", "initial", "next_block", "next_volume", "revise_block", "fill_next_block", "fill_next_volume"]


class PlanningBlockAdjustmentOutput(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    story_block: DraftStoryBlock = Field(alias="storyBlock")


def merge_block_adjustment(before, value, expansion):
    block = PlanningBlockAdjustmentOutput.model_validate(value, strict=True).story_block
    result = before.model_copy(update={"story_blocks": tuple(
        block if node_ref(old) == expansion.target_block_ref else old for old in before.story_blocks
    )})
    validate_expansion_output(before, result, expansion)
    return result


class PlanningContinuationOutput(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    next_volume: DraftVolume | None = Field(alias="nextVolume")
    next_story_block: DraftStoryBlock | None = Field(alias="nextStoryBlock")


def merge_completion(before, value, expansion):
    from backend.domain.planning_completion import merge_missing_node, missing_block_fields, missing_volume_fields
    volume = next(v for v in before.volumes if node_ref(v) == expansion.target_volume_ref)
    block = next((b for b in before.story_blocks if node_ref(b) == expansion.target_block_ref), None)
    # Missing-field patches are merged onto fixed authoritative targets. Filled
    # fields and identities, if supplied, must still match exactly.
    from copy import deepcopy
    from backend.domain.planning_completion import apply_completion_patch
    value = deepcopy(value)
    if isinstance(value, dict):
        if isinstance(value.get('nextVolume'),dict): value['nextVolume']=apply_completion_patch(volume,value['nextVolume'])
        if block and isinstance(value.get('nextStoryBlock'),dict): value['nextStoryBlock']=apply_completion_patch(block,value['nextStoryBlock'])
    delta = PlanningContinuationOutput.model_validate(value, strict=True)
    fill_volume = expansion.mode == 'fill_next_volume' and bool(missing_volume_fields(volume))
    fill_block = block is None or bool(missing_block_fields(block))
    if (delta.next_volume is not None) != fill_volume or (delta.next_story_block is not None) != fill_block:
        raise ValueError('return only nodes that require completion')
    if delta.next_volume is not None: merge_missing_node(volume, delta.next_volume)
    if block is not None and delta.next_story_block is not None: merge_missing_node(block, delta.next_story_block)
    result = before.model_copy(update={
        'volumes': tuple(delta.next_volume if fill_volume and node_ref(v) == node_ref(volume) else v for v in before.volumes),
        'story_blocks': tuple(delta.next_story_block if block and fill_block and node_ref(b) == node_ref(block) else b for b in before.story_blocks)
                        + ((delta.next_story_block,) if block is None else ()),
        'active_story_block_ref': node_ref(block) if block else node_ref(delta.next_story_block),
    })
    validate_expansion_output(before, result, expansion)
    return result


def merge_continuation(before, value, expansion):
    delta = PlanningContinuationOutput.model_validate(value, strict=True)
    if (delta.next_volume is None) != (expansion.target_volume_ref is not None):
        raise ValueError("generate a volume only when no target volume exists")
    if (delta.next_story_block is None) != (expansion.target_block_ref is not None):
        raise ValueError("generate a block only when no target block exists")
    result = before.model_copy(update={
        "volumes": before.volumes + ((delta.next_volume,) if delta.next_volume else ()),
        "story_blocks": before.story_blocks + ((delta.next_story_block,) if delta.next_story_block else ()),
        "active_story_block_ref": expansion.target_block_ref or node_ref(delta.next_story_block),
    })
    validate_expansion_output(before, result, expansion)
    return result


class PlanningExpansion(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    mode: Literal["initial", "next_block", "next_volume", "revise_block", "fill_next_block", "fill_next_volume"]
    authority_hash: str = Field(alias="authorityHash", pattern=r"^[0-9a-f]{64}$")
    target_volume_ref: str | None = Field(default=None, alias="targetVolumeRef")
    target_block_ref: str | None = Field(default=None, alias="targetBlockRef")
    # Values are built and validated from authoritative rows by the service.
    continuity: dict
    protected_node_refs: tuple[str, ...] = Field(default=(), alias="protectedNodeRefs")

    @field_validator("protected_node_refs", mode="before")
    @classmethod
    def accept_json_refs(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @model_serializer(mode="wrap")
    def omit_empty_protection(self, handler):
        result = handler(self)
        if not self.protected_node_refs:
            result.pop("protectedNodeRefs", None)
            result.pop("protected_node_refs", None)
        return result


def node_ref(node):
    return node.id or node.client_key


def validate_expansion_output(before: DraftPlanningAggregate, after: DraftPlanningAggregate,
                              expansion: PlanningExpansion | None):
    if expansion is None:
        if (before.active_story_block_ref != after.active_story_block_ref
                or before.story_blocks != after.story_blocks):
            raise ValueError("preserved planning changed")
        return
    active = next((b for b in after.story_blocks if node_ref(b) == after.active_story_block_ref), None)
    if active is None or active.lifecycle != "active" or not active.stages:
        raise ValueError("generated planning requires an active complete story block")
    if expansion.mode.startswith('fill_'):
        from backend.domain.planning_completion import merge_missing_node, missing_block_fields, missing_volume_fields
        volume = next(v for v in after.volumes if node_ref(v) == expansion.target_volume_ref)
        if (after.plots != before.plots or len(after.volumes) != len(before.volumes)
                or active.volume_ref != expansion.target_volume_ref
                or missing_block_fields(active)
                or (expansion.mode == 'fill_next_volume' and missing_volume_fields(volume))):
            raise ValueError('completed planning must be complete and preserve unrelated plans')
        for old, new in zip(before.volumes, after.volumes):
            if expansion.mode == 'fill_next_volume' and node_ref(old) == expansion.target_volume_ref:
                merge_missing_node(old, new)
            elif old != new: raise ValueError('unrelated volumes must remain unchanged')
        expected_count = len(before.story_blocks) + (expansion.target_block_ref is None)
        if len(after.story_blocks) != expected_count: raise ValueError('unexpected completed blocks')
        for old, new in zip(before.story_blocks, after.story_blocks):
            if node_ref(old) == expansion.target_block_ref:
                merge_missing_node(old, new)
                if node_ref(active) != node_ref(old): raise ValueError('select the completed target')
                def nodes(b): return [b, *[n for s in b.stages for n in (s, *s.scene_tasks)]]
                new_nodes = {node_ref(n): n for n in nodes(new)}
                if any(new_nodes.get(node_ref(n)) != n for n in nodes(old) if node_ref(n) in expansion.protected_node_refs):
                    raise ValueError('implemented content cannot be completed or rewritten')
            elif old != new: raise ValueError('unrelated blocks must remain unchanged')
        if expansion.target_block_ref is None and (active != after.story_blocks[-1] or active.id is not None
                or active.order <= max((b.order for b in before.story_blocks), default=0)):
            raise ValueError('append exactly one new block to the existing volume')
        return
    if expansion.mode == "revise_block":
        original = next(b for b in before.story_blocks if node_ref(b) == expansion.target_block_ref)
        if (after.volumes != before.volumes or after.plots != before.plots
                or after.active_story_block_ref != before.active_story_block_ref
                or len(after.story_blocks) != len(before.story_blocks)
                or node_ref(active) != node_ref(original) or active.volume_ref != original.volume_ref
                or active.order != original.order):
            raise ValueError("adjust only the selected current block")
        for old, new in zip(before.story_blocks, after.story_blocks):
            if node_ref(old) != expansion.target_block_ref and old != new:
                raise ValueError("other blocks must remain unchanged")
        def children(block):
            return {node_ref(n): n for stage in block.stages for n in (stage, *stage.scene_tasks)}
        old_children, new_children = children(original), children(active)
        for reference in expansion.protected_node_refs:
            if old_children.get(reference) is None or old_children[reference] != new_children.get(reference):
                raise ValueError("implemented planning nodes cannot be rewritten")
        return
    if any(s.lifecycle != "active" or not s.scene_tasks for s in active.stages):
        raise ValueError("every generated stage requires scene tasks")
    if expansion.mode == "initial":
        if before.story_blocks or len(after.story_blocks) != 1:
            raise ValueError("initial generation requires exactly the first story block")
        first_volume = min((v for v in after.volumes if v.lifecycle == "active"), key=lambda v: v.order)
        if active.volume_ref != node_ref(first_volume):
            raise ValueError("initial story block must belong to first volume")
        return
    if after.plots != before.plots or after.story_blocks[:len(before.story_blocks)] != before.story_blocks:
        raise ValueError("continuation must preserve all prior blocks and plot lines")
    if after.volumes[:len(before.volumes)] != before.volumes:
        raise ValueError("continuation must preserve all prior volumes")
    if expansion.target_volume_ref is not None:
        if after.volumes != before.volumes or active.volume_ref != expansion.target_volume_ref:
            raise ValueError("continuation must use selected volume")
    else:
        if expansion.mode != "next_volume" or len(after.volumes) != len(before.volumes) + 1:
            raise ValueError("continuation must append one volume")
        volume = after.volumes[-1]
        if (volume.id is not None or volume.lifecycle != "active"
                or volume.order <= max(v.order for v in before.volumes)
                or active.volume_ref != node_ref(volume)):
            raise ValueError("next volume identity or order invalid")
    if expansion.target_block_ref is not None:
        if after.story_blocks != before.story_blocks or node_ref(active) != expansion.target_block_ref:
            raise ValueError("reuse the already planned next block")
    elif (len(after.story_blocks) != len(before.story_blocks) + 1
          or active != after.story_blocks[-1] or active.id is not None
          or active.order <= max(b.order for b in before.story_blocks)):
        raise ValueError("continuation must append one new active story block")
