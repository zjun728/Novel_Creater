from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import (
    DraftPlanningAggregate,
    PlanningDomainError,
    normalize_planning_aggregate,
    validate_confirmable_planning,
)


IDS = tuple(f"00000000-0000-0000-0000-{value:012d}" for value in range(1, 8))


def _valid_payload() -> dict[str, object]:
    return {
        "activeStoryBlockRef": "block-1",
        "volumes": [
            {
                "clientNodeKey": "volume-1",
                "lifecycle": "active",
                "order": 1,
                "title": "第一卷",
                "coreChange": "主角从逃亡者成长为一方势力的核心。",
                "mainPressure": "追兵与资源匮乏同时逼近。",
                "ensembleFocus": ["沈砚", "陆昭"],
                "forbiddenEvents": ["不可提前揭示最终幕后人"],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "plot-main",
                "lifecycle": "active",
                "order": 1,
                "title": "立足主线",
                "plotType": "main",
                "storyQuestion": "主角如何在陌生世界活下来？",
                "futureDirection": "从被动逃亡转为主动布局。",
                "expectedPayoff": "建立第一处可靠据点。",
                "relatedCharacters": ["沈砚"],
            },
            {
                "clientNodeKey": "plot-rel",
                "lifecycle": "active",
                "order": 2,
                "title": "脆弱同盟",
                "plotType": "relationship",
                "storyQuestion": "两个互不信任的人能否并肩？",
                "futureDirection": "利益合作逐步转为真正信任。",
                "expectedPayoff": "陆昭主动承担一次致命风险。",
                "relatedCharacters": ["沈砚", "陆昭"],
            },
        ],
        "storyBlocks": [
            {
                "clientNodeKey": "block-1",
                "lifecycle": "active",
                "order": 1,
                "title": "夜渡封锁线",
                "volumeRef": "volume-1",
                "plotRefs": ["plot-main", "plot-rel"],
                "entrySituation": "二人被困在封锁区内。",
                "blockGoal": "穿过封锁线并拿到落脚资源。",
                "mainPressure": "追兵不断压缩可选路线。",
                "expectedChange": "二人形成最低限度的信任。",
                "openQuestions": ["内应是谁"],
                "involvedCharacters": ["沈砚", "陆昭"],
                "stages": [
                    {
                        "clientNodeKey": "stage-1",
                        "lifecycle": "active",
                        "order": 1,
                        "title": "寻找缺口",
                        "purpose": "确认封锁的薄弱处。",
                        "dramaticQuestion": "他们能否在暴露前找到缺口？",
                        "sceneTasks": [
                            {
                                "clientNodeKey": "task-1",
                                "lifecycle": "active",
                                "order": 1,
                                "task": "潜入废弃驿站观察换岗。",
                                "completionEvidence": "取得完整换岗间隔。",
                            },
                            {
                                "clientNodeKey": "task-2",
                                "lifecycle": "active",
                                "order": 2,
                                "task": "试探暗渠是否仍可通行。",
                                "completionEvidence": "确认暗渠出口未被封死。",
                            },
                        ],
                    }
                ],
            }
        ],
    }


def _normalize(
    payload: dict[str, object] | None = None,
    *,
    previous_confirmed=None,
    previous_draft=None,
    ids: tuple[str, ...] = IDS,
):
    return normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate(payload or _valid_payload()),
        previous_confirmed=previous_confirmed,
        previous_draft=previous_draft,
        id_factory=iter(ids).__next__,
    )


@pytest.mark.parametrize(
    ("field", "alias"),
    (
        ("active_story_block_ref", "activeStoryBlockRef"),
        ("story_blocks", "storyBlocks"),
    ),
)
def test_planning_domain_rejects_python_field_names_at_public_boundary(
    field,
    alias,
):
    payload = _valid_payload()
    payload[field] = payload.pop(alias)

    with pytest.raises(ValidationError):
        DraftPlanningAggregate.model_validate(payload)


