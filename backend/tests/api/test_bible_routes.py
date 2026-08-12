from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import bibles
from backend.http_errors import ProjectArchived
from backend.security.redaction import install_error_handlers
from backend.services.bible_generation import (
    BibleGenerationAttemptNotFound,
    BibleGenerationNotReady,
)
from backend.tests.unit.test_bible_service import (
    HASH_A,
    HASH_D,
    HASH_E,
    BibleHarness,
    bible_payload,
    contract_head,
)


class GenerationHarness:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.attempt = SimpleNamespace(
            attempt_id="generation-attempt-1",
            project_id="p1",
            status="succeeded",
            attempt_version=2,
            provider_id="provider-1",
            model_name_snapshot="novel-model",
            input_manifest_hash="9" * 64,
            result_hash="8" * 64,
            public_error_code=None,
            created_at=1_900_000_000_000,
            completed_at=1_900_000_000_100,
            api_key="must-not-publish",
            base_url="https://private.invalid/v1",
            result_json={"raw": "must-not-publish"},
        )

    async def generate(self, command):
        self.calls.append(("generate", command))
        if self.failure is not None:
            raise self.failure
        return self.attempt

    async def get_attempt(self, project_id, attempt_id):
        self.calls.append(("get", project_id, attempt_id))
        if self.failure is not None:
            raise self.failure
        if project_id != "p1" or attempt_id != self.attempt.attempt_id:
            raise BibleGenerationAttemptNotFound()
        return self.attempt


def make_client():
    harness = BibleHarness()
    generation = GenerationHarness()
    app = FastAPI()
    app.include_router(bibles.router, prefix="/api")
    app.dependency_overrides[bibles.get_bible_service] = lambda: harness.service
    app.dependency_overrides[
        bibles.get_bible_generation_service
    ] = lambda: generation
    install_error_handlers(app)
    return (
        TestClient(app, raise_server_exceptions=False),
        harness,
        generation,
    )


def save_body(expected=0, **payload_overrides):
    return {
        "expectedDraftVersion": expected,
        "draft": bible_payload(**payload_overrides).model_dump(mode="json"),
    }


def test_confirmed_bible_routes_are_read_only_and_exact_retry_replays():
    client, _, _ = make_client()

    missing_head = client.get("/api/projects/p1/bible/head")
    missing_draft = client.get("/api/projects/p1/bible/draft")
    saved = client.put(
        "/api/projects/p1/bible/draft",
        json=save_body(),
    )
    confirmed = client.post(
        "/api/projects/p1/bible/confirm",
        json={
            "idempotencyKey": "route-confirm-1",
            "expectedDraftVersion": saved.json()["draftVersion"],
            "expectedHeadRevision": 0,
        },
    )
    head = client.get("/api/projects/p1/bible/head")
    history = client.get("/api/projects/p1/bible/history")
    historical = client.get("/api/projects/p1/bible/history/1")
    replay = client.post(
        "/api/projects/p1/bible/confirm",
        json={
            "idempotencyKey": "route-confirm-1",
            "expectedDraftVersion": saved.json()["draftVersion"],
            "expectedHeadRevision": 0,
        },
    )
    clone = client.post(
        "/api/projects/p1/bible/draft/clone",
        json={"sourceRevision": 1},
    )
    saved_again = client.put(
        "/api/projects/p1/bible/draft", json=save_body()
    )
    new_confirm = client.post(
        "/api/projects/p1/bible/confirm",
        json={
            "idempotencyKey": "route-confirm-2",
            "expectedDraftVersion": 1,
            "expectedHeadRevision": 1,
        },
    )

    assert [
        missing_head.status_code,
        missing_draft.status_code,
        saved.status_code,
        confirmed.status_code,
        head.status_code,
        history.status_code,
        historical.status_code,
        clone.status_code,
    ] == [200, 200, 200, 201, 200, 200, 200, 409]
    assert missing_head.json()["status"] == "missing"
    assert missing_draft.json()["status"] == "missing"
    assert saved.json()["status"] == "current"
    assert saved.json()["draftVersion"] == 1
    assert saved.json()["canClone"] is False
    assert saved.json()["basis"]["bindingRevisionId"] is None
    assert saved.json()["basis"]["bindingHash"] is None
    assert confirmed.json()["revision"] == head.json()["revision"] == 1
    assert replay.status_code == 201
    assert replay.json() == confirmed.json()
    assert confirmed.json()["canClone"] is False
    assert head.json()["canClone"] is False
    assert historical.json()["canClone"] is False
    assert history.json()["items"] == [historical.json()]
    assert history.json()["nextBeforeRevision"] is None
    for response in (clone, saved_again, new_confirm):
        assert response.status_code == 409
        assert response.json()["code"] == "bible_already_confirmed"


