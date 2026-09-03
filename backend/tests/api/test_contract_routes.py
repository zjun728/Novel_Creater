from __future__ import annotations

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.routers import contracts
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
    assert "documentProjection" not in saved.json()
    assert reloaded.json()["draft"] == saved.json()["draft"]
    projection = reloaded.json()["documentProjection"]
    assert projection["selectedEngine"]["name"] == "方案 1"
    assert projection["primaryStyle"]["name"] == "克制现实"
    assert projection["primaryStyle"]["revision"] == 2
    assert projection["unavailableReasons"] == []
    assert saved.json()["baseHeadRevision"] == 0
    assert saved.json()["draftVersion"] == 1
    assert saved.json()["draftStage"] == "assets"
    assert saved.json()["isComplete"] is True
    assert saved.json()["draft"]["draftStage"] == "assets"
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


@pytest.mark.parametrize("stage", ("engine", "style"))
def test_progressive_draft_response_is_incomplete_and_preview_is_stable_422(stage):
    client, harness = make_client()
    overrides = {"draftStage": stage}
    if stage == "engine":
        overrides.update({
            "primaryStyleRef": None, "secondaryStyleRef": None,
            "likes": None, "dislikes": None,
            "experienceCardRefs": None, "corpusSourceRefs": None,
        })
    else:
        overrides.update({"experienceCardRefs": None, "corpusSourceRefs": None})

    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness, **overrides)
    )
    preview = client.post("/api/projects/p1/contracts/preview")
    confirm = client.post("/api/projects/p1/contracts/confirm", json={
        "idempotencyKey": f"incomplete-{stage}",
        "expectedDraftVersion": saved.json()["draftVersion"],
        "expectedDraftHash": saved.json()["contentHash"],
    })

    assert saved.status_code == 200
    assert saved.json()["draftStage"] == stage
    assert saved.json()["isComplete"] is False
    assert saved.json()["draft"]["draftStage"] == stage
    assert preview.status_code == 422
    assert preview.json()["code"] == "ContractDraftIncomplete"
    assert confirm.status_code == 422
    assert confirm.json()["code"] == "ContractDraftIncomplete"


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
                "seedRevisionId": "forged-revision",
                "seedHash": "f" * 64,
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


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("targetTotalWords", 100_000_001),
        ("expectedVolumeCount", 1_001),
        ("expectedChapterCount", 100_001),
        ("chapterWordRangePreference", [100_001, 100_001]),
        ("chapterWordRangePreference", [1, 100_001]),
    ),
)
def test_save_route_returns_stable_422_for_capacity_values_above_product_bounds(
    field_name, value,
):
    client, harness = make_client()
    body = save_body(harness)
    body["draft"][field_name] = value

    response = client.put("/api/projects/p1/contract-draft", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "ContractRequestInvalid"
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert harness.repository.write_count == 0


def test_path_shaped_input_is_never_persisted_or_reloaded():
    client, harness = make_client()
    valid = save_body(harness)
    sentinels = (
        r"C:\private\novel.txt",
        "/home/author/novel.txt",
        r"\\server\share\novel.txt",
        r"C:private\novel.txt",
        "safe/../private/novel.txt",
    )
    for sentinel in sentinels:
        payload = {
            **valid,
            "draft": {**valid["draft"], "channelProfileKey": sentinel},
        }
        response = client.put("/api/projects/p1/contract-draft", json=payload)
        assert response.status_code == 422
        assert sentinel not in response.text

    assert harness.repository.write_count == 0
    assert client.get("/api/projects/p1/contract-draft").status_code == 404


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


def test_archived_project_reads_existing_draft_but_rejects_formal_operations():
    client, harness = make_client()
    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    )
    writes = harness.repository.write_count
    harness.repository.projects["p1"]["status"] = "archived"

    loaded = client.get("/api/projects/p1/contract-draft")
    preview = client.post("/api/projects/p1/contracts/preview")
    saved_again = client.put(
        "/api/projects/p1/contract-draft",
        json=save_body(harness, expected=saved.json()["draftVersion"]),
    )
    confirmed = client.post("/api/projects/p1/contracts/confirm", json={
        "idempotencyKey": "archived-confirm",
        "expectedDraftVersion": saved.json()["draftVersion"],
        "expectedDraftHash": saved.json()["contentHash"],
    })

    assert loaded.status_code == 200
    loaded_body = loaded.json()
    assert loaded_body.pop("documentProjection")["selectedEngine"]["name"] == "方案 1"
    assert loaded_body == saved.json()
    for response in (preview, saved_again, confirmed):
        assert response.status_code in {404, 409}
    assert preview.json()["code"] == "ContractNotFound"
    assert saved_again.json()["code"] == "ProjectArchived"
    assert confirmed.json()["code"] == "ProjectArchived"
    assert harness.repository.write_count == writes


