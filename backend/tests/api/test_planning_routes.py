from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.planning import PlanningAggregate
from backend.domain.routers import planning
from backend.security.redaction import install_error_handlers
from backend.services.planning import (
    PlanningConflict as ServicePlanningConflict,
    PlanningArchived as ServicePlanningArchived,
    PlanningCapabilities,
    ActualProgressResult,
    PlanningDraftResult,
    PlanningHeadResult,
    PlanningNotFound,
    PlanningPreconditionFailed as ServicePlanningPreconditionFailed,
    PlanningRequestInvalid as ServicePlanningRequestInvalid,
    PlanningRevisionResult,
    PlanningState,
)
from backend.services.planning_generation import (
    GeneratePlanningDraft,
    PlanningGenerationOperationNotFound,
    PlanningOperationResult,
    PublicModelSummary,
)


HASH = "a" * 64
NEXT_HASH = "b" * 64
SENSITIVE_PLANNING_KEYS = (
    "sk-TestSentinel123456",
    "sk_TestSentinel123456",
    "ghp_TestSentinel12345678901234567890",
    "gho_TestSentinel12345678901234567890",
    "ghu_TestSentinel12345678901234567890",
    "ghs_TestSentinel12345678901234567890",
    "ghr_TestSentinel12345678901234567890",
    "github_pat_TestSentinel1234567890",
    "AKIAABCDEFGHIJKLMNOP",
    "ASIA1234567890ABCDEF",
    "AIzaTestSentinel12345678901234567890123",
    "Authorization-Bearer-TestSentinel",
    "bearer.TestSentinel",
    "apiKey-TestSentinel",
    "api_key.TestSentinel",
    "access-token-TestSentinel",
    "TOKEN-TestSentinel",
    "planning.secret.attempt",
    "PASSWORD:TestSentinel",
    "passwd-TestSentinel",
    "credential_TestSentinel",
    "DSN.TestSentinel",
    "planning%2Dencoded",
)


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
        display_status="current",
        display_reason="currentPlanningHead",
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


class FakePlanningGenerationService:
    def __init__(self):
        self.commands = []
        self.key_queries = []
        self.failure: Exception | None = None
        self.result = PlanningOperationResult(
            operation_id="operation-1",
            status="succeeded",
            failure_code=None,
            model=PublicModelSummary(
                provider_id="provider-1",
                model_name="deepseek-v4-flash",
            ),
            loaded=True,
            loaded_draft_revision=2,
        )

    def _raise(self):
        if self.failure is not None:
            raise self.failure

    async def generate(self, command):
        self._raise()
        self.commands.append(command)
        return self.result

    async def get_operation(self, project_id, operation_id):
        self._raise()
        assert (project_id, operation_id) == ("p1", "operation-1")
        return self.result

    async def get_operation_by_key(self, project_id, idempotency_key):
        self._raise()
        self.key_queries.append((project_id, idempotency_key))
        return self.result


def make_client():
    service = FakePlanningService()
    generation_service = FakePlanningGenerationService()
    app = FastAPI()
    app.include_router(planning.router, prefix="/api")
    app.dependency_overrides[planning.get_planning_service] = lambda: service
    app.dependency_overrides[
        planning.get_planning_generation_service
    ] = lambda: generation_service
    install_error_handlers(app)
    return (
        TestClient(app, raise_server_exceptions=False),
        service,
        generation_service,
    )


def test_state_and_history_are_explicit_camel_case_public_dtos():
    client, _, _ = make_client()

    current = client.get("/api/projects/p1/planning")
    history = client.get("/api/projects/p1/planning/history")

    assert current.status_code == history.status_code == 200
    assert current.json() == {
        "projectId": "p1",
        "basisStatus": "current",
        "projectLifecycle": "active",
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
                "displayStatus": "current",
                "displayReason": "currentPlanningHead",
            }
        ]
    }


def test_state_serializes_only_the_closed_actual_progress_dto():
    client, service, _ = make_client()
    service.current_state = replace(
        service.current_state,
        actual_progress=(
            ActualProgressResult(
                revision_number=1,
                subject_key="global",
                entity_id=None,
                field_path="plot.gunpowder",
                value={"status": "推进"},
                content_hash=HASH,
            ),
        ),
    )

    response = client.get("/api/projects/p1/planning")

    assert response.status_code == 200
    assert response.json()["actualProgress"] == [
        {
            "revisionNumber": 1,
            "subjectKey": "global",
            "entityId": None,
            "fieldPath": "plot.gunpowder",
            "value": {"status": "推进"},
            "contentHash": HASH,
        }
    ]


