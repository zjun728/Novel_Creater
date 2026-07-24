from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.domain.chapter_outlines import (
    ChapterOutlineDomainError,
    DraftChapterOutline,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.json_contracts import canonical_hash
from backend.tests.unit.test_planning_domain import IDS, _normalize


PLANNING_REVISION_ID = "00000000-0000-0000-0000-000000000301"
CAPACITY = OutlineCapacityPolicy.model_validate(
    {"targetMin": 2500, "targetMax": 3200, "softCeiling": 3800}
)


def _ref(node) -> dict[str, object]:
    return {
        "id": node.id,
        "revision": node.revision,
        "contentHash": node.content_hash,
    }


def _outline_payload(planning=None) -> dict[str, object]:
    planning = planning or _normalize()
    block = planning.story_blocks[0]
    stage = block.stages[0]
    return {
        "schemaVersion": "chapter-outline-v1",
        "chapterNumber": 1,
        "planningRevisionId": PLANNING_REVISION_ID,
        "planningRevision": 1,
        "planningHash": planning.content_hash,
        "volumeRef": _ref(planning.volumes[0]),
        "storyBlockRef": _ref(block),
        "stageRefs": [_ref(stage)],
        "sceneTaskRefs": [_ref(task) for task in stage.scene_tasks],
        "chapterGoal": "找到穿越封锁线的可行缺口。",
        "expectedCharacters": ["沈砚", "陆昭"],
        "continuation": ["承接二人被困封锁区的局面"],
        "plannedTasks": ["观察换岗", "试探暗渠"],
        "scenes": ["废弃驿站的夜间侦察", "暗渠入口的试探"],
        "forbiddenEarlyEvents": ["不可提前揭示内应"],
        "capacityPolicy": CAPACITY.model_dump(mode="json", by_alias=True),
    }


def _normalize_outline(payload=None, *, planning=None, **overrides):
    planning = planning or _normalize()
    arguments = {
        "planning": planning,
        "authoritative_chapter_number": 1,
        "planning_revision_id": PLANNING_REVISION_ID,
        "planning_revision": 1,
        "capacity_policy": CAPACITY,
        "canon_revision": 0,
        "projection_revision": 0,
        "projection_hash": "0" * 64,
    }
    arguments.update(overrides)
    return normalize_chapter_outline(
        DraftChapterOutline.model_validate(payload or _outline_payload(planning)),
        **arguments,
    )


def test_normalizes_closed_outline_and_computes_hash_server_side():
    planning = _normalize()
    validated = _normalize_outline(planning=planning)

    assert validated.chapter_number == 1
    assert validated.story_block_ref.id == planning.story_blocks[0].id
    assert validated.canon_revision == 0
    assert validated.projection_revision == 0
    assert validated.projection_hash == "0" * 64
    assert validated.content_hash == canonical_hash(
        validated.model_dump(mode="json", by_alias=True, exclude={"content_hash"})
    )


@pytest.mark.parametrize("field", ("contentHash", "extraField"))
def test_browser_cannot_supply_outline_hash_or_extra_fields(field):
    payload = _outline_payload()
    payload[field] = "0" * 64
    with pytest.raises(ValidationError):
        DraftChapterOutline.model_validate(payload)


def test_chapter_number_must_be_positive_and_match_server_authority():
    payload = _outline_payload()
    payload["chapterNumber"] = 0
    with pytest.raises(ValidationError):
        DraftChapterOutline.model_validate(payload)

    payload["chapterNumber"] = 2
    with pytest.raises(ChapterOutlineDomainError, match="chapter"):
        _normalize_outline(payload)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("planningRevisionId", "wrong", "Planning authority"),
        ("planningRevision", 2, "Planning authority"),
        ("planningHash", "f" * 64, "Planning authority"),
    ),
)
def test_expected_planning_authority_must_match_locked_server_values(
    field,
    value,
    match,
):
    payload = _outline_payload()
    payload[field] = value
    with pytest.raises(ChapterOutlineDomainError, match=match):
        _normalize_outline(payload)


def test_capacity_must_match_locked_contract_snapshot():
    payload = _outline_payload()
    payload["capacityPolicy"]["targetMax"] = 3300
    with pytest.raises(ChapterOutlineDomainError, match="capacity"):
        _normalize_outline(payload)


@pytest.mark.parametrize(
    "policy",
    (
        {"targetMin": 3300, "targetMax": 3200, "softCeiling": 3800},
        {"targetMin": 2500, "targetMax": 3900, "softCeiling": 3800},
    ),
)
def test_invalid_capacity_order_is_rejected_before_normalization(policy):
    with pytest.raises(ValidationError):
        OutlineCapacityPolicy.model_validate(policy)


def test_canon_and_projection_must_be_synchronized():
    with pytest.raises(ChapterOutlineDomainError, match="synchronized"):
        _normalize_outline(canon_revision=2, projection_revision=1)


def test_projection_hash_must_be_canonical_sha256():
    with pytest.raises(ChapterOutlineDomainError, match="projection"):
        _normalize_outline(projection_hash="not-a-hash")


@pytest.mark.parametrize(
    ("field", "index"),
    (
        ("volumeRef", None),
        ("storyBlockRef", None),
        ("stageRefs", 0),
        ("sceneTaskRefs", 0),
    ),
)
@pytest.mark.parametrize("identity_part", ("id", "revision", "contentHash"))
def test_unknown_or_mismatched_node_identity_is_rejected(
    field,
    index,
    identity_part,
):
    payload = _outline_payload()
    ref = payload[field] if index is None else payload[field][index]
    if identity_part == "id":
        ref["id"] = "00000000-0000-0000-0000-999999999999"
    elif identity_part == "revision":
        ref["revision"] += 1
    else:
        ref["contentHash"] = "f" * 64
    with pytest.raises(ChapterOutlineDomainError, match="reference"):
        _normalize_outline(payload)