def test_archived_project_reads_confirmed_head_and_history_but_cannot_clone():
    client, harness = make_client()
    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    ).json()
    confirmed = client.post("/api/projects/p1/contracts/confirm", json={
        "idempotencyKey": "confirm-before-archive",
        "expectedDraftVersion": saved["draftVersion"],
        "expectedDraftHash": saved["contentHash"],
    })
    writes = harness.repository.write_count
    harness.repository.projects["p1"]["status"] = "archived"

    head = client.get("/api/projects/p1/contracts/head")
    history = client.get("/api/projects/p1/contracts/history")
    cloned = client.post("/api/projects/p1/contracts/1/clone")

    assert confirmed.status_code == 201
    assert head.status_code == history.status_code == 200
    assert head.json() == confirmed.json()
    assert history.json()["items"] == [confirmed.json()]
    assert cloned.status_code == 409
    assert cloned.json()["code"] == "ProjectArchived"
    assert harness.repository.write_count == writes


def test_preview_missing_dependencies_is_stable_200_with_null_contracts():
    cases = (
        ("seed", "seed_missing", "creationContract"),
        ("engine", "engine_missing", "creationContract"),
        ("style", "style_missing:primary", "styleContract"),
        ("binding", "binding_missing", "creationContract"),
    )
    for missing, reason, null_field in cases:
        client, harness = make_client()
        assert client.put(
            "/api/projects/p1/contract-draft", json=save_body(harness)
        ).status_code == 200
        if missing == "seed":
            harness.repository.seed_revisions.clear()
        elif missing == "engine":
            harness.repository.engines.clear()
        elif missing == "style":
            harness.repository.styles.pop("style-primary")
        else:
            harness.repository.binding_revisions.clear()

        first = client.post("/api/projects/p1/contracts/preview")
        second = client.post("/api/projects/p1/contracts/preview")

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert reason in first.json()["reasons"]
        assert first.json()[null_field] is None
        assert "Internal server error" not in first.text


@pytest.mark.parametrize("command", ("preview", "1/clone"))
def test_contract_commands_strictly_reject_and_redact_nonempty_bodies(command):
    client, harness = make_client()
    sentinel = "/private/contract-sentinel"

    response = client.post(
        f"/api/projects/p1/contracts/{command}",
        json={"unexpected": sentinel},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ContractRequestInvalid"
    assert sentinel not in response.text
    assert harness.repository.write_count == 0


@pytest.mark.parametrize("raw_body", ([], "", 0, False))
def test_preview_rejects_falsey_nonobject_bodies(raw_body):
    client, _ = make_client()
    response = client.post("/api/projects/p1/contracts/preview", json=raw_body)
    assert response.status_code == 422
    assert response.json()["code"] == "ContractRequestInvalid"


def test_clone_route_rejects_confirmed_baseline_without_creating_a_draft():
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
    reference_manifest = harness.service._reference_manifest(result)
    harness.repository.confirmed["p1"] = {
        "project_id": "p1",
        "revision": 6,
        "selection_revision": result.selection_revision,
        "channel_profile_key": result.creation_contract.channelProfileKey,
        "genre_profile_key": result.creation_contract.genreProfileKey,
        "quality_charter_version": result.creation_contract.qualityCharterVersion,
        "total_word_min": result.creation_contract.targetTotalWords,
        "total_word_max": result.creation_contract.targetTotalWords,
        "chapter_capacity_policy": canonical_json({
            "expectedVolumeCount": result.creation_contract.expectedVolumeCount,
            "expectedChapterCount": result.creation_contract.expectedChapterCount,
            "chapterWordRangePreference": list(
                result.creation_contract.chapterWordRangePreference
            ),
        }),
        "seed_id": result.seed_ref.id,
        "seed_revision_id": saved["seed_revision_id"],
        "seed_hash": saved["seed_hash"],
        "engine_option_id": saved["engine_option_id"],
        "engine_batch_id": result.engine_ref.batch_id,
        "engine_hash": result.engine_ref.content_hash,
        "binding_revision_id": result.binding_ref.id,
        "binding_revision": result.binding_ref.revision,
        "binding_hash": result.binding_ref.content_hash,
        "creation_hash": result.creation_hash,
        "style_hash": result.style_hash,
        "head_creation_hash": result.creation_hash,
        "head_style_hash": result.style_hash,
        "creation_contract_id": "creation-6",
        "style_contract_id": "style-6",
        "reference_manifest_json": canonical_json(reference_manifest),
        "reference_manifest_hash": canonical_hash(reference_manifest),
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
            "corpus_fragment_refs": tuple({
                "sourceId": source.id,
                **fragment.model_dump(mode="json"),
            } for source in result.corpus_source_refs
              for fragment in source.fragments),
        }

    cloned = client.post("/api/projects/p1/contracts/6/clone")

    assert cloned.status_code == 409
    assert cloned.json()["code"] == "contract_already_confirmed"
    assert harness.repository.drafts == {}


def test_clone_route_requires_explicit_positive_source_revision():
    client, harness = make_client()
    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    ).json()
    confirmed = client.post("/api/projects/p1/contracts/confirm", json={
        "idempotencyKey": "explicit-clone-source",
        "expectedDraftVersion": saved["draftVersion"],
        "expectedDraftHash": saved["contentHash"],
    })
    assert confirmed.status_code == 201

    cloned = client.post("/api/projects/p1/contracts/1/clone")

    assert cloned.status_code == 409
    assert cloned.json()["code"] == "contract_already_confirmed"
    assert client.post("/api/projects/p1/contracts/0/clone").status_code == 422
    assert client.post("/api/projects/p1/contracts/not-a-revision/clone").status_code == 422