def test_state_does_not_leak_runtime_actual_progress_mapping_extras():
    class LeakyActualProgress(dict):
        def __init__(self):
            super().__init__(
                revisionNumber=1,
                subjectKey="global",
                entityId=None,
                fieldPath="plot.gunpowder",
                value={"status": "推进"},
                contentHash=HASH,
                internalSecret="must-not-cross-public-boundary",
                extraKey="must-not-cross-public-boundary",
            )
            self.revision_number = 1
            self.subject_key = "global"
            self.entity_id = None
            self.field_path = "plot.gunpowder"
            self.value = {"status": "推进"}
            self.content_hash = HASH

    client, service, _ = make_client()
    service.current_state = replace(
        service.current_state,
        actual_progress=(LeakyActualProgress(),),
    )

    response = client.get("/api/projects/p1/planning")

    assert response.status_code == 200
    assert response.json()["actualProgress"] == [
        {
            "revisionNumber": 1,
            "subjectKey": "global",
            "entityId": None,
            "fieldPath": "plot.gunpowder",
            "value": {"status": "推进"},
            "contentHash": HASH,
        }
    ]


def test_planning_router_has_no_actual_progress_mutation_path():
    routes = {
        (method, route.path)
        for route in planning.router.routes
        for method in route.methods
    }
    forbidden = ("complete", "progress", "mark", "sync-memory", "rebuild")

    assert not [
        (method, path)
        for method, path in routes
        if method not in {"GET", "HEAD", "OPTIONS"}
        and any(token in path for token in forbidden)
    ]


