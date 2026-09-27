"""Build continuation only from synchronized, completed authoritative progress."""
from backend.domain.json_contracts import canonical_hash
from backend.domain.planning_expansion import PlanningExpansion, node_ref
from backend.prompts.chapter_outline import PreviousFinalChapter
from backend.services.planning_progress import actual_block_progress, planning_progress_reason
from backend.domain.planning import PlanningAggregate


def expansion_authority_hash(authority):
    return canonical_hash(authority)


def validate_manual_continuation(before, after, authority):
    """Manual selection cannot bypass continuation guards at confirmation."""
    from backend.services.planning_generation import PlanningGenerationService
    from backend.domain.planning_completion import missing_block_fields, missing_volume_fields
    draft = PlanningGenerationService._editable_draft(before)
    result = PlanningGenerationService._editable_draft(after)
    active = next(b for b in draft.story_blocks if node_ref(b) == draft.active_story_block_ref)
    target = next(b for b in result.story_blocks if node_ref(b) == result.active_story_block_ref)
    mode = 'next_block' if target.volume_ref == active.volume_ref else 'next_volume'
    expansion = prepare_expansion(mode, draft, 1, authority)
    if expansion.target_block_ref and node_ref(target) != expansion.target_block_ref:
        raise ValueError('cannot skip an existing block')
    if expansion.target_volume_ref and target.volume_ref != expansion.target_volume_ref:
        raise ValueError('cannot skip an existing volume')
    if not expansion.target_block_ref and (target.order <= max(b.order for b in draft.story_blocks)
                                          or node_ref(target) in {node_ref(b) for b in draft.story_blocks}):
        raise ValueError('new block must follow existing blocks')
    volume = next(v for v in result.volumes if node_ref(v) == target.volume_ref)
    if not expansion.target_volume_ref and (volume.order <= max(v.order for v in draft.volumes)
                                           or node_ref(volume) in {node_ref(v) for v in draft.volumes}):
        raise ValueError('new volume must follow existing volumes')
    if missing_block_fields(target) or (mode == 'next_volume' and missing_volume_fields(volume)):
        raise ValueError('continuation target is incomplete')


def prepare_expansion(mode, draft, head_revision, authority):
    projection = authority["projection"]
    if (projection is None or authority["activeSession"] is not None
            or projection["canon_revision_number"] != projection["projection_revision_number"]):
        raise ValueError("planning expansion requires synchronized idle writing state")
    data = {"mode": mode, "authorityHash": expansion_authority_hash(authority),
            "continuity": {"previous_chapter": None, "actual_progress": []}}
    if mode == "initial":
        if head_revision != 0 or draft.story_blocks or projection["canon_revision_number"] != 0:
            raise ValueError("initial planning is already prepared")
        return PlanningExpansion.model_validate(data, strict=True)
    current = authority["current"]
    reason = planning_progress_reason(current)
    if (current is None or (mode != "revise_block" and reason not in
            {"activeStoryBlockCompleted", "activeStoryBlockTasksCompleted"})):
        raise ValueError("finish current story block before continuation")
    if mode == "revise_block" and reason is not None:
        raise ValueError("completed or unavailable block progress cannot be revised by AI")
    planning = PlanningAggregate.model_validate(current["planning_content"], strict=True)
    # Unsaved/revised arrangements must be handled before generating a continuation.
    from backend.services.planning_generation import PlanningGenerationService
    if draft != PlanningGenerationService._editable_draft(planning):
        raise ValueError("confirm or discard planning changes before continuation")
    active = next(b for b in draft.story_blocks if node_ref(b) == draft.active_story_block_ref)
    block = next(b for b in planning.story_blocks if b.id == planning.active_story_block_id)
    progress = actual_block_progress(current, block)
    if mode == "revise_block":
        data.update(targetVolumeRef=active.volume_ref, targetBlockRef=node_ref(active),
                    protectedNodeRefs=tuple(p.target_id for p in progress if p.target_type == "scene_task"
                                            or (p.target_type == "stage" and p.status == "completed")))
    volume = next(v for v in draft.volumes if node_ref(v) == active.volume_ref)
    following = sorted((b for b in draft.story_blocks if b.lifecycle == "active"
                        and b.volume_ref == active.volume_ref and b.order > active.order), key=lambda b: b.order)
    if mode in {"next_volume", "fill_next_volume"}:
        if following:
            raise ValueError("current volume still has planned story blocks")
        later = sorted((v for v in draft.volumes if v.lifecycle == "active" and v.order > volume.order), key=lambda v: v.order)
        volume = later[0] if later else None
        following = sorted((b for b in draft.story_blocks if b.lifecycle == "active"
                            and volume and b.volume_ref == node_ref(volume)), key=lambda b: b.order)
    data["targetVolumeRef"] = node_ref(volume) if volume else None
    if mode != "revise_block":
        data["targetBlockRef"] = node_ref(following[0]) if following else None
    if mode.startswith('fill_'):
        from backend.domain.planning_completion import missing_block_fields, missing_volume_fields
        target = following[0] if following else None
        if volume is None or (mode == 'fill_next_block' and target is None):
            raise ValueError('completion requires an existing target')
        if not ((target and missing_block_fields(target)) or
                (mode == 'fill_next_volume' and missing_volume_fields(volume))):
            raise ValueError('existing arrangement does not require completion')
        import json
        protected = []
        for row in current.get('actual_progress', []):
            payload = json.loads(row['payload_json']) if isinstance(row.get('payload_json'), str) else row.get('payload_json', {})
            if payload.get('targetId'): protected.append(payload['targetId'])
        data['protectedNodeRefs'] = tuple(protected)
    if current["canon_revision"] == 0:
        return PlanningExpansion.model_validate(data, strict=True)
    previous = current["previous_final_chapter"]
    validated = PreviousFinalChapter.model_validate({
        "id": previous["id"], "chapter_number": previous["chapter_num"],
        "canon_revision": previous["canon_revision"], "content": previous["content"],
        "content_hash": previous["content_hash"],
    }, strict=True)
    if validated.canon_revision != current["canon_revision"]:
        raise ValueError("previous final chapter authority changed")
    data["continuity"] = {
        "previous_chapter": validated.model_dump(mode="json"),
        "actual_progress": [p.model_dump(mode="json", by_alias=True) for p in progress],
    }
    return PlanningExpansion.model_validate(data, strict=True)
