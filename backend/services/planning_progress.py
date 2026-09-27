"""Read the same validated planning progress used by outline generation."""
import json
from backend.domain.planning import PlanningAggregate
from backend.prompts.chapter_outline import ActualPlanningProgress


def actual_block_progress(current, block):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate actual progress key")
            result[key] = value
        return result
    progress = []
    if int(current["canon_revision"]) > 0:
        targets = {("story_block", block.id)}
        targets.update(("stage", stage.id) for stage in block.stages)
        targets.update(("scene_task", task.id)
                       for stage in block.stages for task in stage.scene_tasks)
        for row in current["actual_progress"]:
            if (type(row["revision_number"]) is not int
                or row["revision_number"] != current["projection_revision"]
                or row["content_hash"] != current["projection_hash"]
                or row["subject_key"] != "__global__"
                or row["entity_id"] is not None):
                raise ValueError("actual progress authority changed")
            item = ActualPlanningProgress.model_validate(
                json.loads(row["payload_json"], object_pairs_hook=unique_object),
                strict=True,
            )
            if row["field_path"] != f"plot.progress.{item.target_type}.{item.target_id}":
                raise ValueError("actual progress target changed")
            if (item.target_type, item.target_id) in targets:
                progress.append(item)
    return tuple(progress)


def planning_progress_reason(current):
    if current is None:
        return None
    try:
        if current["canon_revision"] == 0:
            return None
        planning = PlanningAggregate.model_validate(current["planning_content"], strict=True)
        block = next(item for item in planning.story_blocks
                     if item.id == planning.active_story_block_id and item.lifecycle == "active")
        progress = actual_block_progress(current, block)
        if any(item.target_type == "story_block" and item.target_id == block.id
               and item.status == "completed" for item in progress):
            return "activeStoryBlockCompleted"
        completed = {(item.target_type, item.target_id) for item in progress if item.status == "completed"}
        remaining = [task for stage in block.stages if stage.lifecycle == "active"
                     and ("stage", stage.id) not in completed
                     for task in stage.scene_tasks if task.lifecycle == "active"
                     and ("scene_task", task.id) not in completed]
        return None if remaining else "activeStoryBlockTasksCompleted"
    except (KeyError, TypeError, ValueError, StopIteration):
        return "planningProgressUnavailable"
