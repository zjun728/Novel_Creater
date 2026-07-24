"""Closed, revisioned future-story Planning aggregate."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.json_contracts import canonical_hash


Hash = str
Lifecycle = Literal["active", "retired"]
PlotType = Literal[
    "main",
    "character",
    "relationship",
    "conflict",
    "mystery",
    "other",
]


class PlanningDomainError(ValueError):
    """Raised when a Planning draft violates the closed aggregate boundary."""


class _StrictPlanningValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def accept_json_arrays(cls, value):
        if isinstance(value, dict):
            return {
                key: tuple(item) if isinstance(item, list) else item
                for key, item in value.items()
            }
        return value


class DraftNode(_StrictPlanningValue):
    id: str | None = None
    client_key: str | None = Field(default=None, alias="clientNodeKey")
    revision: int | None = Field(default=None, ge=1)
    content_hash: Hash | None = Field(
        default=None,
        alias="contentHash",
        pattern=r"^[0-9a-f]{64}$",
    )
    lifecycle: Lifecycle = "active"

    @model_validator(mode="after")
    def validate_identity_shape(self) -> Self:
        is_new = (
            self.client_key is not None
            and self.id is None
            and self.revision is None
            and self.content_hash is None
        )
        is_existing = (
            self.client_key is None
            and self.id is not None
            and self.revision is not None
            and self.content_hash is not None
        )
        if not (is_new or is_existing):
            raise ValueError(
                "node identity must be either clientNodeKey or id/revision/contentHash"
            )
        return self


class DraftVolume(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    core_change: str = Field(alias="coreChange", min_length=1, max_length=4000)
    main_pressure: str = Field(alias="mainPressure", max_length=4000)
    ensemble_focus: tuple[str, ...] = Field(alias="ensembleFocus")
    forbidden_events: tuple[str, ...] = Field(alias="forbiddenEvents")


class DraftPlot(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    plot_type: PlotType = Field(alias="plotType")
    story_question: str = Field(
        alias="storyQuestion",
        min_length=1,
        max_length=4000,
    )
    future_direction: str = Field(alias="futureDirection", max_length=4000)
    expected_payoff: str = Field(alias="expectedPayoff", max_length=4000)
    related_characters: tuple[str, ...] = Field(alias="relatedCharacters")


class DraftSceneTask(DraftNode):
    order: int = Field(ge=1)
    task: str = Field(min_length=1, max_length=4000)
    completion_evidence: str = Field(
        alias="completionEvidence",
        min_length=1,
        max_length=4000,
    )


class DraftStage(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=4000)
    dramatic_question: str = Field(
        alias="dramaticQuestion",
        min_length=1,
        max_length=4000,
    )
    scene_tasks: tuple[DraftSceneTask, ...] = Field(alias="sceneTasks")


class DraftStoryBlock(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    volume_ref: str = Field(alias="volumeRef", min_length=1)
    plot_refs: tuple[str, ...] = Field(alias="plotRefs", min_length=1)
    entry_situation: str = Field(alias="entrySituation", max_length=4000)
    block_goal: str = Field(alias="blockGoal", min_length=1, max_length=4000)
    main_pressure: str = Field(alias="mainPressure", max_length=4000)
    expected_change: str = Field(alias="expectedChange", max_length=4000)
    open_questions: tuple[str, ...] = Field(alias="openQuestions")
    involved_characters: tuple[str, ...] = Field(alias="involvedCharacters")
    stages: tuple[DraftStage, ...]


class DraftPlanningAggregate(_StrictPlanningValue):
    active_story_block_ref: str | None = Field(alias="activeStoryBlockRef")
    volumes: tuple[DraftVolume, ...]
    plots: tuple[DraftPlot, ...]
    story_blocks: tuple[DraftStoryBlock, ...] = Field(alias="storyBlocks")


class PersistedNode(_StrictPlanningValue):
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: Hash = Field(
        alias="contentHash",
        pattern=r"^[0-9a-f]{64}$",
    )
    lifecycle: Lifecycle


class Volume(PersistedNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    core_change: str = Field(alias="coreChange", min_length=1, max_length=4000)
    main_pressure: str = Field(alias="mainPressure", max_length=4000)
    ensemble_focus: tuple[str, ...] = Field(alias="ensembleFocus")
    forbidden_events: tuple[str, ...] = Field(alias="forbiddenEvents")


class Plot(PersistedNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    plot_type: PlotType = Field(alias="plotType")
    story_question: str = Field(
        alias="storyQuestion",
        min_length=1,
        max_length=4000,
    )
    future_direction: str = Field(alias="futureDirection", max_length=4000)
    expected_payoff: str = Field(alias="expectedPayoff", max_length=4000)
    related_characters: tuple[str, ...] = Field(alias="relatedCharacters")


class SceneTask(PersistedNode):
    stage_id: str = Field(alias="stageId", min_length=1)
    order: int = Field(ge=1)
    task: str = Field(min_length=1, max_length=4000)
    completion_evidence: str = Field(
        alias="completionEvidence",
        min_length=1,
        max_length=4000,
    )


class Stage(PersistedNode):
    story_block_id: str = Field(alias="storyBlockId", min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=4000)
    dramatic_question: str = Field(
        alias="dramaticQuestion",
        min_length=1,
        max_length=4000,
    )
    scene_tasks: tuple[SceneTask, ...] = Field(alias="sceneTasks")


class StoryBlock(PersistedNode):
    volume_id: str = Field(alias="volumeId", min_length=1)
    plot_ids: tuple[str, ...] = Field(alias="plotIds", min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    entry_situation: str = Field(alias="entrySituation", max_length=4000)
    block_goal: str = Field(alias="blockGoal", min_length=1, max_length=4000)
    main_pressure: str = Field(alias="mainPressure", max_length=4000)
    expected_change: str = Field(alias="expectedChange", max_length=4000)
    open_questions: tuple[str, ...] = Field(alias="openQuestions")
    involved_characters: tuple[str, ...] = Field(alias="involvedCharacters")
    stages: tuple[Stage, ...]


class PlanningAggregate(_StrictPlanningValue):
    schema_version: Literal["planning-v1"] = Field(
        default="planning-v1",
        alias="schemaVersion",
    )
    active_story_block_id: str | None = Field(alias="activeStoryBlockId")
    volumes: tuple[Volume, ...]
    plots: tuple[Plot, ...]
    story_blocks: tuple[StoryBlock, ...] = Field(alias="storyBlocks")
    content_hash: Hash = Field(
        alias="contentHash",
        pattern=r"^[0-9a-f]{64}$",
    )


def _iter_draft_nodes(draft: DraftPlanningAggregate):
    yield from draft.volumes
    yield from draft.plots
    for block in draft.story_blocks:
        yield block
        for stage in block.stages:
            yield stage
            yield from stage.scene_tasks


def _iter_nodes(value: PlanningAggregate):
    yield from value.volumes
    yield from value.plots
    for block in value.story_blocks:
        yield block
        for stage in block.stages:
            yield stage
            yield from stage.scene_tasks


def _node_map(value: PlanningAggregate | None) -> dict[str, PersistedNode]:
    if value is None:
        return {}
    return {node.id: node for node in _iter_nodes(value)}


def _ensure_unique_orders(
    label: str,
    nodes: tuple[DraftNode, ...],
) -> None:
    orders = [getattr(node, "order") for node in nodes]
    if len(orders) != len(set(orders)):
        raise PlanningDomainError(f"duplicate {label} order")


def _node_hash(payload: dict[str, object]) -> str:
    return canonical_hash(payload)


def _identity(
    draft_node: DraftNode,
    *,
    node_id: str,
    previous_confirmed: Mapping[str, PersistedNode],
    previous_draft: Mapping[str, PersistedNode],
) -> tuple[int, Hash | None, PersistedNode | None]:
    baseline = previous_draft.get(node_id) or previous_confirmed.get(node_id)
    if draft_node.id is not None:
        if baseline is None:
            raise PlanningDomainError("formal ID was not server-issued")
        expected_type = {
            DraftVolume: Volume,
            DraftPlot: Plot,
            DraftStoryBlock: StoryBlock,
            DraftStage: Stage,
            DraftSceneTask: SceneTask,
        }[type(draft_node)]
        if type(baseline) is not expected_type:
            raise PlanningDomainError(
                "historical stable ID cannot change node type"
            )
        if (
            draft_node.revision != baseline.revision
            or draft_node.content_hash != baseline.content_hash
        ):
            raise PlanningDomainError("formal node identity does not match server state")
    if (
        node_id in previous_confirmed
        and previous_confirmed[node_id].lifecycle == "retired"
        and draft_node.lifecycle == "active"
    ):
        raise PlanningDomainError("retired historical node cannot reactivate")
    return (
        baseline.revision if baseline is not None else 1,
        baseline.content_hash if baseline is not None else None,
        baseline,
    )


def _revisioned_identity(
    draft_node: DraftNode,
    *,
    node_id: str,
    payload: dict[str, object],
    previous_confirmed: Mapping[str, PersistedNode],
    previous_draft: Mapping[str, PersistedNode],
) -> tuple[int, Hash]:
    current_revision, previous_hash, baseline = _identity(
        draft_node,
        node_id=node_id,
        previous_confirmed=previous_confirmed,
        previous_draft=previous_draft,
    )
    content_hash = _node_hash(payload)
    revision = (
        current_revision
        if baseline is None or content_hash == previous_hash
        else current_revision + 1
    )
    return revision, content_hash


def _formal_payload(
    node_id: str,
    draft_node: DraftNode,
    fields: dict[str, object],
) -> dict[str, object]:
    return {
        "id": node_id,
        "lifecycle": draft_node.lifecycle,
        **fields,
    }


def normalize_planning_aggregate(
    draft: DraftPlanningAggregate,
    *,
    previous_confirmed: PlanningAggregate | None,
    previous_draft: PlanningAggregate | None,
    id_factory: Callable[[], str],
) -> PlanningAggregate:
    """Allocate IDs, validate one-way relations, and derive local revisions."""

    confirmed_nodes = _node_map(previous_confirmed)
    draft_nodes = _node_map(previous_draft)
    all_draft_nodes = tuple(_iter_draft_nodes(draft))

    formal_ids = [node.id for node in all_draft_nodes if node.id is not None]
    client_keys = [
        node.client_key for node in all_draft_nodes if node.client_key is not None
    ]
    if len(formal_ids) != len(set(formal_ids)):
        raise PlanningDomainError("duplicate formal node ID")
    if len(client_keys) != len(set(client_keys)):
        raise PlanningDomainError("duplicate client node key")
    if set(formal_ids).intersection(client_keys):
        raise PlanningDomainError("ambiguous formal ID and client node key")
    client_key_set = set(client_keys)

    _ensure_unique_orders("Volume", draft.volumes)
    _ensure_unique_orders("Plot", draft.plots)
    _ensure_unique_orders("StoryBlock", draft.story_blocks)
    for block in draft.story_blocks:
        _ensure_unique_orders("Stage", block.stages)
        for stage in block.stages:
            _ensure_unique_orders("SceneTask", stage.scene_tasks)

    resolved_ids: dict[str, str] = {}
    used_ids: set[str] = set()
    for node in all_draft_nodes:
        if node.id is not None:
            node_id = node.id
        else:
            node_id = id_factory()
            if not isinstance(node_id, str) or not node_id:
                raise PlanningDomainError("id_factory must return a non-empty string")
            if node_id in client_key_set:
                raise PlanningDomainError(
                    "new node ID collision with request client node key"
                )
            if node_id in confirmed_nodes or node_id in draft_nodes:
                raise PlanningDomainError(
                    "new node ID collision with server-issued identity"
                )
        if node_id in used_ids:
            raise PlanningDomainError("duplicate allocated node ID")
        used_ids.add(node_id)
        ref = node.id or node.client_key
        assert ref is not None
        resolved_ids[ref] = node_id

    def resolve(ref: str, kind: str) -> str:
        try:
            return resolved_ids[ref]
        except KeyError as exc:
            raise PlanningDomainError(f"unknown {kind} relation") from exc

    volumes: list[Volume] = []
    for node in draft.volumes:
        node_id = resolve(node.id or node.client_key or "", "Volume")
        fields = {
            "order": node.order,
            "title": node.title,
            "coreChange": node.core_change,
            "mainPressure": node.main_pressure,
            "ensembleFocus": node.ensemble_focus,
            "forbiddenEvents": node.forbidden_events,
        }
        revision, content_hash = _revisioned_identity(
            node,
            node_id=node_id,
            payload=_formal_payload(node_id, node, fields),
            previous_confirmed=confirmed_nodes,
            previous_draft=draft_nodes,
        )
        volumes.append(
            Volume.model_validate(
                {
                    **_formal_payload(node_id, node, fields),
                    "revision": revision,
                    "contentHash": content_hash,
                }
            )
        )

    plots: list[Plot] = []
    for node in draft.plots:
        node_id = resolve(node.id or node.client_key or "", "Plot")
        fields = {
            "order": node.order,
            "title": node.title,
            "plotType": node.plot_type,
            "storyQuestion": node.story_question,
            "futureDirection": node.future_direction,
            "expectedPayoff": node.expected_payoff,
            "relatedCharacters": node.related_characters,
        }
        revision, content_hash = _revisioned_identity(
            node,
            node_id=node_id,
            payload=_formal_payload(node_id, node, fields),
            previous_confirmed=confirmed_nodes,
            previous_draft=draft_nodes,
        )
        plots.append(
            Plot.model_validate(
                {
                    **_formal_payload(node_id, node, fields),
                    "revision": revision,
                    "contentHash": content_hash,
                }
            )
        )

    volume_ids = {node.id for node in volumes}
    plot_ids = {node.id for node in plots}
    story_blocks: list[StoryBlock] = []
    for block in draft.story_blocks:
        block_id = resolve(block.id or block.client_key or "", "StoryBlock")
        volume_id = resolve(block.volume_ref, "Volume")
        if volume_id not in volume_ids:
            raise PlanningDomainError("StoryBlock volumeRef must name a Volume")
        plot_ids_for_block = tuple(resolve(ref, "Plot") for ref in block.plot_refs)
        if len(plot_ids_for_block) != len(set(plot_ids_for_block)):
            raise PlanningDomainError("duplicate StoryBlock plot relation")
        if not set(plot_ids_for_block).issubset(plot_ids):
            raise PlanningDomainError("StoryBlock plotRefs must name Plots")

        stages: list[Stage] = []
        for stage in block.stages:
            stage_id = resolve(stage.id or stage.client_key or "", "Stage")
            tasks: list[SceneTask] = []
            for task in stage.scene_tasks:
                task_id = resolve(task.id or task.client_key or "", "SceneTask")
                task_fields = {
                    "stageId": stage_id,
                    "order": task.order,
                    "task": task.task,
                    "completionEvidence": task.completion_evidence,
                }
                task_revision, task_hash = _revisioned_identity(
                    task,
                    node_id=task_id,
                    payload=_formal_payload(task_id, task, task_fields),
                    previous_confirmed=confirmed_nodes,
                    previous_draft=draft_nodes,
                )
                tasks.append(
                    SceneTask.model_validate(
                        {
                            **_formal_payload(task_id, task, task_fields),
                            "revision": task_revision,
                            "contentHash": task_hash,
                        }
                    )
                )

            stage_fields = {
                "storyBlockId": block_id,
                "order": stage.order,
                "title": stage.title,
                "purpose": stage.purpose,
                "dramaticQuestion": stage.dramatic_question,
            }
            stage_revision, stage_hash = _revisioned_identity(
                stage,
                node_id=stage_id,
                payload=_formal_payload(stage_id, stage, stage_fields),
                previous_confirmed=confirmed_nodes,
                previous_draft=draft_nodes,
            )
            stages.append(
                Stage.model_validate(
                    {
                        **_formal_payload(stage_id, stage, stage_fields),
                        "revision": stage_revision,
                        "contentHash": stage_hash,
                        "sceneTasks": tuple(tasks),
                    }
                )
            )

        block_fields = {
            "volumeId": volume_id,
            "plotIds": plot_ids_for_block,
            "order": block.order,
            "title": block.title,
            "entrySituation": block.entry_situation,
            "blockGoal": block.block_goal,
            "mainPressure": block.main_pressure,
            "expectedChange": block.expected_change,
            "openQuestions": block.open_questions,
            "involvedCharacters": block.involved_characters,
        }
        block_revision, block_hash = _revisioned_identity(
            block,
            node_id=block_id,
            payload=_formal_payload(block_id, block, block_fields),
            previous_confirmed=confirmed_nodes,
            previous_draft=draft_nodes,
        )
        story_blocks.append(
            StoryBlock.model_validate(
                {
                    **_formal_payload(block_id, block, block_fields),
                    "revision": block_revision,
                    "contentHash": block_hash,
                    "stages": tuple(stages),
                }
            )
        )

    active_story_block_id = (
        resolve(draft.active_story_block_ref, "active StoryBlock")
        if draft.active_story_block_ref is not None
        else None
    )
    block_by_id = {block.id: block for block in story_blocks}
    if active_story_block_id is not None:
        active_block = block_by_id.get(active_story_block_id)
        if active_block is None:
            raise PlanningDomainError("activeStoryBlockRef must name a StoryBlock")
        if active_block.lifecycle != "active":
            raise PlanningDomainError("retired StoryBlock cannot be active")

    normalized_ids = {
        node.id
        for node in (
            list(volumes)
            + list(plots)
            + list(story_blocks)
            + [stage for block in story_blocks for stage in block.stages]
            + [
                task
                for block in story_blocks
                for stage in block.stages
                for task in stage.scene_tasks
            ]
        )
    }
    missing_historical = set(confirmed_nodes) - normalized_ids
    if missing_historical:
        raise PlanningDomainError("previous confirmed historical node cannot disappear")

    aggregate_payload: dict[str, object] = {
        "schemaVersion": "planning-v1",
        "activeStoryBlockId": active_story_block_id,
        "volumes": tuple(volumes),
        "plots": tuple(plots),
        "storyBlocks": tuple(story_blocks),
    }
    content_hash = planning_content_hash(
        PlanningAggregate.model_validate(
            {**aggregate_payload, "contentHash": "0" * 64}
        ).model_dump(mode="json", by_alias=True, exclude={"content_hash"})
    )
    return PlanningAggregate.model_validate(
        {**aggregate_payload, "contentHash": content_hash}
    )


def planning_content_hash(value: Mapping[str, object]) -> str:
    """Hash a canonical Planning payload."""

    return canonical_hash(dict(value))


def validate_confirmable_planning(value: PlanningAggregate) -> None:
    """Reject an incomplete future plan before immutable confirmation."""

    volumes = {node.id: node for node in value.volumes}
    plots = {node.id: node for node in value.plots}
    active_volumes = {key: node for key, node in volumes.items() if node.lifecycle == "active"}
    active_plots = {key: node for key, node in plots.items() if node.lifecycle == "active"}
    blocks = {node.id: node for node in value.story_blocks}
    block = (
        blocks.get(value.active_story_block_id)
        if value.active_story_block_id is not None
        else None
    )
    if block is None or block.lifecycle != "active":
        raise PlanningDomainError("planning is not confirmable")
    if (
        block.volume_id not in volumes
        or volumes[block.volume_id].lifecycle != "active"
        or any(
            plot_id not in plots or plots[plot_id].lifecycle != "active"
            for plot_id in block.plot_ids
        )
    ):
        raise PlanningDomainError(
            "planning is not confirmable: active StoryBlock must reference active nodes"
        )
    if not active_volumes or not active_plots:
        raise PlanningDomainError("planning is not confirmable")
    active_stages = [stage for stage in block.stages if stage.lifecycle == "active"]
    if not active_stages:
        raise PlanningDomainError("planning is not confirmable")
    if not any(
        task.lifecycle == "active"
        for stage in active_stages
        for task in stage.scene_tasks
    ):
        raise PlanningDomainError("planning is not confirmable")


__all__ = (
    "DraftNode",
    "DraftPlanningAggregate",
    "DraftPlot",
    "DraftSceneTask",
    "DraftStage",
    "DraftStoryBlock",
    "DraftVolume",
    "PlanningAggregate",
    "PlanningDomainError",
    "Plot",
    "SceneTask",
    "Stage",
    "StoryBlock",
    "Volume",
    "normalize_planning_aggregate",
    "planning_content_hash",
    "validate_confirmable_planning",
)
