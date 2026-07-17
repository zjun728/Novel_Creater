from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.planning import (
    PlanningState,
    SceneTaskView,
    StoryBlockView,
    StoryStageView,
    VolumePlanView,
)
from backend.routers import planning
from backend.security.redaction import install_error_handlers


class FakePlanningService:
    def __init__(self):
        self.commands = []
        self.state = PlanningState(
            project_id="p1",
            has_planning=True,
            contract_revision=1,
            active_volume=VolumePlanView(
                id="volume-1", project_id="p1", volume_num=1,
                title="第一卷 山河初启",
                direction={"direction": "典籍入山河"},
                revision=1, status="active",
            ),
            active_block=StoryBlockView(
                id="block-1", project_id="p1", volume_plan_id="volume-1",
                block_num=1, title="典籍入山河",
                goal={
                    "goal": "让主角入局",
                    "chapterCapacity": {
                        "targetMin": 3500,
                        "targetMax": 4500,
                        "softCeiling": 5200,
                    },
                },
                revision=1, status="active",
            ),
            stages=(
                StoryStageView(
                    id="stage-1", project_id="p1", story_block_id="block-1",
                    stage_order=1, title="入局与误判",
                    plan={"purpose": "入局与误判"},
                    revision=1, status="in_progress",
                ),
            ),
            scene_tasks=(
                SceneTaskView(
                    id="task-1", project_id="p1", story_stage_id="stage-1",
                    task_order=1, task={"task": "具体麻烦开场"},
                    revision=1, status="pending",
                ),
            ),
            manifest_hash="a" * 64,
        )

    async def get_state(self, project_id):
        assert project_id == "p1"
        return self.state

    async def create_initial_plan(self, command):
        self.commands.append(command)
        return self.state


def make_client():
    service = FakePlanningService()
    app = FastAPI()
    app.include_router(planning.router, prefix="/api")
    app.dependency_overrides[planning.get_planning_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_planning_routes_return_public_state_and_accept_explicit_initial_create():
    client, service = make_client()

    read = client.get("/api/projects/p1/planning")
    created = client.post("/api/projects/p1/planning/initial", json={
        "expectedContractRevision": 1,
        "idempotencyKey": "m3-route-test",
    })

    assert read.status_code == 200
    assert created.status_code == 201
    body = created.json()
    assert body["hasPlanning"] is True
    assert body["planningReady"] is True
    assert body["contractRevision"] == 1
    assert body["activeBlock"]["goal"]["chapterCapacity"]["targetMax"] == 4500
    assert "targetChapterCount" not in body["activeBlock"]["goal"]
    assert body["stages"][0]["status"] == "in_progress"
    assert body["sceneTasks"][0]["status"] == "pending"
    assert service.commands[0].expected_contract_revision == 1
    assert service.commands[0].idempotency_key == "m3-route-test"


def test_planning_routes_reject_unknown_fields():
    client, _ = make_client()

    response = client.post("/api/projects/p1/planning/initial", json={
        "expectedContractRevision": 1,
        "idempotencyKey": "m3-route-test",
        "unexpected": True,
    })

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"