def test_clone_route_returns_stable_conflict_without_a_confirmed_head():
    client, _ = make_client()

    response = client.post("/api/projects/p1/contracts/999/clone")

    assert response.status_code == 409
    assert response.json()["code"] == "ContractConflict"


def test_confirm_route_is_strict_returns_201_and_head_history_are_safe():
    client, harness = make_client()
    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    ).json()
    body = {
        "idempotencyKey": "api-confirm-1",
        "expectedDraftVersion": saved["draftVersion"],
        "expectedDraftHash": saved["contentHash"],
    }

    confirmed = client.post("/api/projects/p1/contracts/confirm", json=body)
    head = client.get("/api/projects/p1/contracts/head")
    history = client.get("/api/projects/p1/contracts/history")

    assert confirmed.status_code == 201
    assert head.status_code == history.status_code == 200
    assert confirmed.json()["revision"] == head.json()["revision"] == 1
    assert history.json()["items"] == [head.json()]
    assert confirmed.json()["supersededReasons"] == []
    assert head.json()["supersededReasons"] == []
    assert len(head.json()["bindingRef"]["items"]) == 8
    assert head.json()["contractReady"] is True
    forbidden = (
        "api_key", "apikey", "base_url", "baseurl", "payload_json",
        "raw", "path", "secret",
    )
    assert all(word not in (confirmed.text + head.text + history.text).lower()
               for word in forbidden)


def test_clone_manifest_is_not_read_after_confirmation_and_redacts_internal_snapshot():
    client, harness = make_client()
    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    ).json()
    confirmed = client.post("/api/projects/p1/contracts/confirm", json={
        "idempotencyKey": "api-clone-corrupt",
        "expectedDraftVersion": saved["draftVersion"],
        "expectedDraftHash": saved["contentHash"],
    })
    assert confirmed.status_code == 201
    sentinel = r"C:\private\manifest-sentinel.json"
    harness.repository.confirmed["p1"]["reference_manifest_json"] = canonical_json({
        "internalPath": sentinel,
    })

    response = client.post("/api/projects/p1/contracts/1/clone")

    assert response.status_code == 409
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == "contract_already_confirmed"
    assert sentinel not in response.text
    assert "reference_manifest" not in response.text.lower()


@pytest.mark.parametrize("body", (
    {},
    {"idempotencyKey": "x", "expectedDraftVersion": 1,
     "expectedDraftHash": "a" * 64, "extra": True},
    {"idempotencyKey": "x" * 65, "expectedDraftVersion": 1,
     "expectedDraftHash": "a" * 64},
    {"idempotencyKey": "/private/key", "expectedDraftVersion": 1,
     "expectedDraftHash": "a" * 64},
))
def test_confirm_route_manually_rejects_and_redacts_invalid_body(body):
    client, _ = make_client()
    response = client.post("/api/projects/p1/contracts/confirm", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "ContractRequestInvalid"
    assert "/private/key" not in response.text


def test_head_zero_and_history_limit_are_explicit_and_bounded():
    client, _ = make_client()
    head = client.get("/api/projects/p1/contracts/head")
    assert head.status_code == 200
    assert head.json() == {
        "projectId": "p1", "revision": 0, "hasContract": False,
        "contractReady": False, "reasons": ["contract_missing"],
    }
    assert client.get(
        "/api/projects/p1/contracts/history?limit=101"
    ).status_code == 422


def test_history_route_has_one_permanent_baseline_and_rejects_bad_cursor():
    client, harness = make_client()
    saved = client.put(
        "/api/projects/p1/contract-draft", json=save_body(harness)
    ).json()
    first = client.post("/api/projects/p1/contracts/confirm", json={
        "idempotencyKey": "history-route-first",
        "expectedDraftVersion": saved["draftVersion"],
        "expectedDraftHash": saved["contentHash"],
    })
    clone = client.post("/api/projects/p1/contracts/1/clone")

    first_page = client.get("/api/projects/p1/contracts/history?limit=1")
    second_page = client.get(
        "/api/projects/p1/contracts/history?limit=1&beforeRevision=1"
    )

    assert first.status_code == 201
    assert clone.status_code == 409
    assert clone.json()["code"] == "contract_already_confirmed"
    assert [item["revision"] for item in first_page.json()["items"]] == [1]
    assert first_page.json()["nextBeforeRevision"] is None
    assert second_page.json() == {"items": [], "nextBeforeRevision": None}
    for cursor in ("0", "-1", "1.5", "true"):
        assert client.get(
            f"/api/projects/p1/contracts/history?beforeRevision={cursor}"
        ).status_code == 422