@pytest.mark.parametrize("field", ("stageRefs", "sceneTaskRefs"))
def test_outline_requires_at_least_one_stage_and_scene_task(field):
    payload = _outline_payload()
    payload[field] = []
    with pytest.raises(ValidationError):
        DraftChapterOutline.model_validate(payload)


def _with_second_block(planning):
    original = planning.story_blocks[0]
    other_stage = original.stages[0].model_copy(
        update={
            "id": "00000000-0000-0000-0000-000000000402",
            "story_block_id": "00000000-0000-0000-0000-000000000401",
            "content_hash": "4" * 64,
            "scene_tasks": (
                original.stages[0].scene_tasks[0].model_copy(
                    update={
                        "id": "00000000-0000-0000-0000-000000000403",
                        "stage_id": "00000000-0000-0000-0000-000000000402",
                        "content_hash": "5" * 64,
                    }
                ),
            ),
        }
    )
    other_block = original.model_copy(
        update={
            "id": "00000000-0000-0000-0000-000000000401",
            "content_hash": "3" * 64,
            "order": 2,
            "stages": (other_stage,),
        }
    )
    return planning.model_copy(
        update={"story_blocks": planning.story_blocks + (other_block,)}
    ), other_block


def test_story_block_must_be_current_active_block_even_when_identity_is_exact():
    planning, other_block = _with_second_block(_normalize())
    payload = _outline_payload(planning)
    payload["storyBlockRef"] = _ref(other_block)
    payload["stageRefs"] = [_ref(other_block.stages[0])]
    payload["sceneTaskRefs"] = [_ref(other_block.stages[0].scene_tasks[0])]
    with pytest.raises(ChapterOutlineDomainError, match="current active"):
        _normalize_outline(payload, planning=planning)


def test_volume_must_belong_to_selected_story_block():
    planning = _normalize()
    other_volume = planning.volumes[0].model_copy(
        update={
            "id": "00000000-0000-0000-0000-000000000404",
            "content_hash": "6" * 64,
            "order": 2,
        }
    )
    planning = planning.model_copy(
        update={"volumes": planning.volumes + (other_volume,)}
    )
    payload = _outline_payload(planning)
    payload["volumeRef"] = _ref(other_volume)
    with pytest.raises(ChapterOutlineDomainError, match="Volume"):
        _normalize_outline(payload, planning=planning)


def test_stage_from_other_block_is_rejected_even_when_identity_is_exact():
    planning, other_block = _with_second_block(_normalize())
    payload = _outline_payload(planning)
    payload["stageRefs"] = [_ref(other_block.stages[0])]
    payload["sceneTaskRefs"] = [_ref(other_block.stages[0].scene_tasks[0])]
    with pytest.raises(ChapterOutlineDomainError, match="Stage"):
        _normalize_outline(payload, planning=planning)


def test_scene_task_from_unselected_stage_is_rejected():
    planning = _normalize()
    block = planning.story_blocks[0]
    selected_stage = block.stages[0]
    other_task = selected_stage.scene_tasks[0].model_copy(
        update={
            "id": "00000000-0000-0000-0000-000000000405",
            "stage_id": "00000000-0000-0000-0000-000000000406",
            "content_hash": "7" * 64,
        }
    )
    other_stage = selected_stage.model_copy(
        update={
            "id": "00000000-0000-0000-0000-000000000406",
            "content_hash": "8" * 64,
            "order": 2,
            "scene_tasks": (other_task,),
        }
    )
    changed_block = block.model_copy(
        update={"stages": block.stages + (other_stage,)}
    )
    planning = planning.model_copy(update={"story_blocks": (changed_block,)})
    payload = _outline_payload(planning)
    payload["sceneTaskRefs"] = [_ref(other_task)]
    with pytest.raises(ChapterOutlineDomainError, match="selected Stage"):
        _normalize_outline(payload, planning=planning)


@pytest.mark.parametrize("kind", ("volume", "block", "stage", "task"))
def test_retired_node_is_rejected_from_outline(kind):
    planning = _normalize()
    block = planning.story_blocks[0]
    stage = block.stages[0]
    payload = _outline_payload(planning)
    if kind == "volume":
        retired = planning.volumes[0].model_copy(update={"lifecycle": "retired"})
        planning = planning.model_copy(update={"volumes": (retired,)})
        payload["volumeRef"] = _ref(retired)
    elif kind == "block":
        retired = block.model_copy(update={"lifecycle": "retired"})
        planning = planning.model_copy(update={"story_blocks": (retired,)})
        payload["storyBlockRef"] = _ref(retired)
    elif kind == "stage":
        retired = stage.model_copy(update={"lifecycle": "retired"})
        changed = block.model_copy(update={"stages": (retired,)})
        planning = planning.model_copy(update={"story_blocks": (changed,)})
        payload["stageRefs"] = [_ref(retired)]
    else:
        retired = stage.scene_tasks[0].model_copy(update={"lifecycle": "retired"})
        changed_stage = stage.model_copy(
            update={"scene_tasks": (retired, stage.scene_tasks[1])}
        )
        changed = block.model_copy(update={"stages": (changed_stage,)})
        planning = planning.model_copy(update={"story_blocks": (changed,)})
        payload["sceneTaskRefs"][0] = _ref(retired)
    with pytest.raises(ChapterOutlineDomainError, match="active"):
        _normalize_outline(payload, planning=planning)


def test_outline_input_is_not_mutated():
    payload = _outline_payload()
    before = deepcopy(payload)
    _normalize_outline(payload)
    assert payload == before
