import sys
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path("backend").resolve()))

from routers import story_blocks


def expect_http_409(fn):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == 409
        return
    raise AssertionError("expected HTTPException 409")


def test_metadata_only_remaining_stage_update_keeps_locked_stage_plan():
    existing = [
        {"id": "stage-1", "status": "completed", "chapterRefs": [1], "purpose": "已执行阶段"},
        {"id": "stage-2", "status": "planned", "purpose": "未来阶段"},
    ]

    merged = story_blocks._merge_remaining_stage_update(
        existing,
        None,
        locked_stage_ids={"stage-1"},
        completed_ids={"stage-1"},
        closed_ids=set(),
    )

    assert merged == existing


def test_editable_future_patch_updates_only_unlocked_future_stage():
    existing = [
        {"id": "stage-1", "status": "completed", "chapterRefs": [1], "purpose": "已执行阶段"},
        {"id": "stage-2", "status": "planned", "purpose": "旧未来阶段"},
    ]

    merged = story_blocks._merge_remaining_stage_update(
        existing,
        [{"id": "stage-2", "status": "planned", "purpose": "新未来阶段"}],
        locked_stage_ids={"stage-1"},
        completed_ids={"stage-1"},
        closed_ids=set(),
        patch_mode="editable_future_only",
    )

    assert merged[0] == existing[0]
    assert merged[1]["purpose"] == "新未来阶段"


def test_editable_future_patch_rejects_locked_stage_modification():
    existing = [
        {"id": "stage-1", "status": "completed", "chapterRefs": [1], "purpose": "已执行阶段"},
        {"id": "stage-2", "status": "planned", "purpose": "未来阶段"},
    ]

    def modify_locked():
        story_blocks._merge_remaining_stage_update(
            existing,
            [{"id": "stage-1", "status": "planned", "purpose": "试图回改已执行阶段"}],
            locked_stage_ids={"stage-1"},
            completed_ids={"stage-1"},
            closed_ids=set(),
            patch_mode="editable_future_only",
        )

    expect_http_409(modify_locked)


def test_full_replace_still_rejects_locked_stage_modification():
    existing = [
        {"id": "stage-1", "status": "completed", "chapterRefs": [1], "purpose": "已执行阶段"},
        {"id": "stage-2", "status": "planned", "purpose": "未来阶段"},
    ]

    def modify_locked():
        story_blocks._merge_remaining_stage_update(
            existing,
            [{"id": "stage-1", "status": "planned", "purpose": "试图回改已执行阶段"}],
            locked_stage_ids={"stage-1"},
            completed_ids={"stage-1"},
            closed_ids=set(),
        )

    expect_http_409(modify_locked)


if __name__ == "__main__":
    test_metadata_only_remaining_stage_update_keeps_locked_stage_plan()
    test_editable_future_patch_updates_only_unlocked_future_stage()
    test_editable_future_patch_rejects_locked_stage_modification()
    test_full_replace_still_rejects_locked_stage_modification()
