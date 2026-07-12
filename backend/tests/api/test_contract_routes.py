from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import contracts
from backend.security.redaction import install_error_handlers
from backend.services.contracts import ContractDraftInput
from backend.tests.support.contract_fakes import ContractHarness, draft_values


def make_client():
    harness = ContractHarness()
    app = FastAPI()
    app.include_router(contracts.router, prefix="/api")
    app.dependency_overrides[contracts.get_contract_service] = lambda: harness.service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), harness


def save_body(harness, expected=0, **overrides):
    draft = ContractDraftInput(**draft_values(harness.repository, **overrides))
    return {
        "expectedDraftVersion": expected,
        "draft": draft.model_dump(mode="json"),
    }


def test_save_reload_and_preview_routes_return_strict_safe_public_snapshots():
    client, harness = make_client()

    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    )
    reloaded = client.get("/api/projects/p1/contract-draft")
    preview = client.post("/api/projects/p1/contracts/preview")

    assert [saved.status_code, reloaded.status_code, preview.status_code] == [200] * 3
    assert reloaded.json() == saved.json()
    assert saved.json()["baseHeadRevision"] == 0
    assert saved.json()["draftVersion"] == 1
    assert saved.json()["draft"]["modelBindingRef"]["revision"] == 3
    assert saved.json()["draft"]["qualityCharterVersion"] == "writer-core-quality-v1"
    body = preview.json()
    assert body["contractReady"] is True
    assert body["reasons"] == []
    assert body["expectedRevision"] == 1
    assert body["seedRef"]["revisionId"] == "seed-revision-1"
    assert body["engineRef"]["id"] == "engine-1"
    assert body["bindingRef"]["revision"] == 3
    assert len(body["bindingRef"]["items"]) == 8
    assert body["styleRefs"][0]["role"] == "primary"
    assert body["experienceCardRefs"][0]["contentHash"]
    assert body["corpusSourceRefs"][0]["selectionMode"] == "author"
    assert body["creationContract"]["qualityCharterVersion"] == "writer-core-quality-v1"
    assert body["creationHash"] == client.post(
        "/api/projects/p1/contracts/preview"
    ).json()["creationHash"]
    forbidden = (
        "rubric", "checklist", "payload_json", "relative_path",
        "api_key", "base_url", "C:\\\\Users", "secret",
    )
    assert all(marker not in preview.text.lower() for marker in forbidden)


def test_route_validation_rejects_unknown_long_duplicate_and_same_style_inputs():
    client, harness = make_client()
    valid = save_body(harness)
    cases = (
        {**valid, "unexpected": True},
        {**valid, "draft": {**valid["draft"], "likes": ["x"] * 21}},
        {
            **valid,
            "draft": {
                **valid["draft"],
                "experienceCardRefs": valid["draft"]["experienceCardRefs"] * 2,
            },
        },
        {
            **valid,
            "draft": {
                **valid["draft"],
                "modelBindingRef": {
                    "id": "client-controlled", "revision": 99,
                    "contentHash": "f" * 64,
                },
            },
        },
        {
            **valid,
            "draft": {
                **valid["draft"],
                "secondaryStyleRef": valid["draft"]["primaryStyleRef"],
            },
        },
    )
    for payload in cases:
        response = client.put("/api/projects/p1/contract-draft", json=payload)
        assert response.status_code == 422
    assert harness.repository.write_count == 0
    assert client.post(
        "/api/projects/p1/contracts/preview", json={"debug": True}
    ).status_code == 422


def test_routes_return_stable_404_and_409_for_archived_and_stale_cas():
    client, harness = make_client()
    archived = client.get("/api/projects/archived/contract-draft")
    missing = client.get("/api/projects/missing/contract-draft")
    created = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    )
    conflict = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness, expected=0)
    )

    assert archived.status_code == missing.status_code == 404
    assert archived.json()["code"] == "ContractNotFound"
    assert created.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "ContractConflict"
    assert set(conflict.json()) == {"code", "message", "correlationId"}


def test_clone_route_delegates_and_returns_version_one_from_confirmed_head():
    client, harness = make_client()
    saved_response = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    )
    assert saved_response.status_code == 200
    saved = harness.repository.drafts["p1"]
    preview = harness.service

    # Seed a faithful confirmed snapshot using the already-tested service preview.
    import asyncio
    result = asyncio.run(preview.preview("p1"))
    harness.repository.drafts.clear()
    harness.repository.heads["p1"] = {
        "project_id": "p1", "revision": 6,
        "creation_contract_id": "creation-6", "style_contract_id": "style-6",
        "creation_hash": result.creation_hash, "style_hash": result.style_hash,
    }
    harness.repository.confirmed["p1"] = {
        "revision": 6,
        "seed_revision_id": saved["seed_revision_id"],
        "seed_hash": saved["seed_hash"],
        "engine_option_id": saved["engine_option_id"],
        "engine_hash": result.engine_ref.content_hash,
        "binding_revision_id": result.binding_ref.id,
        "binding_revision": result.binding_ref.revision,
        "binding_hash": result.binding_ref.content_hash,
        "creation_hash": result.creation_hash,
        "style_hash": result.style_hash,
        "head_creation_hash": result.creation_hash,
        "head_style_hash": result.style_hash,
        "creation_json": result.creation_contract.model_dump(mode="json"),
        "style_json": result.style_contract.model_dump(mode="json"),
        "likes_json": list(result.likes),
        "dislikes_json": list(result.dislikes),
        "style_refs": tuple(ref.model_dump(mode="json") for ref in result.style_refs),
        "experience_card_refs": tuple(
            ref.model_dump(mode="json") for ref in result.experience_card_refs
        ),
        "corpus_source_refs": tuple(
            ref.model_dump(mode="json") for ref in result.corpus_source_refs
        ),
    }

    cloned = client.post("/api/projects/p1/contracts/clone")
    second = client.post("/api/projects/p1/contracts/clone")

    assert cloned.status_code == 200
    assert cloned.json()["baseHeadRevision"] == 6
    assert cloned.json()["draftVersion"] == 1
    assert second.status_code == 409
