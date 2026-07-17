from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Mapping
from uuid import uuid4

from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import (
    PlanningState,
    SceneTaskView,
    StoryBlockView,
    StoryStageView,
    VolumePlanView,
)


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


class PlanningError(RuntimeError):
    pass


class PlanningNotFound(PlanningError):
    pass


class PlanningRequestInvalid(PlanningError):
    pass


class PlanningPreconditionFailed(PlanningError):
    pass


class PlanningConflict(PlanningError):
    pass


@dataclass(frozen=True)
class CreateInitialPlan:
    project_id: str
    expected_contract_revision: int
    idempotency_key: str


class PlanningService:
    def __init__(self, repository, *, transaction_factory, connection_factory=None):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory

    async def get_state(self, project_id: str) -> PlanningState:
        if self.connection_factory is None:
            raise RuntimeError("Planning read connection is unavailable")
        async with self.connection_factory() as session:
            project = await self.repository.lock_project(session, project_id)
            if project is None:
                raise PlanningNotFound("Project not found")
            head = await self.repository.read_contract_head(session, project_id)
            plan = await self.repository.read_current_plan(session, project_id)
            return self._state_from_plan(project_id, head, plan)

    async def create_initial_plan(self, command: CreateInitialPlan) -> PlanningState:
        self._validate_command(command)
        async with self.transaction_factory() as session:
            project = await self.repository.lock_project(session, command.project_id)
            if project is None:
                raise PlanningNotFound("Project not found")
            existing = await self.repository.read_current_plan(session, command.project_id)
            head = await self.repository.read_contract_head(session, command.project_id)
            if existing is not None:
                self._require_contract_revision(head, command.expected_contract_revision)
                return self._state_from_plan(command.project_id, head, existing)
            self._require_contract_revision(head, command.expected_contract_revision)
            creation = await self.repository.read_creation_contract(
                session, head["creation_contract_id"],
            )
            if creation is None:
                raise PlanningPreconditionFailed("confirmed contract payload is missing")
            seed = await self.repository.read_selected_seed(session, command.project_id)
            bundle = self._initial_bundle(
                project=project,
                head=head,
                creation_contract=creation,
                selected_seed=seed or {},
            )
            inserted = await self.repository.insert_initial_plan(session, bundle)
            if not inserted:
                raise PlanningConflict("Planning write did not create the initial plan")
            return self._state_from_plan(command.project_id, head, bundle)

    def _validate_command(self, command: CreateInitialPlan) -> None:
        if not command.project_id:
            raise PlanningRequestInvalid("project_id is required")
        if command.expected_contract_revision < 1:
            raise PlanningRequestInvalid("expected contract revision is required")
        if _IDEMPOTENCY_KEY.fullmatch(command.idempotency_key or "") is None:
            raise PlanningRequestInvalid("idempotency key is invalid")

    def _require_contract_revision(
        self, head: Mapping[str, Any] | None, expected_revision: int,
    ) -> None:
        if not head or int(head.get("revision") or 0) < 1:
            raise PlanningPreconditionFailed("confirmed contract is required")
        if int(head.get("revision") or 0) != expected_revision:
            raise PlanningConflict("contract revision drift")
        if head.get("contract_ready") is False:
            raise PlanningPreconditionFailed("confirmed contract is not ready")

    def _initial_bundle(
        self,
        *,
        project: Mapping[str, Any],
        head: Mapping[str, Any],
        creation_contract: Mapping[str, Any],
        selected_seed: Mapping[str, Any],
    ) -> dict[str, Any]:
        now = int(time.time() * 1000)
        project_id = str(project["id"])
        content = self._json_object(creation_contract.get("content_json"))
        seed_payload = self._json_object(selected_seed.get("payload_json"))
        story_engine = self._json_object(
            content.get("selectedEngine") or content.get("storyEngine")
        )
        capacity = self._capacity(content.get("chapterCapacityPolicy"))
        engine_name = self._clean(story_engine.get("name")) or "本书主线"
        promise = self._clean(story_engine.get("storyPromise")) or "把选定故事承诺落到具体人物选择、阻力和后果。"
        protagonist = self._clean(seed_payload.get("protagonist")) or "主角"
        pressure = self._clean(seed_payload.get("coreConflict")) or promise
        hook = self._clean(seed_payload.get("openingHook")) or "以一个可见问题打开局面。"
        volume_payload = {
            "schemaVersion": "volume-plan-v1",
            "contractRevision": int(head["revision"]),
            "direction": f"{engine_name}：先把核心承诺落到第一段连续剧情。",
            "longTermPromise": promise,
            "readerExperience": "故事优先，具体行动、人物选择和现实后果优先。",
        }
        block_payload = {
            "schemaVersion": "story-block-v1",
            "contractRevision": int(head["revision"]),
            "goal": f"{protagonist}从{hook}入局，第一次证明典籍知识能改变局面，同时付出代价。",
            "entrySituation": hook,
            "mainPressure": pressure,
            "involvedCharacters": [protagonist],
            "openQuestions": ["典籍知识的收益、代价和觊觎者需要在行动中显形。"],
            "chapterCapacity": capacity,
        }
        stage_payloads = (
            {
                "schemaVersion": "story-stage-v1",
                "purpose": "入局与误判",
                "dramaticQuestion": "主角能否把看似无用的知识变成可见行动？",
                "naturalContinuation": "允许跨章延续，不强制本章完成。",
            },
            {
                "schemaVersion": "story-stage-v1",
                "purpose": "试用与代价",
                "dramaticQuestion": "第一次成功会引来什么误会、利益冲突或新压力？",
                "naturalContinuation": "根据章节容量领取任务，未完成项滚入下一章。",
            },
            {
                "schemaVersion": "story-stage-v1",
                "purpose": "后果与转向",
                "dramaticQuestion": "人物关系和局势如何因这次选择发生可追踪变化？",
                "naturalContinuation": "块目标自然完成、失败或转向时再关闭。",
            },
        )
        task_payloads = (
            {
                "schemaVersion": "scene-task-v1",
                "stageOrder": 1,
                "task": "用一个具体麻烦开场，让主角必须做选择，而不是解释设定。",
                "acceptance": "读者能看见问题、人物立场和行动压力。",
            },
            {
                "schemaVersion": "scene-task-v1",
                "stageOrder": 1,
                "task": "让典籍知识通过行动产生效果，同时暴露局限或成本。",
                "acceptance": "知识不是说明书，而是改变局面的工具。",
            },
            {
                "schemaVersion": "scene-task-v1",
                "stageOrder": 2,
                "task": "安排至少一个配角因自身目的推动或阻碍主角。",
                "acceptance": "配角不是陪衬，有独立欲望和判断。",
            },
            {
                "schemaVersion": "scene-task-v1",
                "stageOrder": 3,
                "task": "留下一个自然未解决项，交给后续故事块或下一章延续。",
                "acceptance": "不硬塞钩子，不机械清零。",
            },
        )
        manifest_hash = canonical_hash({
            "contractRevision": int(head["revision"]),
            "volume": volume_payload,
            "block": block_payload,
            "stages": list(stage_payloads),
            "sceneTasks": list(task_payloads),
        })
        volume_id = str(uuid4())
        block_id = str(uuid4())
        stage_ids = [str(uuid4()) for _ in stage_payloads]
        return {
            "manifest_hash": manifest_hash,
            "volume": {
                "id": volume_id, "project_id": project_id, "volume_num": 1,
                "title": "第一卷 山河初启", "payload": volume_payload,
                "revision": 1, "status": "active",
                "created_at": now, "updated_at": now,
            },
            "block": {
                "id": block_id, "project_id": project_id, "volume_plan_id": volume_id,
                "block_num": 1, "title": engine_name, "payload": block_payload,
                "revision": 1, "status": "active",
                "created_at": now, "updated_at": now,
            },
            "stages": tuple({
                "id": stage_id, "project_id": project_id, "story_block_id": block_id,
                "stage_order": index, "title": payload["purpose"],
                "payload": payload, "revision": 1,
                "status": "in_progress" if index == 1 else "pending",
                "created_at": now, "updated_at": now,
            } for index, (stage_id, payload) in enumerate(zip(stage_ids, stage_payloads), start=1)),
            "scene_tasks": tuple({
                "id": str(uuid4()), "project_id": project_id,
                "story_stage_id": stage_ids[int(payload["stageOrder"]) - 1],
                "task_order": index, "payload": payload, "revision": 1,
                "status": "pending", "created_at": now, "updated_at": now,
            } for index, payload in enumerate(task_payloads, start=1)),
        }

    def _state_from_plan(
        self,
        project_id: str,
        head: Mapping[str, Any] | None,
        plan: Mapping[str, Any] | None,
    ) -> PlanningState:
        contract_revision = int((head or {}).get("revision") or 0)
        if plan is None:
            return PlanningState(
                project_id=project_id, has_planning=False,
                contract_revision=contract_revision, active_volume=None,
                active_block=None, stages=(), scene_tasks=(), manifest_hash=None,
            )
        volume = plan["volume"]
        block = plan["block"]
        stages = tuple(plan.get("stages") or ())
        tasks = tuple(plan.get("scene_tasks") or ())
        return PlanningState(
            project_id=project_id, has_planning=True,
            contract_revision=contract_revision,
            active_volume=VolumePlanView(
                id=volume["id"], project_id=volume["project_id"],
                volume_num=int(volume["volume_num"]), title=volume["title"],
                direction=volume["payload"], revision=int(volume["revision"]),
                status=volume["status"],
            ),
            active_block=StoryBlockView(
                id=block["id"], project_id=block["project_id"],
                volume_plan_id=block["volume_plan_id"],
                block_num=int(block["block_num"]), title=block["title"],
                goal=block["payload"], revision=int(block["revision"]),
                status=block["status"],
            ),
            stages=tuple(StoryStageView(
                id=stage["id"], project_id=stage["project_id"],
                story_block_id=stage["story_block_id"],
                stage_order=int(stage["stage_order"]), title=stage["title"],
                plan=stage["payload"], revision=int(stage["revision"]),
                status=stage["status"],
            ) for stage in stages),
            scene_tasks=tuple(SceneTaskView(
                id=task["id"], project_id=task["project_id"],
                story_stage_id=task["story_stage_id"],
                task_order=int(task["task_order"]), task=task["payload"],
                revision=int(task["revision"]), status=task["status"],
            ) for task in tasks),
            manifest_hash=plan.get("manifest_hash"),
        )

    def _json_object(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return loaded if isinstance(loaded, dict) else {}
        return {}

    def _capacity(self, value: Any) -> dict[str, int]:
        data = self._json_object(value)
        return {
            "targetMin": int(data.get("targetMin") or 3500),
            "targetMax": int(data.get("targetMax") or 4500),
            "softCeiling": int(data.get("softCeiling") or 5200),
        }

    def _clean(self, value: Any) -> str:
        return str(value or "").strip()