def _as_draft_payload(value) -> dict[str, object]:
    return {
        "activeStoryBlockRef": value.active_story_block_id,
        "volumes": [
            {
                **node.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude={"content_hash"},
                ),
                "contentHash": node.content_hash,
            }
            for node in value.volumes
        ],
        "plots": [
            {
                **node.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude={"content_hash"},
                ),
                "contentHash": node.content_hash,
            }
            for node in value.plots
        ],
        "storyBlocks": [
            {
                **block.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude={"content_hash", "volume_id", "plot_ids", "stages"},
                ),
                "contentHash": block.content_hash,
                "volumeRef": block.volume_id,
                "plotRefs": list(block.plot_ids),
                "stages": [
                    {
                        **stage.model_dump(
                            mode="json",
                            by_alias=True,
                            exclude={
                                "content_hash",
                                "story_block_id",
                                "scene_tasks",
                            },
                        ),
                        "contentHash": stage.content_hash,
                        "sceneTasks": [
                            {
                                **task.model_dump(
                                    mode="json",
                                    by_alias=True,
                                    exclude={"content_hash", "stage_id"},
                                ),
                                "contentHash": task.content_hash,
                            }
                            for task in stage.scene_tasks
                        ],
                    }
                    for stage in block.stages
                ],
            }
            for block in value.story_blocks
        ],
    }


def _all_nodes(value):
    return (
        list(value.volumes)
        + list(value.plots)
        + list(value.story_blocks)
        + [stage for block in value.story_blocks for stage in block.stages]
        + [
            task
            for block in value.story_blocks
            for stage in block.stages
            for task in stage.scene_tasks
        ]
    )


def test_normalizes_closed_aggregate_and_allocates_server_identities():
    normalized = _normalize()

    assert normalized.active_story_block_id == IDS[3]
    assert normalized.story_blocks[0].volume_id == IDS[0]
    assert normalized.story_blocks[0].plot_ids == (IDS[1], IDS[2])
    assert normalized.story_blocks[0].stages[0].story_block_id == IDS[3]
    assert normalized.story_blocks[0].stages[0].scene_tasks[0].stage_id == IDS[4]
    assert normalized.volumes[0].revision == 1
    assert [node.id for node in _all_nodes(normalized)] == list(IDS)
    assert all("clientNodeKey" not in node.model_dump(by_alias=True) for node in _all_nodes(normalized))
    assert normalized.content_hash == canonical_hash(
        normalized.model_dump(mode="json", by_alias=True, exclude={"content_hash"})
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "duplicate_client_key",
        "unknown_volume",
        "unknown_plot",
        "duplicate_order",
        "retired_active_block",
        "completed_lifecycle",
        "browser_supplied_new_id",
    ),
)
def test_invalid_aggregate_is_rejected(mutation):
    payload = _valid_payload()
    if mutation == "duplicate_client_key":
        payload["plots"][1]["clientNodeKey"] = "plot-main"
    elif mutation == "unknown_volume":
        payload["storyBlocks"][0]["volumeRef"] = "missing"
    elif mutation == "unknown_plot":
        payload["storyBlocks"][0]["plotRefs"] = ["plot-main", "missing"]
    elif mutation == "duplicate_order":
        payload["plots"][1]["order"] = 1
    elif mutation == "retired_active_block":
        payload["storyBlocks"][0]["lifecycle"] = "retired"
    elif mutation == "completed_lifecycle":
        payload["storyBlocks"][0]["lifecycle"] = "completed"
        with pytest.raises(ValidationError):
            DraftPlanningAggregate.model_validate(payload)
        return
    elif mutation == "browser_supplied_new_id":
        node = payload["volumes"][0]
        node.pop("clientNodeKey")
        node.update({"id": IDS[0], "revision": 1, "contentHash": "0" * 64})

    with pytest.raises(PlanningDomainError):
        _normalize(payload)


def test_unknown_fields_including_actual_progress_are_rejected():
    for field in ("completed", "in_progress", "targetChapterCount"):
        payload = _valid_payload()
        payload["storyBlocks"][0][field] = True
        with pytest.raises(ValidationError):
            DraftPlanningAggregate.model_validate(payload)


