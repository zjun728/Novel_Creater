from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.planning import PlanningAggregate
from backend.routers import planning
from backend.security.redaction import install_error_handlers
from backend.services.planning import (
    PlanningConflict as ServicePlanningConflict,
    PlanningArchived as ServicePlanningArchived,
    PlanningCapabilities,
    PlanningDraftResult,
    PlanningHeadResult,
    PlanningNotFound,
    PlanningPreconditionFailed as ServicePlanningPreconditionFailed,
    PlanningRequestInvalid as ServicePlanningRequestInvalid,
    PlanningRevisionResult,
    PlanningState,
)


HASH = "a" * 64
NEXT_HASH = "b" * 64


def aggregate(content_hash: str = HASH) -> PlanningAggregate:
    return PlanningAggregate.model_validate(
        {
            "schemaVersion": "planning-v1",
            "activeStoryBlockId": None,
            "volumes": [],
            "plots": [],
            "storyBlocks": [],
            "contentHash": content_hash,
        }
    )


def draft(project_id: str = "p1") -> PlanningDraftResult:
    return PlanningDraftResult(
        project_id=project_id,
        draft_id="draft-1",
        base_head_revision=0,
        draft_revision=1,
        content_hash=HASH,
        content=aggregate(),
        status="active",
        capacity_policy={
            "targetMin": 3000,
            "targetMax": 5000,
            "softCeiling": 5000,
        },
    )


def revision(project_id: str = "p1") -> PlanningRevisionResult:
    return PlanningRevisionResult(
        project_id=project_id,
        planning_revision_id="planning-revision-1",
        revision=1,
        parent_revision=0,
        content_hash=NEXT_HASH,
        content=aggregate(NEXT_HASH),
    )


def state(project_id: str = "p1", *, archived: bool = False) -> PlanningState:
    return PlanningState(
        project_id=project_id,
        basis_status="current",
        head=PlanningHeadResult(
            revision=0,
            planning_revision_id=None,
            content_hash=None,
        ),
        draft=None,
        future_plan=None,
        actual_progress=(),
        canon_projection_status={
            "canonRevision": 3,
            "projectionRevision": 3,
            "contentHash": "c" * 64,
            "synchronized": True,
        },
        capacity_policy={
            "targetMin": 3000,
            "targetMax": 5000,
            "softCeiling": 5000,
        },
        capabilities=PlanningCapabilities(
            view=True,
            edit=not archived,
            confirm=False,
            generate=False,
        ),
        archived=archived,
    )


class FakePlanningService:
    def __init__(self):
        self.commands = []
        self.current_state = state()
        self.failure: Exception | None = None

    def _raise(self):
        if self.failure is not None:
            raise self.failure

    async def get_state(self, project_id):
        self._raise()
        assert project_id == "p1"
        return self.current_state

    async def history(self, project_id):
        self._raise()
        assert project_id == "p1"
        return (revision(),)

    async def create_draft(self, command):
        self._raise()
        self.commands.append(command)
        return draft(command.project_id)

    async def save_draft(self, command):
        self._raise()
        self.commands.append(command)
        return replace(
            draft(command.project_id),
            draft_revision=2,
            content_hash=NEXT_HASH,
            content=aggregate(NEXT_HASH),
        )

    async def confirm_draft(self, command):
        self._raise()
        self.commands.append(command)
        return revision(command.project_id)


