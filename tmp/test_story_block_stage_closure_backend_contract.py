import sys
from pathlib import Path

sys.path.insert(0, str(Path("backend").resolve()))

from routers import story_blocks


def test_unexecuted_stages_closed_with_block_are_not_completed():
    stage_plan = [
        {"id": "stage-1", "status": "completed", "completedChapterNum": 1, "chapterRefs": [1]},
        {"id": "stage-2", "status": "planned"},
        {"id": "stage-3", "status": "planned"},
    ]

    archived = story_blocks._archive_unfinished_stages_for_closed_block(stage_plan, set())

    assert archived[0]["status"] == "completed"
    assert archived[1]["status"] in {"closed_unexecuted", "skipped_by_block_close"}
    assert archived[2]["status"] in {"closed_unexecuted", "skipped_by_block_close"}
    assert archived[1]["status"] != "completed"
    assert archived[2]["status"] != "completed"


def test_ai_completed_stage_ids_are_filtered_to_executed_stage():
    block = {
        "stage_plan": [
            {"id": "stage-1", "status": "planned", "chapterRefs": [1]},
            {"id": "stage-2", "status": "planned"},
            {"id": "stage-3", "status": "planned"},
            {"id": "stage-4", "status": "planned"},
        ]
    }
    review = {
        "blockStageSnapshot": {"stageId": "stage-1"},
        "completedStageIds": ["stage-1", "stage-2", "stage-3", "stage-4"],
    }

    filtered = story_blocks._filter_executed_completed_stage_ids(
        block,
        review,
        ["stage-1", "stage-2", "stage-3", "stage-4"],
    )

    assert filtered == ["stage-1"]


if __name__ == "__main__":
    test_unexecuted_stages_closed_with_block_are_not_completed()
    test_ai_completed_stage_ids_are_filtered_to_executed_stage()