def test_clone_by_draft_id_only_accepts_the_active_superseded_draft():
    client, harness, _ = make_client()
    saved = client.put("/api/projects/p1/bible/draft", json=save_body()).json()

    current_clone = client.post(
        "/api/projects/p1/bible/draft/clone",
        json={"sourceDraftId": saved["draftId"]},
    )
    assert current_clone.status_code == 409
    assert current_clone.json()["code"] == "BibleConflict"

    harness.contract_service.heads["p1"] = contract_head(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_D,
        revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_E,
        style_contract_id="style-b",
        style_hash=HASH_A,
    )
    superseded = client.get("/api/projects/p1/bible/draft").json()
    clone = client.post(
        "/api/projects/p1/bible/draft/clone",
        json={"sourceDraftId": saved["draftId"]},
    )

    assert superseded["status"] == "superseded"
    assert superseded["canClone"] is True
    assert clone.status_code == 200
    assert clone.json()["draftId"] != saved["draftId"]
    assert clone.json()["canClone"] is False


def test_clone_by_draft_id_returns_confirmed_baseline_conflict():
    client, _, _ = make_client()
    saved = client.put("/api/projects/p1/bible/draft", json=save_body()).json()
    confirmed = client.post(
        "/api/projects/p1/bible/confirm",
        json={
            "idempotencyKey": "retired-source-confirm",
            "expectedDraftVersion": saved["draftVersion"],
            "expectedHeadRevision": 0,
        },
    )
    clone = client.post(
        "/api/projects/p1/bible/draft/clone",
        json={"sourceDraftId": saved["draftId"]},
    )

    assert confirmed.status_code == 201
    assert clone.status_code == 409
    assert clone.json()["code"] == "bible_already_confirmed"


def test_public_dtos_are_explicit_allowlists_without_internal_or_secret_fields():
    client, _, _ = make_client()
    saved = client.put("/api/projects/p1/bible/draft", json=save_body()).json()

    assert set(saved) == {
        "projectId",
        "lifecycle",
        "status",
        "draftId",
        "draftVersion",
        "baseHeadRevision",
        "contentHash",
        "draft",
        "basis",
        "canEdit",
        "canConfirm",
        "canClone",
        "reasons",
        "createdAt",
        "updatedAt",
    }
    assert set(saved["basis"]) == {
        "selectionRevision",
        "seedId",
        "seedRevisionId",
        "seedHash",
        "contractRevision",
        "creationContractId",
        "creationHash",
        "styleContractId",
        "styleHash",
        "bindingRevisionId",
        "bindingHash",
        "policyVersion",
    }
    forbidden = (
        "api_key",
        "apikey",
        "base_url",
        "baseurl",
        "authorization",
        "password",
        "token",
        "raw sql",
        "traceback",
        "debug",
    )
    assert all(marker not in str(saved).lower() for marker in forbidden)