def test_duplicate_formal_id_and_duplicate_nested_order_are_rejected():
    confirmed = _normalize()
    payload = _as_draft_payload(confirmed)
    payload["plots"][1]["id"] = payload["plots"][0]["id"]
    payload["plots"][1]["revision"] = payload["plots"][0]["revision"]
    payload["plots"][1]["contentHash"] = payload["plots"][0]["contentHash"]
    with pytest.raises(PlanningDomainError, match="duplicate"):
        _normalize(payload, previous_confirmed=confirmed)

    payload = _as_draft_payload(confirmed)
    payload["storyBlocks"][0]["stages"][0]["sceneTasks"][1]["order"] = 1
    with pytest.raises(PlanningDomainError, match="order"):
        _normalize(payload, previous_confirmed=confirmed)


def test_server_issued_draft_id_remains_editable_across_saves():
    first_save = _normalize()
    payload = _as_draft_payload(first_save)
    payload["storyBlocks"][0]["blockGoal"] = "穿过封锁线、取得资源并救出向导。"

    second_save = _normalize(payload, previous_draft=first_save)

    assert second_save.story_blocks[0].id == first_save.story_blocks[0].id
    assert second_save.story_blocks[0].revision == 2
    assert second_save.story_blocks[0].content_hash != first_save.story_blocks[0].content_hash
    unchanged = {
        node.id: (node.revision, node.content_hash) for node in _all_nodes(first_save)
    }
    for node in _all_nodes(second_save):
        if node.id != first_save.story_blocks[0].id:
            assert (node.revision, node.content_hash) == unchanged[node.id]


def test_changed_order_or_parent_increments_exactly_once():
    first_save = _normalize()
    payload = _as_draft_payload(first_save)
    payload["plots"].append(
        {
            "clientNodeKey": "plot-third",
            "lifecycle": "active",
            "order": 3,
            "title": "追索",
            "plotType": "mystery",
            "storyQuestion": "谁泄露了路线？",
            "futureDirection": "逐步缩小嫌疑人。",
            "expectedPayoff": "揭出外围内应。",
            "relatedCharacters": ["沈砚"],
        }
    )
    payload["storyBlocks"][0]["plotRefs"] = [
        first_save.plots[0].id,
        "plot-third",
    ]
    ids = ("00000000-0000-0000-0000-000000000008",)

    second_save = _normalize(payload, previous_draft=first_save, ids=ids)

    assert second_save.story_blocks[0].revision == 2
    assert second_save.story_blocks[0].plot_ids == (
        first_save.plots[0].id,
        ids[0],
    )
    assert second_save.plots[0].revision == 1


def test_changed_order_increments_each_affected_node_exactly_once():
    first_save = _normalize()
    payload = _as_draft_payload(first_save)
    payload["plots"][0]["order"] = 2
    payload["plots"][1]["order"] = 1

    second_save = _normalize(payload, previous_draft=first_save)

    assert [plot.revision for plot in second_save.plots] == [2, 2]
    assert all(
        current.content_hash != previous.content_hash
        for current, previous in zip(second_save.plots, first_save.plots)
    )


def test_never_confirmed_draft_node_may_be_removed():
    first_save = _normalize()
    payload = _as_draft_payload(first_save)
    removed = payload["plots"].pop()
    payload["storyBlocks"][0]["plotRefs"].remove(removed["id"])

    second_save = _normalize(payload, previous_draft=first_save)

    assert removed["id"] not in {node.id for node in _all_nodes(second_save)}


