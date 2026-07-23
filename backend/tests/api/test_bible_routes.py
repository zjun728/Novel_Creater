from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import bibles
from backend.security.redaction import install_error_handlers
from backend.tests.unit.test_bible_service import (
    HASH_A,
    HASH_D,
    HASH_E,
    BibleHarness,
    bible_payload,
    contract_head,
)


def make_client():
    harness = BibleHarness()
    app = FastAPI()
    app.include_router(bibles.router, prefix="/api")
    app.dependency_overrides[bibles.get_bible_service] = lambda: harness.service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), harness


def save_body(expected=0, **payload_overrides):
    return {
        "expectedDraftVersion": expected,
        "draft": bible_payload(**payload_overrides).model_dump(mode="json"),
    }


def test_exact_manual_bible_routes_save_confirm_clone_and_read_history():
    client, _ = make_client()

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
    clone = client.post(
        "/api/projects/p1/bible/draft/clone",
        json={"sourceRevision": 1},
    )
    refreshed_head = client.get("/api/projects/p1/bible/head")
    refreshed_historical = client.get("/api/projects/p1/bible/history/1")
    blocked_clone = client.post(
        "/api/projects/p1/bible/draft/clone",
        json={"sourceRevision": 1},
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
    ] == [200, 200, 200, 201, 200, 200, 200, 200]
    assert missing_head.json()["status"] == "missing"
    assert missing_draft.json()["status"] == "missing"
    assert saved.json()["status"] == "current"
    assert saved.json()["draftVersion"] == 1
    assert saved.json()["canClone"] is False
    assert saved.json()["basis"]["bindingRevisionId"] is None
    assert saved.json()["basis"]["bindingHash"] is None
    assert confirmed.json()["revision"] == head.json()["revision"] == 1
    assert confirmed.json()["canClone"] is True
    assert head.json()["canClone"] is True
    assert historical.json()["canClone"] is True
    assert history.json()["items"] == [historical.json()]
    assert history.json()["nextBeforeRevision"] is None
    assert clone.json()["draftVersion"] == 1
    assert clone.json()["baseHeadRevision"] == 1
    assert clone.json()["draft"] == historical.json()["bible"]
    assert clone.json()["canClone"] is False
    assert refreshed_head.json()["canClone"] is False
    assert refreshed_historical.json()["canClone"] is False
    assert blocked_clone.status_code == 409
    assert blocked_clone.json()["code"] == "BibleConflict"


def test_clone_by_draft_id_only_accepts_the_active_superseded_draft():
    client, harness = make_client()
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


def test_clone_by_draft_id_hides_a_retired_confirmed_draft():
    client, _ = make_client()
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
    assert clone.status_code == 404
    assert clone.json()["code"] == "BibleNotFound"


def test_public_dtos_are_explicit_allowlists_without_internal_or_secret_fields():
    client, _ = make_client()
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
    client, harness = make_client()
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
    client, _ = make_client()
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
    client, harness = make_client()
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
    client, harness = make_client()
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
    client, _ = make_client()
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
    }
    assert client.delete("/api/projects/p1/bible/draft").status_code in {
        404,
        405,
    }