def make_client():
    service = FakePlanningService()
    app = FastAPI()
    app.include_router(planning.router, prefix="/api")
    app.dependency_overrides[planning.get_planning_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_state_and_history_are_explicit_camel_case_public_dtos():
    client, _ = make_client()

    current = client.get("/api/projects/p1/planning")
    history = client.get("/api/projects/p1/planning/history")

    assert current.status_code == history.status_code == 200
    assert current.json() == {
        "projectId": "p1",
        "basisStatus": "current",
        "head": {
            "revision": 0,
            "planningRevisionId": None,
            "contentHash": None,
        },
        "draft": None,
        "futurePlan": None,
        "actualProgress": [],
        "canonProjectionStatus": {
            "canonRevision": 3,
            "projectionRevision": 3,
            "contentHash": "c" * 64,
            "synchronized": True,
        },
        "capacityPolicy": {
            "targetMin": 3000,
            "targetMax": 5000,
            "softCeiling": 5000,
        },
        "capabilities": {
            "view": True,
            "edit": True,
            "confirm": False,
            "generate": False,
        },
    }
    assert history.json() == {
        "items": [
            {
                "projectId": "p1",
                "planningRevisionId": "planning-revision-1",
                "revision": 1,
                "parentRevision": 0,
                "contentHash": NEXT_HASH,
                "content": {
                    "schemaVersion": "planning-v1",
                    "activeStoryBlockId": None,
                    "volumes": [],
                    "plots": [],
                    "storyBlocks": [],
                    "contentHash": NEXT_HASH,
                },
            }
        ]
    }


def test_create_save_and_confirm_use_revisioned_service_commands():
    client, service = make_client()
    content = {
        "activeStoryBlockRef": None,
        "volumes": [],
        "plots": [],
        "storyBlocks": [],
    }

    created = client.post(
        "/api/projects/p1/planning/drafts",
        json={"idempotencyKey": "create-draft-1"},
    )
    saved = client.put(
        "/api/projects/p1/planning/drafts/draft-1",
        json={
            "expectedDraftRevision": 1,
            "expectedDraftHash": HASH,
            "content": content,
            "idempotencyKey": "save-draft-1",
        },
    )
    confirmed = client.post(
        "/api/projects/p1/planning/drafts/draft-1/confirm",
        json={
            "expectedDraftRevision": 2,
            "expectedDraftHash": NEXT_HASH,
            "idempotencyKey": "confirm-draft-1",
        },
    )

    assert created.status_code == 201
    assert created.json()["draftId"] == "draft-1"
    assert saved.status_code == 200
    assert saved.json()["draftRevision"] == 2
    assert confirmed.status_code == 201
    assert confirmed.json()["revision"] == 1
    assert service.commands[0].project_id == "p1"
    assert service.commands[0].idempotency_key == "create-draft-1"
    assert service.commands[1].draft_id == "draft-1"
    assert service.commands[1].expected_revision == 1
    assert service.commands[1].expected_hash == HASH
    assert service.commands[1].content == content
    assert service.commands[2].expected_draft_revision == 2
    assert service.commands[2].expected_draft_hash == NEXT_HASH


@pytest.mark.parametrize(
    ("method", "path", "body"),
    (
        (
            "post",
            "/api/projects/p1/planning/drafts",
            {"idempotencyKey": "create-draft-1", "unexpected": True},
        ),
        (
            "put",
            "/api/projects/p1/planning/drafts/draft-1",
            {
                "expectedDraftRevision": 1,
                "expectedDraftHash": HASH,
                "content": {
                    "activeStoryBlockRef": None,
                    "volumes": [],
                    "plots": [],
                    "storyBlocks": [],
                },
                "idempotencyKey": "save-draft-1",
                "unexpected": True,
            },
        ),
        (
            "post",
            "/api/projects/p1/planning/drafts/draft-1/confirm",
            {
                "expectedDraftRevision": 1,
                "expectedDraftHash": HASH,
                "idempotencyKey": "confirm-draft-1",
                "unexpected": True,
            },
        ),
    ),
)
def test_every_planning_request_body_forbids_unknown_fields(
    method, path, body
):
    client, _ = make_client()

    response = getattr(client, method)(path, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"


def test_nested_planning_content_is_also_strict():
    client, _ = make_client()

    response = client.put(
        "/api/projects/p1/planning/drafts/draft-1",
        json={
            "expectedDraftRevision": 1,
            "expectedDraftHash": HASH,
            "content": {
                "activeStoryBlockRef": None,
                "volumes": [],
                "plots": [],
                "storyBlocks": [],
                "unexpected": True,
            },
            "idempotencyKey": "save-draft-1",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"


def test_deepest_scene_task_content_forbids_unknown_fields():
    client, _ = make_client()
    content = {
        "activeStoryBlockRef": "block",
        "volumes": [
            {
                "clientNodeKey": "volume",
                "order": 1,
                "title": "第一卷",
                "coreChange": "站稳脚跟",
                "mainPressure": "追兵迫近",
                "ensembleFocus": ["主角"],
                "forbiddenEvents": [],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "plot",
                "order": 1,
                "title": "立足",
                "plotType": "main",
                "storyQuestion": "如何脱险",
                "futureDirection": "转守为攻",
                "expectedPayoff": "建立据点",
                "relatedCharacters": ["主角"],
            }
        ],
        "storyBlocks": [
            {
                "clientNodeKey": "block",
                "order": 1,
                "title": "夜渡",
                "volumeRef": "volume",
                "plotRefs": ["plot"],
                "entrySituation": "受困",
                "blockGoal": "穿过封锁",
                "mainPressure": "追兵合围",
                "expectedChange": "建立信任",
                "openQuestions": [],
                "involvedCharacters": ["主角"],
                "stages": [
                    {
                        "clientNodeKey": "stage",
                        "order": 1,
                        "title": "找缺口",
                        "purpose": "观察换岗",
                        "dramaticQuestion": "能否及时脱身",
                        "sceneTasks": [
                            {
                                "clientNodeKey": "task",
                                "order": 1,
                                "task": "记录巡逻",
                                "completionEvidence": "获得换岗间隔",
                                "unexpected": True,
                            }
                        ],
                    }
                ],
            }
        ],
    }

    response = client.put(
        "/api/projects/p1/planning/drafts/draft-1",
        json={
            "expectedDraftRevision": 1,
            "expectedDraftHash": HASH,
            "content": content,
            "idempotencyKey": "save-draft-1",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"


@pytest.mark.parametrize(
    "raw_body",
    (
        "",
        '{"idempotencyKey":',
        "null",
    ),
)
def test_empty_malformed_and_null_json_use_fixed_request_error(raw_body):
    client, _ = make_client()

    response = client.post(
        "/api/projects/p1/planning/drafts",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"
    assert set(response.json()) == {"code", "message", "correlationId"}


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    (
        (
            ServicePlanningRequestInvalid("bad request"),
            422,
            "PlanningRequestInvalid",
        ),
        (
            PlanningNotFound("missing"),
            404,
            "PlanningResourceNotFound",
        ),
        (
            ServicePlanningPreconditionFailed("stale basis"),
            412,
            "PlanningPreconditionFailed",
        ),
        (
            ServicePlanningConflict("CAS conflict"),
            409,
            "PlanningConflict",
        ),
        (
            ServicePlanningArchived("archived"),
            409,
            "PlanningArchived",
        ),
    ),
)
def test_service_errors_map_to_fixed_public_codes(failure, status_code, code):
    client, service = make_client()
    service.failure = failure

    response = client.get("/api/projects/p1/planning")

    assert response.status_code == status_code
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["message"]


def test_archived_state_is_readable_but_exposes_no_write_capabilities():
    client, service = make_client()
    service.current_state = state(archived=True)

    response = client.get("/api/projects/p1/planning")

    assert response.status_code == 200
    assert response.json()["capabilities"] == {
        "view": True,
        "edit": False,
        "confirm": False,
        "generate": False,
    }


def test_retired_initial_route_is_not_part_of_the_public_contract():
    client, _ = make_client()

    response = client.post(
        "/api/projects/p1/planning/initial",
        json={"idempotencyKey": "old"},
    )

    assert response.status_code == 404


def test_public_responses_do_not_leak_internal_or_provider_fields():
    client, service = make_client()
    service.current_state = replace(state(), draft=draft())

    responses = [
        client.get("/api/projects/p1/planning"),
        client.get("/api/projects/p1/planning/history"),
        client.post(
            "/api/projects/p1/planning/drafts",
            json={"idempotencyKey": "create-draft-1"},
        ),
    ]
    forbidden = {
        "project_id",
        "planning_revision_id",
        "content_hash",
        "prompt",
        "rawOutput",
        "providerId",
        "providerName",
        "apiKey",
        "sql",
    }
    for response in responses:
        assert response.status_code in {200, 201}
        text = response.text
        for name in forbidden:
            assert name not in text