def test_create_save_and_confirm_use_revisioned_service_commands():
    client, service, _ = make_client()
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
    assert set(confirmed.json()) == {
        "projectId",
        "planningRevisionId",
        "revision",
        "parentRevision",
        "contentHash",
        "content",
    }
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
    client, _, _ = make_client()

    response = getattr(client, method)(path, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"


def test_nested_planning_content_is_also_strict():
    client, _, _ = make_client()

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


@pytest.mark.parametrize(
    "content",
    (
        {
            "active_story_block_ref": None,
            "volumes": [],
            "plots": [],
            "storyBlocks": [],
        },
        {
            "activeStoryBlockRef": None,
            "volumes": [],
            "plots": [],
            "story_blocks": [],
        },
    ),
)
def test_planning_api_rejects_nested_python_field_names(content):
    client, _, _ = make_client()

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


def test_deepest_scene_task_content_forbids_unknown_fields():
    client, _, _ = make_client()
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
    client, _, _ = make_client()

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
    client, service, _ = make_client()
    service.failure = failure

    response = client.get("/api/projects/p1/planning")

    assert response.status_code == status_code
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["message"]


def test_archived_state_is_readable_but_exposes_no_write_capabilities():
    client, service, _ = make_client()
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
    client, _, _ = make_client()

    response = client.post(
        "/api/projects/p1/planning/initial",
        json={"idempotencyKey": "old"},
    )

    assert response.status_code == 404


def test_public_responses_do_not_leak_internal_or_provider_fields():
    client, service, _ = make_client()
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


def test_generate_and_get_operation_use_safe_explicit_contract():
    client, _, generation = make_client()

    generated = client.post(
        "/api/projects/p1/planning/drafts/draft-1/generate",
        json={
            "draftRevision": 1,
            "draftHash": HASH,
            "idempotencyKey": "generate-planning-1",
            "authorInstructions": "强化群像变化。",
        },
    )
    queried = client.get(
        "/api/projects/p1/planning/operations/operation-1"
    )
    recovered = client.get(
        "/api/projects/p1/planning/operations/by-idempotency-key/"
        "generate-planning-1"
    )

    assert generated.status_code == queried.status_code == recovered.status_code == 200
    expected = {
        "operationId": "operation-1",
        "status": "succeeded",
        "failureCode": None,
        "model": {
            "providerId": "provider-1",
            "modelName": "deepseek-v4-flash",
        },
        "loaded": True,
        "loadedDraftRevision": 2,
    }
    assert generated.json() == queried.json() == recovered.json() == expected
    assert generation.key_queries == [("p1", "generate-planning-1")]
    assert generation.commands == [
        GeneratePlanningDraft(
            project_id="p1",
            draft_id="draft-1",
            draft_revision=1,
            draft_hash=HASH,
            idempotency_key="generate-planning-1",
            author_instructions="强化群像变化。",
        )
    ]


@pytest.mark.parametrize(
    "unsafe_key",
    (
        "x" * 65,
        "bad%25key",
        "bad%20key",
        "bad$key",
    ),
)
def test_operation_by_key_rejects_invalid_keys_with_fixed_error(unsafe_key):
    client, _, generation = make_client()

    response = client.get(
        "/api/projects/p1/planning/operations/by-idempotency-key/"
        f"{unsafe_key}"
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"
    assert generation.key_queries == []
    assert unsafe_key not in response.text


def test_operation_by_key_not_found_is_fixed_safe_404():
    client, _, generation = make_client()
    generation.failure = PlanningGenerationOperationNotFound()

    response = client.get(
        "/api/projects/p1/planning/operations/by-idempotency-key/"
        "missing-key"
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": "PlanningGenerationOperationNotFound",
        "message": "Planning generation operation not found",
        "correlationId": response.json()["correlationId"],
    }
    assert "missing-key" not in response.text


def test_generation_routes_reject_sensitive_keys_before_service_calls():
    for key in SENSITIVE_PLANNING_KEYS:
        client, _, generation = make_client()
        generated = client.post(
            "/api/projects/p1/planning/drafts/draft-1/generate",
            json={
                "draftRevision": 1,
                "draftHash": HASH,
                "idempotencyKey": key,
                "authorInstructions": "",
            },
        )
        path_key = key.replace("%", "%2525")
        recovered = client.get(
            "/api/projects/p1/planning/operations/by-idempotency-key/"
            f"{path_key}"
        )

        for response in (generated, recovered):
            assert response.status_code == 422
            assert response.json()["code"] == "PlanningRequestInvalid"
            assert key not in response.text
            assert "TestSentinel" not in response.text
        assert generation.commands == []
        assert generation.key_queries == []


def test_generation_routes_keep_the_ordinary_closed_key_contract():
    for key in (
        "planning-2026.07:attempt_1",
        "123e4567-e89b-12d3-a456-426614174000",
    ):
        client, _, generation = make_client()

        recovered = client.get(
            "/api/projects/p1/planning/operations/by-idempotency-key/"
            f"{key}"
        )

        assert recovered.status_code == 200
        assert generation.key_queries == [("p1", key)]


@pytest.mark.parametrize(
    "extra",
    (
        {"provider": "forbidden"},
        {"model": "forbidden"},
        {"prompt": "forbidden"},
        {"rawOutput": "forbidden"},
        {"manifest": {"forbidden": True}},
        {"apiKey": "sk-forbidden"},
    ),
)
def test_generate_body_rejects_every_internal_or_secret_field(extra):
    client, _, generation = make_client()
    body = {
        "draftRevision": 1,
        "draftHash": HASH,
        "idempotencyKey": "generate-planning-1",
        "authorInstructions": "",
        **extra,
    }

    response = client.post(
        "/api/projects/p1/planning/drafts/draft-1/generate",
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"
    assert generation.commands == []


def test_generate_body_bounds_author_instructions():
    client, _, generation = make_client()

    response = client.post(
        "/api/projects/p1/planning/drafts/draft-1/generate",
        json={
            "draftRevision": 1,
            "draftHash": HASH,
            "idempotencyKey": "generate-planning-1",
            "authorInstructions": "x" * 4001,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PlanningRequestInvalid"
    assert generation.commands == []


def test_operation_response_drops_runtime_and_raw_provider_data():
    client, _, generation = make_client()
    generation.result = replace(
        generation.result,
        status="failed",
        failure_code="PlanningProviderFailed",
        loaded=False,
        loaded_draft_revision=None,
    )

    response = client.get(
        "/api/projects/p1/planning/operations/operation-1"
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "operationId",
        "status",
        "failureCode",
        "model",
        "loaded",
        "loadedDraftRevision",
    }
    text = response.text
    for forbidden in (
        "apiKey",
        "prompt",
        "rawOutput",
        "manifest",
        "baseUrl",
        "dsn",
    ):
        assert forbidden not in text


def test_operation_response_replaces_unknown_failure_code_with_safe_category():
    client, _, generation = make_client()
    generation.result = replace(
        generation.result,
        status="failed",
        failure_code="sk-private-runtime-detail",
        loaded=False,
        loaded_draft_revision=None,
    )

    response = client.get(
        "/api/projects/p1/planning/operations/operation-1"
    )

    assert response.status_code == 200
    assert response.json()["failureCode"] == "PlanningGenerationFailed"
    assert "sk-private-runtime-detail" not in response.text


def test_operation_response_closes_status_to_the_four_public_states():
    client, _, generation = make_client()
    generation.result = replace(
        generation.result,
        status="sk-private-runtime-status",
        failure_code=None,
        loaded=False,
        loaded_draft_revision=None,
    )

    response = client.get(
        "/api/projects/p1/planning/operations/operation-1"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["failureCode"] == "PlanningGenerationFailed"
    assert "sk-private-runtime-status" not in response.text


def test_get_operation_fail_closes_entire_model_for_credential_dsn():
    client, _, generation = make_client()
    credential_dsn = "mysql://root:private@database.example/novel"
    generation.result = replace(
        generation.result,
        model=PublicModelSummary(
            provider_id=credential_dsn,
            model_name="deepseek-v4-flash",
        ),
    )

    response = client.get(
        "/api/projects/p1/planning/operations/operation-1"
    )

    assert response.status_code == 200
    assert set(response.json()["model"]) == {"providerId", "modelName"}
    assert response.json()["model"] == {
        "providerId": "unavailable",
        "modelName": "unavailable",
    }
    for forbidden in (credential_dsn, "root", "private"):
        assert forbidden not in response.text


def test_generate_fail_closes_entire_model_for_api_key_shaped_name():
    client, _, generation = make_client()
    key_sentinel = "sk-private-model-secret"
    generation.result = replace(
        generation.result,
        model=PublicModelSummary(
            provider_id="provider-1",
            model_name=key_sentinel,
        ),
    )

    response = client.post(
        "/api/projects/p1/planning/drafts/draft-1/generate",
        json={
            "draftRevision": 1,
            "draftHash": HASH,
            "idempotencyKey": "generate-redacted-model",
            "authorInstructions": "",
        },
    )

    assert response.status_code == 200
    assert set(response.json()["model"]) == {"providerId", "modelName"}
    assert response.json()["model"] == {
        "providerId": "unavailable",
        "modelName": "unavailable",
    }
    for forbidden in (key_sentinel, "private", "model-secret"):
        assert forbidden not in response.text


@pytest.mark.parametrize(
    ("method", "unsafe_value", "forbidden"),
    (
        (
            "get",
            "Authorization%3ABearer%20AUTH_SENTINEL",
            "AUTH_SENTINEL",
        ),
        (
            "post",
            "Authorization%3aBearer%20LOWER_SENTINEL",
            "LOWER_SENTINEL",
        ),
        ("get", "apiKey%3DKEY_SENTINEL", "KEY_SENTINEL"),
        ("post", "sk%2Dprivate%2Dencoded%2Dsecret", "encoded-secret"),
        ("get", "sk%2dprivate%2dlower%2dsecret", "lower-secret"),
        (
            "post",
            "sk%252Dprivate%252Ddouble%252Dsecret",
            "double-secret",
        ),
        (
            "get",
            "sk%25252Dprivate%25252Dtriple%25252Dsecret",
            "triple-secret",
        ),
        (
            "post",
            "sk%25252dprivate%25252dlower%25252dsecret",
            "lower-secret",
        ),
        (
            "get",
            "Authorization%25253ABearer%252520AUTH_TRIPLE_SENTINEL",
            "AUTH_TRIPLE_SENTINEL",
        ),
        (
            "post",
            "Authorization%25253aBearer%252520LOWER_TRIPLE_SENTINEL",
            "LOWER_TRIPLE_SENTINEL",
        ),
        ("get", "model%FFDECODE_SENTINEL", "DECODE_SENTINEL"),
        ("post", "model%ZZINVALID_SENTINEL", "INVALID_SENTINEL"),
        ("get", "\ud800SURROGATE_SENTINEL", "SURROGATE_SENTINEL"),
    ),
)
def test_operation_model_projection_decodes_and_rejects_secret_shapes(
    method,
    unsafe_value,
    forbidden,
):
    client, _, generation = make_client()
    generation.result = replace(
        generation.result,
        model=PublicModelSummary(
            provider_id="provider-1",
            model_name=unsafe_value,
        ),
    )

    if method == "post":
        response = client.post(
            "/api/projects/p1/planning/drafts/draft-1/generate",
            json={
                "draftRevision": 1,
                "draftHash": HASH,
                "idempotencyKey": "redacted-projection",
                "authorInstructions": "",
            },
        )
    else:
        response = client.get(
            "/api/projects/p1/planning/operations/operation-1"
        )

    assert response.status_code == 200
    assert response.json()["model"] == {
        "providerId": "unavailable",
        "modelName": "unavailable",
    }
    assert forbidden not in response.text
    assert "private" not in response.text


@pytest.mark.parametrize(
    ("method", "model_name"),
    (
        ("get", "deepseek-v4-flash"),
        ("post", "model+preview"),
        ("get", "model preview"),
    ),
)
def test_operation_model_projection_preserves_ordinary_model_names(
    method,
    model_name,
):
    client, _, generation = make_client()
    generation.result = replace(
        generation.result,
        model=PublicModelSummary(
            provider_id="provider-1",
            model_name=model_name,
        ),
    )

    if method == "post":
        response = client.post(
            "/api/projects/p1/planning/drafts/draft-1/generate",
            json={
                "draftRevision": 1,
                "draftHash": HASH,
                "idempotencyKey": "ordinary-model-projection",
                "authorInstructions": "",
            },
        )
    else:
        response = client.get(
            "/api/projects/p1/planning/operations/operation-1"
        )

    assert response.status_code == 200
    assert response.json()["model"] == {
        "providerId": "provider-1",
        "modelName": model_name,
    }


@pytest.mark.parametrize(
    (
        "status",
        "failure_code",
        "loaded",
        "loaded_revision",
    ),
    (
        ("pending", "PlanningProviderFailed", False, None),
        ("pending", None, True, 2),
        ("succeeded", "PlanningProviderFailed", True, 2),
        ("succeeded", None, False, 2),
        ("failed", None, False, None),
        ("failed", "PlanningProviderFailed", True, 2),
        ("superseded", "PlanningProviderFailed", False, None),
        ("superseded", None, True, 2),
        ("succeeded", None, True, 0),
        ("succeeded", None, True, -1),
    ),
)
def test_operation_projection_fail_closes_invalid_state_combinations(
    status,
    failure_code,
    loaded,
    loaded_revision,
):
    client, _, generation = make_client()
    generation.result = replace(
        generation.result,
        status=status,
        failure_code=failure_code,
        loaded=loaded,
        loaded_draft_revision=loaded_revision,
    )

    response = client.get(
        "/api/projects/p1/planning/operations/operation-1"
    )

    assert response.status_code == 200
    assert response.json() == {
        "operationId": "operation-1",
        "status": "failed",
        "failureCode": "PlanningGenerationFailed",
        "model": {
            "providerId": "provider-1",
            "modelName": "deepseek-v4-flash",
        },
        "loaded": False,
        "loadedDraftRevision": None,
    }


@pytest.mark.parametrize(
    ("status", "failure_code", "loaded", "loaded_revision"),
    (
        ("pending", None, False, None),
        ("succeeded", None, False, None),
        ("succeeded", None, True, 2),
        ("failed", "PlanningProviderFailed", False, None),
        ("superseded", None, False, None),
    ),
)
def test_operation_projection_preserves_every_valid_public_combination(
    status,
    failure_code,
    loaded,
    loaded_revision,
):
    client, _, generation = make_client()
    generation.result = replace(
        generation.result,
        status=status,
        failure_code=failure_code,
        loaded=loaded,
        loaded_draft_revision=loaded_revision,
    )

    response = client.post(
        "/api/projects/p1/planning/drafts/draft-1/generate",
        json={
            "draftRevision": 1,
            "draftHash": HASH,
            "idempotencyKey": f"valid-{status}-{loaded}",
            "authorInstructions": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["failureCode"] == failure_code
    assert response.json()["loaded"] is loaded
    assert response.json()["loadedDraftRevision"] == loaded_revision