def test_request_models_reject_unknown_fields_invalid_clone_source_and_fact_shapes():
    client, harness, _ = make_client()
    valid = save_body()
    cases = (
        {**valid, "basis": {"selectionRevision": 99}},
        {**valid, "unexpected": True},
        {
            **valid,
            "draft": {
                **valid["draft"],
                "occurredEvents": [{"id": "event-1", "text": "事实"}],
            },
        },
        {
            **valid,
            "draft": {
                **valid["draft"],
                "worldRules": [
                    {"id": "same", "text": "规则一"},
                    {"id": "same", "text": "规则二"},
                ],
            },
        },
    )
    for case in cases:
        response = client.put("/api/projects/p1/bible/draft", json=case)
        assert response.status_code == 422
        assert response.json()["code"] == "BibleRequestInvalid"

    clone_cases = (
        {},
        {"sourceDraftId": "draft-1", "sourceRevision": 1},
        {"sourceRevision": 0},
        {"sourceDraftId": "draft-1", "debug": True},
    )
    for case in clone_cases:
        response = client.post(
            "/api/projects/p1/bible/draft/clone",
            json=case,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "BibleRequestInvalid"
    assert harness.repository.write_count == 0


def test_confirm_is_strict_idempotent_and_same_key_different_request_conflicts():
    client, _, _ = make_client()
    saved = client.put(
        "/api/projects/p1/bible/draft",
        json=save_body(),
    ).json()
    body = {
        "idempotencyKey": "route-idempotency-1",
        "expectedDraftVersion": saved["draftVersion"],
        "expectedHeadRevision": 0,
    }

    first = client.post("/api/projects/p1/bible/confirm", json=body)
    replay = client.post("/api/projects/p1/bible/confirm", json=body)
    conflict = client.post(
        "/api/projects/p1/bible/confirm",
        json={**body, "expectedHeadRevision": 1},
    )
    invalid = client.post(
        "/api/projects/p1/bible/confirm",
        json={**body, "debug": "internal"},
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "BibleConflict"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "BibleRequestInvalid"
    assert set(conflict.json()) == {"code", "message", "correlationId"}


def test_unrecorded_confirmation_failure_is_retryable_without_leaking_details():
    client, harness, _ = make_client()
    saved = client.put(
        "/api/projects/p1/bible/draft",
        json=save_body(),
    ).json()
    state = {"fail_main": True}

    def fail_once(stage):
        if state["fail_main"] and stage == "after_request_reserve":
            state["fail_main"] = False
            raise RuntimeError("private main failure")

    harness.service.failpoint = fail_once
    harness.repository.fail_failed_request_insert = True
    body = {
        "idempotencyKey": "route-retryable-confirm",
        "expectedDraftVersion": saved["draftVersion"],
        "expectedHeadRevision": 0,
    }

    retryable = client.post("/api/projects/p1/bible/confirm", json=body)
    harness.repository.fail_failed_request_insert = False
    succeeded = client.post("/api/projects/p1/bible/confirm", json=body)

    assert retryable.status_code == 503
    assert retryable.json()["code"] == "BibleConfirmationRetryable"
    assert retryable.json()["retryable"] is True
    assert set(retryable.json()) == {
        "code",
        "message",
        "correlationId",
        "retryable",
    }
    assert "private" not in str(retryable.json()).lower()
    assert succeeded.status_code == 201
    assert succeeded.json()["revision"] == 1


def test_archived_reads_remain_available_but_capabilities_and_mutations_are_closed():
    client, harness, _ = make_client()
    saved = client.put(
        "/api/projects/p1/bible/draft",
        json=save_body(),
    ).json()
    harness.repository.projects["p1"]["archived_at"] = 123
    writes = harness.repository.write_count

    draft = client.get("/api/projects/p1/bible/draft")
    head = client.get("/api/projects/p1/bible/head")
    history = client.get("/api/projects/p1/bible/history")
    save = client.put(
        "/api/projects/p1/bible/draft",
        json=save_body(saved["draftVersion"]),
    )
    clone = client.post(
        "/api/projects/p1/bible/draft/clone",
        json={"sourceDraftId": saved["draftId"]},
    )
    confirm = client.post(
        "/api/projects/p1/bible/confirm",
        json={
            "idempotencyKey": "archived-route-confirm",
            "expectedDraftVersion": saved["draftVersion"],
            "expectedHeadRevision": 0,
        },
    )

    assert draft.status_code == head.status_code == history.status_code == 200
    assert draft.json()["lifecycle"] == "archived"
    assert draft.json()["canEdit"] is False
    assert draft.json()["canConfirm"] is False
    assert draft.json()["canClone"] is False
    assert head.json()["canEdit"] is False
    assert head.json()["canClone"] is False
    for response in (save, clone, confirm):
        assert response.status_code == 409
        assert response.json()["code"] == "ProjectArchived"
    assert harness.repository.write_count == writes


def test_no_delete_or_reset_route_is_exposed():
    client, _, _ = make_client()
    routes = {
        (method, route.path)
        for route in client.app.routes
        for method in route.methods
        if "/bible" in route.path
    }

    assert routes == {
        ("GET", "/api/projects/{pid}/bible/head"),
        ("GET", "/api/projects/{pid}/bible/draft"),
        ("PUT", "/api/projects/{pid}/bible/draft"),
        ("POST", "/api/projects/{pid}/bible/draft/clone"),
        ("POST", "/api/projects/{pid}/bible/confirm"),
        ("GET", "/api/projects/{pid}/bible/history"),
        ("GET", "/api/projects/{pid}/bible/history/{revision}"),
        ("POST", "/api/projects/{pid}/bible/generate"),
        (
            "GET",
            "/api/projects/{pid}/bible/generation-attempts/{attemptId}",
        ),
    }
    assert client.delete("/api/projects/p1/bible/draft").status_code in {
        404,
        405,
    }


def test_generation_routes_accept_only_browser_command_and_return_safe_facts():
    client, _, generation = make_client()
    body = {
        "authorInstructions": "强调群像分工。",
        "expectedDraftVersion": 0,
        "expectedHeadRevision": 0,
        "idempotencyKey": "generation-key-1",
    }

    created = client.post(
        "/api/projects/p1/bible/generate",
        json=body,
    )
    fetched = client.get(
        "/api/projects/p1/bible/generation-attempts/generation-attempt-1"
    )

    assert created.status_code == fetched.status_code == 200
    assert created.json() == {"attempt": fetched.json()}
    assert set(fetched.json()) == {
        "id",
        "projectId",
        "status",
        "attemptVersion",
        "providerId",
        "modelNameSnapshot",
        "inputManifestHash",
        "resultHash",
        "publicErrorCode",
        "createdAt",
        "completedAt",
    }
    command = generation.calls[0][1]
    assert command.project_id == "p1"
    assert command.author_instructions == "强调群像分工。"
    assert command.expected_draft_version == 0
    assert command.expected_head_revision == 0
    assert command.idempotency_key == "generation-key-1"
    rendered = str(created.json()).lower()
    assert all(
        forbidden not in rendered
        for forbidden in (
            "api_key",
            "base_url",
            "private.invalid",
            "raw",
            "prompt",
        )
    )


def test_generation_body_forbids_selection_assets_binding_and_provider_fields():
    client, _, generation = make_client()
    valid = {
        "authorInstructions": "",
        "expectedDraftVersion": 0,
        "expectedHeadRevision": 0,
        "idempotencyKey": "generation-key-1",
    }
    extras = (
        {"selectionRevision": 3},
        {"seed": {"id": "seed-1"}},
        {"contract": {"revision": 2}},
        {"assets": []},
        {"bindingRevisionId": "binding-1"},
        {"providerId": "provider-1"},
        {"model": "novel-model"},
        {"debug": True},
    )
    for extra in extras:
        response = client.post(
            "/api/projects/p1/bible/generate",
            json={**valid, **extra},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "BibleRequestInvalid"
    assert generation.calls == []


def test_generation_public_errors_cover_not_ready_archived_and_missing_attempt():
    client, _, generation = make_client()
    body = {
        "authorInstructions": "",
        "expectedDraftVersion": 0,
        "expectedHeadRevision": 0,
        "idempotencyKey": "generation-key-1",
    }
    generation.failure = BibleGenerationNotReady()
    not_ready = client.post("/api/projects/p1/bible/generate", json=body)
    generation.failure = ProjectArchived()
    archived = client.post("/api/projects/p1/bible/generate", json=body)
    generation.failure = BibleGenerationAttemptNotFound()
    missing = client.get(
        "/api/projects/p1/bible/generation-attempts/missing-attempt"
    )

    assert (not_ready.status_code, not_ready.json()["code"]) == (
        422,
        "BibleGenerationNotReady",
    )
    assert (archived.status_code, archived.json()["code"]) == (
        409,
        "ProjectArchived",
    )
    assert (missing.status_code, missing.json()["code"]) == (
        404,
        "BibleGenerationAttemptNotFound",
    )
    for response in (not_ready, archived, missing):
        assert set(response.json()) <= {
            "code",
            "message",
            "correlationId",
            "retryable",
        }