def test_id_factory_cannot_recycle_a_server_issued_historical_id():
    confirmed = _normalize()
    payload = _as_draft_payload(confirmed)
    removed = payload["plots"].pop()
    payload["storyBlocks"][0]["plotRefs"].remove(removed["id"])
    payload["plots"].append(
        {
            "clientNodeKey": "replacement",
            "lifecycle": "active",
            "order": 2,
            "title": "替代支线",
            "plotType": "other",
            "storyQuestion": "替代支线将走向哪里？",
            "futureDirection": "保持开放。",
            "expectedPayoff": "形成新变化。",
            "relatedCharacters": [],
        }
    )
    payload["storyBlocks"][0]["plotRefs"].append("replacement")

    with pytest.raises(PlanningDomainError, match="collision"):
        _normalize(
            payload,
            previous_confirmed=confirmed,
            previous_draft=confirmed,
            ids=(removed["id"],),
        )


def test_id_factory_cannot_allocate_any_request_client_node_key():
    colliding_ids = (
        "plot-main",
        IDS[1],
        IDS[2],
        IDS[3],
        IDS[4],
        IDS[5],
        IDS[6],
    )

    with pytest.raises(PlanningDomainError, match="client node key"):
        _normalize(ids=colliding_ids)


def test_formal_id_and_client_key_cannot_create_an_ambiguous_reference_token():
    first_save = _normalize()
    payload = _as_draft_payload(first_save)
    payload["plots"].append(
        {
            "clientNodeKey": first_save.volumes[0].id,
            "lifecycle": "active",
            "order": 3,
            "title": "歧义支线",
            "plotType": "other",
            "storyQuestion": "引用会落到哪个节点？",
            "futureDirection": "不允许产生歧义。",
            "expectedPayoff": "请求被拒绝。",
            "relatedCharacters": [],
        }
    )

    with pytest.raises(PlanningDomainError, match="ambiguous"):
        _normalize(
            payload,
            previous_draft=first_save,
            ids=("00000000-0000-0000-0000-000000000008",),
        )


def test_unknown_browser_formal_id_is_rejected_even_with_valid_identity_shape():
    confirmed = _normalize()
    payload = _as_draft_payload(confirmed)
    payload["volumes"][0].update(
        {
            "id": "00000000-0000-0000-0000-999999999999",
            "revision": 1,
            "contentHash": "0" * 64,
        }
    )
    with pytest.raises(PlanningDomainError, match="server-issued"):
        _normalize(payload, previous_confirmed=confirmed)


def test_stale_or_forged_existing_identity_is_rejected():
    confirmed = _normalize()
    payload = _as_draft_payload(confirmed)
    payload["volumes"][0]["revision"] = 2
    with pytest.raises(PlanningDomainError, match="identity"):
        _normalize(payload, previous_confirmed=confirmed)


def test_historical_stable_ids_cannot_be_swapped_across_node_types():
    confirmed = _normalize()
    payload = _as_draft_payload(confirmed)
    volume_identity = {
        key: payload["volumes"][0][key]
        for key in ("id", "revision", "contentHash")
    }
    plot_identity = {
        key: payload["plots"][0][key]
        for key in ("id", "revision", "contentHash")
    }
    payload["volumes"][0].update(plot_identity)
    payload["plots"][0].update(volume_identity)
    payload["storyBlocks"][0]["volumeRef"] = plot_identity["id"]
    payload["storyBlocks"][0]["plotRefs"][0] = volume_identity["id"]

    with pytest.raises(PlanningDomainError, match="type"):
        _normalize(
            payload,
            previous_confirmed=confirmed,
            previous_draft=confirmed,
        )


def test_existing_story_block_can_change_to_another_volume_of_the_same_type():
    first_save = _normalize()
    payload = _as_draft_payload(first_save)
    payload["volumes"].append(
        {
            "clientNodeKey": "volume-2",
            "lifecycle": "active",
            "order": 2,
            "title": "第二卷",
            "coreChange": "同一故事块被重新安排到另一卷。",
            "mainPressure": "新的卷级压力。",
            "ensembleFocus": ["沈砚"],
            "forbiddenEvents": [],
        }
    )
    payload["storyBlocks"][0]["volumeRef"] = "volume-2"

    second_save = _normalize(
        payload,
        previous_confirmed=first_save,
        previous_draft=first_save,
        ids=("00000000-0000-0000-0000-000000000008",),
    )

    assert second_save.story_blocks[0].id == first_save.story_blocks[0].id
    assert second_save.story_blocks[0].volume_id == second_save.volumes[1].id
    assert second_save.story_blocks[0].revision == 2


