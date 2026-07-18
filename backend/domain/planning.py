from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class VolumePlanView:
    id: str
    project_id: str
    volume_num: int
    title: str
    direction: Mapping[str, Any]
    revision: int
    status: str


@dataclass(frozen=True)
class StoryBlockView:
    id: str
    project_id: str
    volume_plan_id: str
    block_num: int
    title: str
    goal: Mapping[str, Any]
    revision: int
    status: str


@dataclass(frozen=True)
class StoryStageView:
    id: str
    project_id: str
    story_block_id: str
    stage_order: int
    title: str
    plan: Mapping[str, Any]
    revision: int
    status: str


@dataclass(frozen=True)
class SceneTaskView:
    id: str
    project_id: str
    story_stage_id: str
    task_order: int
    task: Mapping[str, Any]
    revision: int
    status: str


@dataclass(frozen=True)
class PlanningState:
    project_id: str
    has_planning: bool
    contract_revision: int
    active_volume: VolumePlanView | None
    active_block: StoryBlockView | None
    stages: tuple[StoryStageView, ...]
    scene_tasks: tuple[SceneTaskView, ...]
    manifest_hash: str | None
    selection_revision: int = 0
    contract_hash: str | None = None
    bible_revision: int = 0
    bible_hash: str | None = None

    @property
    def planning_ready(self) -> bool:
        return (
            self.has_planning
            and self.active_volume is not None
            and self.active_block is not None
            and any(stage.status in {"pending", "in_progress"} for stage in self.stages)
            and any(task.status in {"pending", "in_progress"} for task in self.scene_tasks)
        )