def test_previous_confirmed_unreferenced_node_cannot_disappear():
    confirmed = _normalize()
    payload = _as_draft_payload(confirmed)
    omitted = payload["plots"].pop()
    payload["storyBlocks"][0]["plotRefs"].remove(omitted["id"])
    with pytest.raises(PlanningDomainError, match="historical node"):
        _normalize(
            payload,
            previous_confirmed=confirmed,
            previous_draft=confirmed,
        )


def test_confirmed_active_node_may_retire_but_never_reactivate_or_disappear():
    confirmed = _normalize()
    payload = _as_draft_payload(confirmed)
    payload["plots"][1]["lifecycle"] = "retired"
    payload["storyBlocks"][0]["plotRefs"].remove(confirmed.plots[1].id)
    retired = _normalize(
        payload,
        previous_confirmed=confirmed,
        previous_draft=confirmed,
    )
    assert retired.plots[1].lifecycle == "retired"
    assert retired.plots[1].revision == 2

    payload = _as_draft_payload(retired)
    payload["plots"][1]["lifecycle"] = "active"
    with pytest.raises(PlanningDomainError, match="reactivate"):
        _normalize(
            payload,
            previous_confirmed=retired,
            previous_draft=retired,
        )

    payload = _as_draft_payload(retired)
    payload["plots"].pop()
    with pytest.raises(PlanningDomainError, match="historical node"):
        _normalize(
            payload,
            previous_confirmed=retired,
            previous_draft=retired,
        )


def test_empty_draft_normalizes_but_is_not_confirmable():
    empty = _normalize(
        {
            "activeStoryBlockRef": None,
            "volumes": [],
            "plots": [],
            "storyBlocks": [],
        },
        ids=(),
    )
    assert empty.schema_version == "planning-v1"
    with pytest.raises(PlanningDomainError, match="confirm"):
        validate_confirmable_planning(empty)


def test_complete_aggregate_with_non_main_plot_is_confirmable():
    payload = _valid_payload()
    payload["plots"] = [payload["plots"][1]]
    payload["plots"][0]["order"] = 1
    payload["storyBlocks"][0]["plotRefs"] = ["plot-rel"]
    normalized = _normalize(
        payload,
        ids=(IDS[0], IDS[1], IDS[3], IDS[4], IDS[5], IDS[6]),
    )

    validate_confirmable_planning(normalized)


@pytest.mark.parametrize("missing", ("volume", "plot", "block", "stage", "task"))
def test_incomplete_active_slice_is_not_confirmable(missing):
    payload = _valid_payload()
    if missing == "volume":
        payload["volumes"][0]["lifecycle"] = "retired"
    elif missing == "plot":
        for plot in payload["plots"]:
            plot["lifecycle"] = "retired"
    elif missing == "block":
        payload["activeStoryBlockRef"] = None
        payload["storyBlocks"][0]["lifecycle"] = "retired"
    elif missing == "stage":
        payload["storyBlocks"][0]["stages"][0]["lifecycle"] = "retired"
    elif missing == "task":
        for task in payload["storyBlocks"][0]["stages"][0]["sceneTasks"]:
            task["lifecycle"] = "retired"
    normalized = _normalize(payload)
    with pytest.raises(PlanningDomainError, match="confirm"):
        validate_confirmable_planning(normalized)


def test_active_block_cannot_reference_retired_volume_or_plot_at_confirmation():
    for collection in ("volumes", "plots"):
        payload = _valid_payload()
        payload[collection][0]["lifecycle"] = "retired"
        normalized = _normalize(payload)
        with pytest.raises(PlanningDomainError, match="active"):
            validate_confirmable_planning(normalized)


def test_input_objects_are_not_mutated():
    payload = _valid_payload()
    before = deepcopy(payload)
    _normalize(payload)
    assert payload == before
